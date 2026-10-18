"""Loopback Responses adapter: normalize Codex system messages for Qwen's template."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import hmac
import io
import json
import sqlite3
import time
import threading
import tempfile
import socket
import http.client
import os
import urllib.request
import urllib.error
from PIL import Image, ImageOps
from generation_trace import GenerationTrace
from vision_history import archive_observed_tool_images
from ui_image_gate import defer_ui_tool_images
from tool_directory import register_tools
from request_continuity import reconcile
from history_memory import HistoryMemory, archive_thread_id
from task_artifacts import TaskArtifacts
from core import (ROOT, api, load_settings, MODELS, selected_model, context_for, start_model,
                  active_model, runtime_context_for, OUTPUT_RESERVE, ADAPTER_VERSION, model_supports_vision)
from core import selected_backend
from core import reasoning_budget
from generation_guard import GuardStore, GuardStopped, InferenceWatch, guard_options, repeated_failure
from error_research import research_failure

from tool_call_recovery import diagnose_call, BATCH_GUIDANCE, decode_patch_arguments, ToolCallFormatError

INFERENCE_LOCK = threading.Lock()
STATUS_WRITE_LOCK = threading.Lock()

def write_status_json(path, value):
    """Best-effort atomic telemetry; Windows readers must not break inference."""
    temporary = None
    try:
        # Unique names prevent another process/thread from replacing our temp file.
        # Close the handle before replacing: Windows denies rename of open files.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp',
                delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False)
        # Windows may also deny simultaneous replaces of the destination itself.
        with STATUS_WRITE_LOCK:
            for attempt in range(5):
                try:
                    os.replace(temporary, path)
                    temporary = None
                    return True
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(.025 * (2 ** attempt))
    except OSError as error:
        print(f'Status snapshot unavailable: {path.name} '
              f'({type(error).__name__}, WinError {getattr(error, "winerror", None)})',
              flush=True)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return False

def append_runtime_state(body, text):
    # Updating the first system message invalidates an entire hybrid-model KV
    # prefix on every tool call. Put changing application evidence at the tail.
    inputs=body.get('input','')
    if isinstance(inputs,str):inputs=[{'role':'user','content':inputs}]
    body['input']=list(inputs)+[{'role':'user','content':[{'type':'input_text',
        'text':'[Application runtime context; existing task and authorization remain unchanged]\n'+text}]}]

def attach_task_state(body,root=ROOT):
    thread=archive_thread_id(body.get('instructions',''))
    if not thread:return None
    store=TaskArtifacts(root)
    state=store.current(thread)
    if state:append_runtime_state(body,store.instructions(thread))
    return state

def save_generation_phase(phase, tool_name=None, trace_name=None):
    # Status contains only a stage and tool name, never prompt or generated text.
    write_status_json(ROOT/'generation-status.json',
        {'phase': phase, 'tool_name': tool_name, 'trace_file': trace_name})

def compatible_image_url(url):
    """Transcode codecs stb_image cannot read without discarding the attachment."""
    if not isinstance(url,str) or not url.startswith('data:image/'):
        return url,False
    try:
        header,encoded=url.split(',',1)
        if not header.endswith(';base64'):
            raise ValueError('Invalid image encoding')
        raw=base64.b64decode(encoded,validate=True)
        if raw.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8',b'GIF87a',b'GIF89a',b'BM')):
            return url,False
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            image=ImageOps.exif_transpose(source)
            image=image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
            output=io.BytesIO()
            image.save(output,format='PNG')
        return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii'),True
    except (OSError,ValueError,Image.DecompressionBombError) as error:
        raise ValueError('图片附件无法解析，请重新添加原图片（支持 PNG、JPEG 和 WebP）。') from error

def contains_input_images(body):
    def contains(value):
        if isinstance(value, list):
            return any(contains(item) for item in value)
        if isinstance(value, dict):
            return value.get('type') in ('input_image', 'image_url', 'image') or any(contains(item) for item in value.values())
        return False
    return contains(body.get('input')) or contains(body.get('messages'))


def normalize_media(body):
    converted=0
    def content_blocks(blocks):
        nonlocal converted
        if not isinstance(blocks,list):
            return
        references=[]
        for index,block in enumerate(blocks):
            if not isinstance(block,dict) or block.get('type') not in ('input_image','image_url'):
                continue
            value=block.get('image_url')
            if isinstance(value,dict):
                url,changed=compatible_image_url(value.get('url'))
                value['url']=url
            else:
                url,changed=compatible_image_url(value)
                block['image_url']=url
            converted+=int(changed)
            encoded_url=url
            if isinstance(encoded_url,str) and encoded_url.startswith('data:image/'):
                try:
                    raw=base64.b64decode(encoded_url.split(',',1)[1],validate=True)
                    with Image.open(io.BytesIO(raw)) as coordinate_image:
                        width,height=coordinate_image.size
                    reference=f'[Image coordinate reference: encoded image {width}x{height}. For UI pointing return normalized x,y in [0,1] relative to image content, then use coordinate mapping tools. Encoded/preview pixels are not necessarily device or desktop pixels; do not tap them directly.]'
                    if index==0 or not isinstance(blocks[index-1],dict) or blocks[index-1].get('text')!=reference:
                        references.append((index,{'type':'input_text' if block.get('type')=='input_image' else 'text','text':reference}))
                except (ValueError,OSError,Image.DecompressionBombError):pass
        for index,reference in reversed(references):blocks.insert(index,reference)
    for field in ('input','messages'):
        items=body.get(field)
        if isinstance(items,list):
            for item in items:
                if isinstance(item,dict):
                    content_blocks(item.get('content'))
                    content_blocks(item.get('output'))
    return converted

def content_text(content):
    if isinstance(content, str):
        return content
    return '\n'.join(x.get('text', '') for x in (content or []) if isinstance(x,dict))

def tool_response_routes(tools):
    """Keep the advertised identity for each flattened llama.cpp tool name."""
    routes,custom_names={},set()
    def visit(items,namespace=''):
        for tool in items:
            if tool.get('type')=='namespace':
                visit(tool.get('tools',[]),namespace+'__'+tool['name'] if namespace else tool['name'])
                continue
            name=tool['name'];flat=namespace+'__'+name if namespace else name
            if namespace:routes[flat]={'name':name,'namespace':namespace}
            if tool.get('type')=='custom':custom_names.add(flat)
    visit(tools)
    return routes,custom_names

def restore_tool_identity(item,routes):
    if item.get('type') in ('function_call','custom_tool_call'):
        identity=routes.get(item.get('name'))
        if identity:item.update(identity)
    return item

def retain_execution_state(body,memory=None):
    thread_id=archive_thread_id(body.get('instructions'))
    if not thread_id:return 0
    memory=HistoryMemory(ROOT) if memory is None else memory
    state=memory.execution_snapshot(thread_id)
    blocked=GuardStore(ROOT).read(thread_id)
    if blocked.get('blocked') and blocked.get('code')=='repeated_failure':
        GuardStore(ROOT).reset(thread_id)
    elif blocked.get('blocked'):raise GuardStopped(blocked['reason'])
    if state['failures']:
        append_runtime_state(body,memory.execution_instructions(state))
        repeated=repeated_failure(state,guard_options(load_settings())['repeated_failures'])
        if repeated:
            append_runtime_state(body,'Recovery required: repeated failure detected. Continue the authorized task. Do not repeat the unchanged failing command. Diagnose the actual interpreter, dependency and error first, then change one cause and verify it. ModuleNotFoundError means the selected interpreter lacks that module; use that exact interpreter with -m pip, or select an already working environment. Historical failures are evidence, not a reason to stop all tool calls.')
        save_generation_phase('research')
        reference=research_failure(ROOT,state)
        if reference:append_runtime_state(body,reference)
    return len(state['failures'])

def normalize(body):
    body['reasoning_budget_tokens']=reasoning_budget()
    body.pop('thinking_budget_tokens',None)
    # Native Codex groups MCP tools in Responses namespaces. llama.cpp needs
    # flat names. Restore the advertised namespace/name on the return path.
    def flatten(items,prefix=''):
        for original in items:
            tool=dict(original)
            if tool.get('type')=='namespace':
                yield from flatten(tool.get('tools',[]),prefix+tool['name']+'__')
            else:
                if prefix:tool['name']=prefix+tool['name']
                if tool.get('type')=='custom':
                    tool['type']='function';tool.pop('format',None)
                    tool['parameters']={'type':'object','properties':{'input':{
                        'type':'string','description':'Exact raw tool input. For apply_patch, include the full *** Begin Patch / *** End Patch patch.'}},
                        'required':['input'],'additionalProperties':False}
                yield tool
    if 'tools' in body:body['tools']=list(flatten(body['tools']))
    inputs = body.get('input')
    if not isinstance(inputs, list):
        return body
    instructions = [body['instructions']] if body.get('instructions') else []
    kept = []
    for item in inputs:
        if isinstance(item, dict) and item.get('role') in ('system', 'developer'):
            instructions.append(content_text(item.get('content')))
        else:
            kept.append(item)
    body['instructions'] = '\n\n'.join(instructions)
    body['input'] = kept
    for item in kept:
        if isinstance(item,dict) and item.get('type') == 'custom_tool_call':
            item['type'] = 'function_call'
            item['arguments'] = json.dumps({'input':item.pop('input','')},ensure_ascii=False)
        elif isinstance(item,dict) and item.get('type') == 'custom_tool_call_output':
            item['type'] = 'function_call_output'
        if isinstance(item,dict) and item.get('type')=='function_call' and item.get('namespace'):
            item['name']=item.pop('namespace')+'__'+item['name']
    return body

def responses_chat(body):
    """Mirror the installed llama.cpp Responses-to-chat conversion for counting.

    Only the counting copy is converted; inference receives the original request.
    This preserves the exact model template, tool schemas and previous reasoning.
    """
    messages=[]
    if 'instructions' in body:
        messages.append({'role':'system','content':body['instructions']})
    inputs=body.get('input',[])
    if isinstance(inputs,str):
        inputs=[{'role':'user','content':inputs}]
    for original in inputs:
        item=dict(original)
        content=item.get('content')
        if isinstance(content,str):
            content=[{'type':'input_text','text':content}]
        merge=bool(messages and messages[-1].get('role')=='assistant')
        role,kind=item.get('role'),item.get('type')
        if role in ('user','system','developer'):
            message={k:v for k,v in item.items() if k not in ('type','status','content')}
            message['content']=chat_content(content or [])
            messages.append(message)
        elif role=='assistant' and kind=='message':
            converted=chat_content(content or [])
            if merge:
                messages[-1].setdefault('content',[]).extend(converted)
            else:
                message={k:v for k,v in item.items() if k not in ('type','status','content')}
                message['content']=converted
                messages.append(message)
        elif kind=='function_call':
            call={'type':'function','id':item['call_id'],'function':{
                'name':item['name'],'arguments':item['arguments']}}
            if not merge:
                messages.append({'role':'assistant'})
            messages[-1].setdefault('tool_calls',[]).append(call)
        elif kind=='function_call_output':
            output=item['output']
            messages.append({'role':'tool','tool_call_id':item['call_id'],
                             'content':chat_content(output) if isinstance(output,list) else output})
        elif kind=='reasoning':
            blocks=item.get('content') or []
            if not blocks or not isinstance(blocks[0].get('text'),str):
                raise ValueError('Unsupported reasoning input for token counting')
            if not merge:
                messages.append({'role':'assistant','content':[]})
            messages[-1]['reasoning_content']=blocks[0]['text']
        else:
            raise ValueError('Unsupported input item for token counting')
    chat={k:v for k,v in body.items() if k not in ('input','instructions','tools','reasoning','max_output_tokens')}
    chat['messages']=messages
    tools=[]
    for tool in body.get('tools',[]):
        if tool.get('type')=='function':
            function={k:v for k,v in tool.items() if k!='type'}
            function.setdefault('strict',True)
            tools.append({'type':'function','function':function})
    if tools:
        chat['tools']=tools
    if (body.get('reasoning') or {}).get('effort'):
        chat['reasoning_effort']=body['reasoning']['effort']
    return chat

def chat_content(content):
    converted=[]
    for block in content:
        kind=block.get('type')
        if kind in ('input_text','output_text','text'):
            converted.append({'type':'text','text':block['text']})
        elif kind=='input_image':
            converted.append({'type':'image_url','image_url':{'url':block['image_url']}})
        elif kind in ('image_url','refusal'):
            converted.append(dict(block))
        else:
            raise ValueError('Unsupported content for token counting')
    return converted


def _skill_output_text(output):
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return '\n'.join(str(item.get('text','')) for item in output if isinstance(item,dict))
    return json.dumps(output,ensure_ascii=False) if output is not None else ''


def _skill_result_metadata(output_text):
    """Extract only safe metadata from a skill_read tool result, never its body."""
    pending=[output_text]
    seen=set()
    while pending:
        text=pending.pop(0)
        if not isinstance(text,str) or text in seen:
            continue
        seen.add(text)
        try:
            value=json.loads(text)
        except (TypeError,ValueError):
            continue
        if isinstance(value,dict):
            if isinstance(value.get('name'),str) and ('body' in value or 'total_chars' in value):
                return {key:value.get(key) for key in ('name','path','revision','offset','total_chars','next_offset')}
            for key in ('structuredContent','result','content'):
                nested=value.get(key)
                if isinstance(nested,str):pending.append(nested)
                elif isinstance(nested,list):
                    pending.extend(item.get('text','') for item in nested if isinstance(item,dict))
                elif isinstance(nested,dict):pending.append(json.dumps(nested,ensure_ascii=False))
    return None


def skill_read_request_stats(body):
    """Summarize Skill bodies present in the exact Responses input, without logging text."""
    inputs=body.get('input',[])
    if not isinstance(inputs,list):
        return {'skill_reads_this_turn':[],'skill_reads_earlier_history':[],'skill_output_tokens_this_turn':0}
    # Runtime MCP/tool-catalog hints are sometimes appended as bare
    # {role: user, content: ...} items. They are not a new user turn and must
    # not move Skill reads into the historical bucket.
    last_user=max((index for index,item in enumerate(inputs)
                   if isinstance(item,dict) and item.get('role')=='user' and
                   item.get('type') in ('message','input_message')),default=-1)
    calls={}
    for item in inputs:
        if not isinstance(item,dict) or item.get('type')!='function_call':
            continue
        name=str(item.get('name','')).split('__')[-1]
        if name=='skill_read' and item.get('call_id'):
            calls[item['call_id']]=True
    current=[]
    historical=[]
    for index,item in enumerate(inputs):
        if not isinstance(item,dict) or item.get('type')!='function_call_output':
            continue
        if item.get('call_id') not in calls:
            continue
        output_text=_skill_output_text(item.get('output'))
        metadata=_skill_result_metadata(output_text)
        if not metadata:
            continue
        entry={key:value for key,value in metadata.items() if value is not None}
        entry['output_chars']=len(output_text)
        is_current=(index>last_user) if last_user>=0 else True
        if is_current:
            try:
                if selected_backend()=='moe4all':
                    entry['output_tokens']=None
                else:
                    entry['output_tokens']=len(api('/tokenize',{
                        'content':output_text,'add_special':True,'parse_special':True},timeout=30)['tokens'])
            except (OSError,ValueError,KeyError,TypeError):
                entry['output_tokens']=None
            current.append(entry)
        else:
            historical.append(entry)
    return {'skill_reads_this_turn':current[-10:],
            'skill_reads_earlier_history':historical[-20:],
            'skill_output_tokens_this_turn':sum(row.get('output_tokens') or 0 for row in current)}


def skill_read_reuse_context(body):
    """Return a short guard against repeating a completed Skill chunk this turn."""
    inputs=body.get('input',[])
    if not isinstance(inputs,list):return ''
    last_user=max((index for index,item in enumerate(inputs)
                   if isinstance(item,dict) and item.get('role')=='user' and
                   item.get('type') in ('message','input_message')),default=-1)
    completed={item.get('call_id') for item in inputs[last_user+1:]
               if isinstance(item,dict) and item.get('type')=='function_call_output' and item.get('call_id')}
    reads=[]
    for item in inputs[last_user+1:]:
        if not isinstance(item,dict) or item.get('type')!='function_call' or item.get('call_id') not in completed:
            continue
        if str(item.get('name','')).split('__')[-1]!='skill_read':continue
        raw=item.get('arguments',{})
        try:args=json.loads(raw) if isinstance(raw,str) else raw
        except (ValueError,TypeError):args={}
        if isinstance(args,dict) and isinstance(args.get('input'),str):
            try:args=json.loads(args['input'])
            except (ValueError,TypeError):args={}
        if not isinstance(args,dict):args={}
        name=args.get('name')
        if isinstance(name,str) and name:
            offset=args.get('offset',0)
            offset=offset if isinstance(offset,int) and offset>=0 else 0
            reads.append((name,offset))
    unique=list(dict.fromkeys(reads))
    if not unique:return ''
    labels=', '.join(f'{name} offset {offset}' for name,offset in unique[-8:])
    return ('Already returned Skill chunks in this user task: '+labels+'. Reuse those exact results; '
            'do not call skill_read again for a listed Skill/offset. Read only a different next_offset '
            'if the returned chunk proves more instructions are required. If a read failed, inspect its '
            'error and change the attempt instead of resending it unchanged.')


def encode_upstream_body(body):
    """Serialize the final normalized Responses request exactly as sent upstream."""
    return json.dumps(body,ensure_ascii=False).encode('utf-8')

def count_prompt_tokens(body, route):
    if selected_backend()=='moe4all':
        # This engine does not expose a tokenizer route. It grows physical KV
        # itself, so leave the exact count unknown instead of counting chunks,
        # estimating characters, or reloading a second model for tokenization.
        return None
    image_count=0
    if route=='/completion':
        prompt=body['prompt']
    else:
        chat=responses_chat(body) if route=='/v1/responses' else dict(body)
        # Do not decode/download images twice. Count their text placeholders plus
        # the configured 2048-token maximum for each image conservatively.
        messages=[]
        for original in chat.get('messages',[]):
            message=dict(original)
            if isinstance(message.get('content'),list):
                parts=[]
                for block in message['content']:
                    if block.get('type')=='image_url':
                        image_count+=1
                        parts.append({'type':'text','text':'<image>'})
                    else:
                        parts.append(block)
                message['content']=parts
            messages.append(message)
        chat['messages']=messages
        prompt=api('/apply-template',chat,timeout=30)['prompt']
    tokens=api('/tokenize',{'content':prompt,'add_special':True,'parse_special':True},timeout=30)['tokens']
    return len(tokens)+image_count*2048

def request_output_reserve(body):
    for key in ('max_output_tokens','max_tokens','n_predict'):
        value=body.get(key)
        if isinstance(value,int) and value>0:
            return value
    # This is allocation headroom only, never a generation or reasoning limit.
    return OUTPUT_RESERVE

def fit_generation_to_window(body,route,context,prompt_tokens):
    if prompt_tokens is None:return {}
    field='max_output_tokens' if route=='/v1/responses' else 'max_tokens' if route=='/v1/chat/completions' else 'n_predict'
    remaining=max(1,context-int(prompt_tokens)-256)
    budget=min(int(body[field]),remaining)
    body[field]=budget
    if isinstance(body.get('reasoning_budget_tokens'),int):
        body['reasoning_budget_tokens']=min(body['reasoning_budget_tokens'],max(0,budget-4096))
    return {'effective_output_budget':budget,'remaining_context':remaining,'effective_reasoning_budget':body.get('reasoning_budget_tokens')}

def route_inference(body, route, settings, name, media_converted=0, vision_stats=None):
    ceiling=context_for(settings,name)
    start_model(name,ceiling,wait=True)
    reserve=request_output_reserve(body)
    try:
        prompt_tokens=count_prompt_tokens(body,route)
        count_error=None
    except (OSError,ValueError,KeyError,TypeError) as error:
        # Unknown multimodal/formats must use the full window, never truncate.
        prompt_tokens=None
        count_error=type(error).__name__
    target=ceiling if prompt_tokens is None else runtime_context_for(settings,name,prompt_tokens,reserve)
    fitted=fit_generation_to_window(body,route,target,prompt_tokens)
    previous=active_model()
    record={'model':name,'context_limit':ceiling,'prompt_tokens':prompt_tokens,
        'output_reserve':reserve,'target_context':target,'count_error':count_error,
        'media_converted_to_png':media_converted,
        'phase':'switching' if previous.get('context')!=target else 'ready'}
    if route=='/v1/responses':
        try:record.update(skill_read_request_stats(body))
        except (OSError,ValueError,TypeError,KeyError):
            record.update(skill_reads_this_turn=[],skill_reads_earlier_history=[],
                          skill_output_tokens_this_turn=None)
    record.update(vision_stats or {})
    record['request_started_at']=time.time()
    record.update(fitted)
    thread_id=archive_thread_id(body.get('instructions'))
    if thread_id:record['thread_id']=thread_id
    path=ROOT/'request-routing.json'
    def save():
        return write_status_json(path, record)
    save()
    start_model(name,ceiling,wait=True,prompt_tokens=prompt_tokens,output_reserve=reserve,
                full_context=prompt_tokens is None)
    record.update(phase='ready',runtime_context=active_model().get('context'),
                  kv_cache_location=active_model().get('kv_cache_location'),
                  backend=active_model().get('backend','vulkan'),reasoning_budget=reasoning_budget(settings))
    save()
    print('inference routing: '+json.dumps(record),flush=True)
    return record

def custom_item(item, names):
    if item.get('type') == 'function_call' and item.get('name') in names:
        arguments = item.pop('arguments','')
        try:
            value = json.loads(arguments).get('input','') if arguments else ''
        except ValueError:
            value = arguments
        item['type'] = 'custom_tool_call'
        item['input'] = value
    return item

def adapt_event(data, names, ids, routes=None):
    routes={} if routes is None else routes
    item = data.get('item')
    if isinstance(item,dict) and item.get('type') == 'function_call' and item.get('name') in names:
        ids.add(item['id'])
        custom_item(item,names)
    if isinstance(item,dict):restore_tool_identity(item,routes)
    kind = data.get('type','')
    if data.get('item_id') in ids:
        if kind == 'response.function_call_arguments.delta':
            return []  # Wait for complete JSON, then emit a single raw patch delta.
        if kind == 'response.function_call_arguments.done':
            value = decode_patch_arguments(data.pop('arguments','{}'))
            delta = {**data,'type':'response.custom_tool_call_input.delta','delta':value}
            data['type'] = 'response.custom_tool_call_input.done'
            data['input'] = value
            return [delta,data]
    if isinstance(data.get('response'),dict):
        for item in data['response'].get('output',[]):
            custom_item(item,names)
            restore_tool_identity(item,routes)
        if data.get('type')=='response.completed':
            output=data['response'].get('output',[])
            actionable=any(item.get('type') in ('function_call','custom_tool_call') or
                (item.get('type')=='message' and any(block.get('text','').strip() for block in item.get('content',[])))
                for item in output)
            if not actionable:
                data['type']='response.failed'
                data['response']['status']='failed'
                data['response']['error']={'code':'server_error',
                    'message':'本地模型本轮仅产生思考内容，没有正文或工具调用。可能已用完可用上下文，请压缩对话或增加窗口后重试。'}
    return [data]

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        if self.command == 'POST' and self.path.split('?')[0] in ('/v1/responses', '/v1/chat/completions', '/completion'):
            with INFERENCE_LOCK:
                self.forward_request()
        else:
            self.forward_request()

    def forward_request(self):
        self.trace = None
        self.trace_outcome = 'proxy_error'
        self.trace_http_status = None
        try:
            self._forward_request()
        finally:
            if self.trace is not None:
                self.trace.finish(self.trace_outcome, self.trace_http_status)
                save_generation_phase('finished', trace_name=self.trace.path.name if self.trace.path else None)
                self.trace = None

    def _forward_request(self):
        # Each request owns its body and upstream stream. Close the client connection
        # too, so idle keep-alive threads cannot retain a previous 100K request body.
        self.close_connection = True
        expected = 'Bearer ' + load_settings()['api_key']
        if not hmac.compare_digest(self.headers.get('Authorization',''), expected):
            self.send_error(401)
            return
        route=self.path.split('?')[0]
        if self.command=='POST' and route=='/guard/reset':
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<2048:self.send_error(400);return
            value=json.loads(self.rfile.read(length))
            thread=value.get('thread_id')
            if not isinstance(thread,str) or len(thread)>128:self.send_error(400);return
            GuardStore(ROOT).reset(thread)
            result=b'{"ok":true}'
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
            return
        if self.command == 'GET' and route in ('/health','/v1/models'):
            data={'status':'ok','adapter_version':ADAPTER_VERSION,'request_continuity':'historical-boundaries-v1'} if route=='/health' else {
                'object':'list', 'data':[{'id':name,'object':'model','owned_by':'local','created':0} for name in MODELS]}
            result=json.dumps(data).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(result)))
            self.send_header('Connection','close')
            self.end_headers()
            self.wfile.write(result)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if length > 64 * 1024 * 1024:
            self.send_error(413)
            return
        payload = self.rfile.read(length) if length else None
        custom_names = set()
        tool_routes = {}
        advertised={}
        tool_execution_enabled=False
        watch=None
        options=guard_options(load_settings())
        inference=payload is not None and route in ('/v1/responses','/v1/chat/completions','/completion')
        thread_id=None
        if payload is not None and self.path.split('?')[0] in ('/v1/responses', '/v1/chat/completions', '/completion'):
            try:
                body = json.loads(payload)
                settings = load_settings()
                name = body.get('model') or selected_model(settings)
                if name not in MODELS:
                    self.send_error(400, 'Unknown local model')
                    return
                if not model_supports_vision(name) and contains_input_images(body):
                    raise ValueError('当前模型不能接收图片，请选择支持视觉的模型。')
                if route == '/v1/responses':
                    tool_routes,custom_names = tool_response_routes(body.get('tools',[]))
                    body = normalize(body)
                    deferred_ui_images=defer_ui_tool_images(body)
                    vision_stats=archive_observed_tool_images(body)
                    vision_stats['deferred_ui_images']=deferred_ui_images
                    original_input_count = len(body.get('input', []))
                    vision_stats.update(register_tools(body))
                    skill_reuse=skill_read_reuse_context(body)
                    if skill_reuse:append_runtime_state(body,skill_reuse)
                    try:
                        retained_failures=retain_execution_state(body)
                    except (OSError,ValueError,sqlite3.Error) as error:
                        retained_failures=-1
                        print('Execution evidence unavailable: '+type(error).__name__,flush=True)
                    task_state=attach_task_state(body)
                else:
                    vision_stats={}
                    body['reasoning_budget_tokens']=reasoning_budget(settings)
                    body.pop('thinking_budget_tokens',None)
                options=guard_options(settings)
                budget_field='max_output_tokens' if route=='/v1/responses' else 'max_tokens' if route=='/v1/chat/completions' else 'n_predict'
                requested=body.get(budget_field)
                body[budget_field]=min(requested,options['output_tokens']) if isinstance(requested,int) and requested>0 else options['output_tokens']
                thread_id=archive_thread_id(body.get('instructions'))
                if route=='/v1/responses' and thread_id:
                    # The desktop profile is the user's chosen token budget.
                    # Do not let an engine's old model default silently shrink it.
                    body[budget_field]=options['output_tokens']
                advertised={t['name']:t for t in body.get('tools',[]) if isinstance(t,dict) and t.get('name')}
                choice=body.get('tool_choice')
                tool_execution_enabled=bool(advertised) and choice!='none' and not (isinstance(choice,dict) and choice.get('type')=='none')
                if tool_execution_enabled and route=='/v1/responses':
                    append_runtime_state(body,BATCH_GUIDANCE)
                media_converted=normalize_media(body)
                if route == '/v1/responses':
                    try:
                        vision_stats.update(reconcile(body, original_input_count, archive_thread_id(body.get('instructions'))))
                    except (OSError, ValueError, TypeError, KeyError) as error:
                        print('Request continuity unavailable: ' + type(error).__name__, flush=True)
                routing = route_inference(body,route,settings,name,media_converted,vision_stats)
                if selected_backend(settings)=='moe4all':
                    from moe4all_backend import normalize_request
                    body=normalize_request(body,route)
                if route=='/v1/responses':routing['retained_execution_failures']=retained_failures
                if route=='/v1/responses' and task_state:
                    routing['artifact_task_id']=task_state['task_id']
                    routing['draft_directory']=task_state['draft_directory']
                payload = encode_upstream_body(body)
                streaming = bool(body.get('stream'))
                del body
            except (ValueError, TypeError, GuardStopped) as error:
                result=json.dumps({'error':{'code':400,'type':'invalid_request_error',
                    'message':str(error) or '请求格式不正确。'}},ensure_ascii=False).encode('utf-8')
                self.send_response(400)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(result)))
                self.send_header('Connection','close')
                self.end_headers()
                self.wfile.write(result)
                return
            except (OSError, RuntimeError) as error:
                result=json.dumps({'error':{'code':'local_gateway_unavailable',
                    'type':'server_error','message':str(error) or '本地模型接口暂时不可用。'}},
                    ensure_ascii=False).encode('utf-8')
                self.send_response(503)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(result)))
                self.send_header('Connection','close')
                self.end_headers()
                self.wfile.write(result)
                return
            if route == '/v1/responses' and streaming:
                self.trace = GenerationTrace(ROOT/'logs'/'generation', routing)
                if routing.get('thread_id') and self.trace.path:
                    try:
                        HistoryMemory(ROOT).register_source(routing['thread_id'],self.trace.path,'trace')
                    except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:
                        print('History trace link unavailable: '+type(error).__name__,flush=True)
                save_generation_phase('waiting', trace_name=self.trace.path.name if self.trace.path else None)
        upstream=http.client.HTTPConnection('127.0.0.1',8080,timeout=None if inference else options['prefill_seconds'])
        if inference:
            watch=InferenceWatch(ROOT,thread_id,options,upstream,self.connection,active_model().get('pid'),tool_enabled=tool_execution_enabled)
            watch.start()
        try:
            upstream.request(self.command,self.path,body=payload,
                headers={'Authorization':expected,'Content-Type':'application/json','Accept-Encoding':'identity'})
            response=upstream.getresponse()
            if watch:watch.remember_socket(response)
        except (OSError,http.client.HTTPException) as e:
            if watch:watch.finish()
            else:upstream.close()
            self.trace_outcome = 'upstream_connection_error'
            if watch and watch.stopped.is_set():
                result=json.dumps({'error':{'type':'invalid_request_error','message':watch.reason}},ensure_ascii=False).encode('utf-8')
                self.send_response(400);self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
            else:self.send_error(502,str(e).encode('ascii','replace').decode())
            return
        try:
            with response:
                self.trace_http_status = response.status
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers.get('Content-Type','application/json'))
                self.send_header('Transfer-Encoding','chunked')
                self.send_header('Cache-Control','no-cache')
                self.send_header('Connection','close')
                self.end_headers()
                def write_chunk(block):
                    self.wfile.write(f'{len(block):x}\r\n'.encode()+block+b'\r\n')
                    self.wfile.flush()
                if route=='/v1/responses' and 'text/event-stream' in response.headers.get('Content-Type',''):
                    event_lines, ids = [], set()
                    while line := response.readline():
                        if line.strip():
                            event_lines.append(line)
                            continue
                        data_lines = [x[5:].strip() for x in event_lines if x.startswith(b'data:')]
                        if data_lines and data_lines[0] != b'[DONE]':
                            data = json.loads(b'\n'.join(data_lines))
                            original_type = data.get('type')
                            if self.trace is not None:
                                self.trace.event(data)
                            if watch:
                                watch.event(data)
                                for warning in watch.warnings:
                                    if self.trace:self.trace.diagnostic(warning)
                                watch.warnings.clear()
                                if original_type=='response.output_item.done':
                                    item=data.get('item') or {}
                                    if item.get('type')=='function_call':
                                        problem=diagnose_call(item,advertised)
                                        if problem:
                                            code,reason=problem
                                            watch.stop(reason,code=code)
                                            raise GuardStopped(watch.reason)
                            if original_type == 'response.output_item.added':
                                item = data.get('item') or {}
                                save_generation_phase(item.get('type'), item.get('name'), self.trace.path.name if self.trace and self.trace.path else None)
                            if not original_type:
                                # Backend stream errors may have no event type;
                                # preserve them instead of raising a KeyError.
                                write_chunk(b''.join(event_lines)+b'\n')
                                event_lines = []
                                continue
                            for transformed in adapt_event(data,custom_names,ids,tool_routes):
                                if self.trace is not None and transformed.get('type') != original_type and transformed.get('type') in ('response.failed','response.incomplete'):
                                    self.trace.adapter_terminal(transformed)
                                text = 'event: '+transformed['type']+'\ndata: '+json.dumps(transformed,ensure_ascii=False)+'\n\n'
                                write_chunk(text.encode('utf-8'))
                        else:
                            write_chunk(b''.join(event_lines)+b'\n')
                        event_lines = []
                elif (custom_names or tool_routes) and response.status == 200:
                    data = json.load(response)
                    for item in data.get('output',[]):
                        custom_item(item,custom_names)
                        restore_tool_identity(item,tool_routes)
                    write_chunk(json.dumps(data,ensure_ascii=False).encode('utf-8'))
                else:
                    while block := response.read1(65536):
                        write_chunk(block)
                if watch and watch.stopped.is_set():raise GuardStopped(watch.reason)
                terminal=(self.trace.adapter_outcome or self.trace.terminal) if self.trace else None
                if route=='/v1/responses' and streaming and response.status==200 and self.trace and terminal is None:
                    raise OSError('Model stream ended without a terminal response event.')
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
                terminal=(self.trace.adapter_outcome or self.trace.terminal) if self.trace else None
                self.trace_outcome = ('completed' if terminal=='response.completed' else
                    'upstream_failed' if terminal=='response.failed' else
                    'upstream_incomplete' if terminal=='response.incomplete' else
                    'upstream_eof') if response.status==200 else 'upstream_http_error'
        except (BrokenPipeError, ConnectionResetError):
            self.trace_outcome = 'client_disconnected'
            if watch:watch.stop('客户端已断开，后台推理已取消。',notify=False)
        except (GuardStopped,ToolCallFormatError,OSError,http.client.HTTPException) as error:
            if self.trace:
                self.trace.diagnostic('stream_exception: '+type(error).__name__+': '+str(error)[:300])
            if isinstance(error,ToolCallFormatError) and watch:
                watch.stop(str(error),code=error.code)
            self.trace_outcome='guard_stopped' if watch and watch.stopped.is_set() else 'upstream_stream_error'
            if watch and not watch.stopped.is_set():watch.stop('模型流意外中断，已停止本轮并保留日志。',code='upstream_stream_error')
            if watch:
                event=watch.failed_event()
                if self.trace:self.trace.adapter_terminal(event)
                try:
                    if route=='/v1/responses':write_chunk(('event: response.failed\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode('utf-8'))
                    self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
                except OSError:pass
        finally:
            if watch:watch.finish()
            else:upstream.close()

class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

def serve():
    LocalServer(('127.0.0.1',8081), Handler).serve_forever()

if __name__ == '__main__':
    serve()
