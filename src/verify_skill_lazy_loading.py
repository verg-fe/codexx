"""Verify metadata-only Skill discovery and tokenizer counts for final Responses requests."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).parent
WORK = Path(r'G:\LocalCodex-work\mycodex-repair-20261009')
DEPLOY_INTERNAL = WORK / 'deploy' / 'MyCodex-v82-lazy-schemas-95k' / 'MyCodex' / '_internal'
DEPLOY_SKILLS = DEPLOY_INTERNAL / 'skills'
ROOT = Path(r'D:\LocalCodex')
OUT = WORK / 'artifacts' / 'lazy-skill-mcp-index-20261012'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SOURCE))

import core
import gateway
from history_memory import TOOLS as HISTORY_TOOLS, memory_instructions
from skill_memory import SkillMemory
from tool_call_recovery import BATCH_GUIDANCE
import tool_directory

MCP_TOOLS_JSON = WORK / 'artifacts' / 'skill-lazy-loading-20261010' / 'mcp-tools.json'


def app_developer_instructions():
    tree = ast.parse((SOURCE / 'app.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'BASE_DEVELOPER_INSTRUCTIONS'
                for target in node.targets):
            def evaluate(value):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
                    return evaluate(value.left) + evaluate(value.right)
                raise AssertionError('BASE_DEVELOPER_INSTRUCTIONS is no longer a string literal.')
            return evaluate(node.value)
    raise AssertionError('BASE_DEVELOPER_INSTRUCTIONS was not found.')


def skill_tools_namespace():
    return {'type': 'namespace', 'name': 'local_history', 'tools': [
        {'type': 'custom', 'name': tool['name'], 'description': tool['description'],
         'parameters': tool['inputSchema']} for tool in HISTORY_TOOLS
    ]}


def active_mcp_namespaces():
    if not MCP_TOOLS_JSON.is_file():
        return []
    namespaces = []
    for server_name, server in json.loads(MCP_TOOLS_JSON.read_text(encoding='utf-8')).items():
        if server.get('status') != 'ok':
            continue
        tools = []
        for tool in server.get('tools', []):
            tools.append({'type': 'custom', 'name': tool['name'],
                         'description': tool.get('description', ''),
                         'parameters': tool.get('inputSchema', {})})
        if tools:
            namespaces.append({'type': 'namespace',
                               'name': server_name, 'tools': tools})
    return namespaces


def request_tools():
    # Replicate the live workspace request: every configured MCP server
    # contributes its namespace (17 servers / 154 tools at 2026-10-10).
    other = [namespace for namespace in active_mcp_namespaces()
             if namespace['name'] != 'local_history']
    return [skill_tools_namespace()] + other


class LazyIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skill-lazy-fixture-', dir=OUT)
        self.root = Path(self.temp.name)
        self.skill_dir = self.root / 'codex-home' / 'skills' / 'body-only-term'
        self.skill_dir.mkdir(parents=True)
        self.bundle = self.root / 'bundle' / 'skills'
        self.bundle.mkdir(parents=True)
        self.skill_path = self.skill_dir / 'SKILL.md'
        self.skill_path.write_text('---\nname: body-only-term\ndescription: Only for metadata lookup verification.\n---\n\n'
                                  + ('secret_body_marker ' * 50000), encoding='utf-8')
        local_dir = self.root / 'codex-home' / 'skills' / 'android-local-toolchain'
        local_dir.mkdir(parents=True)
        (local_dir / 'SKILL.md').write_text(
            '---\nname: android-local-toolchain\ndescription: Local Android tools and paths.\n---\n\n'
            + ('local_toolchain_body ' * 1000), encoding='utf-8')
        self.memory = SkillMemory(self.root, bundle_root=self.root / 'bundle')

    def tearDown(self):
        self.temp.cleanup()

    def test_search_uses_frontmatter_only_and_does_not_match_body(self):
        with patch.object(self.memory, '_read', side_effect=AssertionError('search loaded a full body')):
            metadata = self.memory.search('metadata lookup verification', limit=3)
            body_only = self.memory.search('secret_body_marker', limit=3)
        self.assertEqual([row['name'] for row in metadata['skills']], ['body-only-term'])
        self.assertEqual(body_only['skills'], [])
        self.assertIn('metadata_revision', metadata['skills'][0])
        self.assertNotIn('revision', metadata['skills'][0])

    def test_selected_read_returns_body_in_bounded_chunks(self):
        result = self.memory.read('body-only-term', max_chars=16000)
        self.assertEqual(len(result['body']), 16000)
        self.assertEqual(result['offset'], 0)
        self.assertIsNotNone(result['next_offset'])
        continuation = self.memory.read('body-only-term', offset=result['next_offset'], max_chars=16000)
        self.assertEqual(continuation['offset'], 16000)
        self.assertIn('secret_body_marker', continuation['body'])

    def test_resident_index_reads_only_local_toolchain_frontmatter(self):
        read_paths = []
        original = self.memory._read_frontmatter
        def tracked(path):
            read_paths.append(Path(path).parent.name)
            return original(path)
        with patch.object(self.memory, '_read_frontmatter', side_effect=tracked):
            rows = self.memory.resident_index()
        self.assertEqual([row['name'] for row in rows], ['android-local-toolchain'])
        self.assertEqual(read_paths, ['android-local-toolchain'])
        self.assertNotIn('local_toolchain_body', json.dumps(rows))

    def test_turn_skill_context_keeps_only_the_local_toolchain_index(self):
        context=core.skill_reference_context('IDA Frida screenshot task',root=self.root,
                                            bundle_root=self.root/'bundle')
        self.assertIn('android-local-toolchain',context)
        self.assertNotIn('body-only-term',context)
        self.assertIn('local_history__skill_search',context)

    def test_compaction_handoff_is_bounded_and_does_not_trigger_rereads(self):
        from history_memory import memory_instructions
        self.assertIn('1,200 tokens',core.INSTRUCTIONS)
        self.assertIn('Do not call tools or reread history just because compaction is near',core.INSTRUCTIONS)
        context=memory_instructions('test-thread')
        self.assertIn('native compaction handoff rules',context)
        self.assertIn('new session',context)
        self.assertNotIn('save a checkpoint before compaction',context)



class ToolSchemaIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tool-index-fixture-', dir=OUT)
        self.root = Path(self.temp.name)
        self.original_root = tool_directory.ROOT
        tool_directory.ROOT = self.root / 'catalogs'
        self.tools = [
            {'type':'function','name':'tool_directory__tool_catalog_search','parameters':{'type':'object'}},
            {'type':'custom','name':'local_history__skill_search','parameters':{'type':'object'}},
            {'type':'custom','name':'local_history__skill_read','parameters':{'type':'object'}},
            {'type':'function','name':'android__screen_capture','description':'Capture a fresh Android screenshot.','parameters':{'type':'object','properties':{'serial':{'type':'string'}},'required':['serial']}},
            {'type':'function','name':'ida_local__inspect_binary','description':'Inspect binary functions in IDA Pro.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}},
        ]
        self.body={'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'Inspect Android screen and binary.'}]}],
                   'tools':list(self.tools)}

    def tearDown(self):
        tool_directory.ROOT = self.original_root
        self.temp.cleanup()

    def test_initial_request_exposes_only_search_and_skill_tools(self):
        stats=tool_directory.register_tools(self.body)
        self.assertEqual(stats['tools_before_directory'],5)
        self.assertEqual(stats['tools_after_directory'],3)
        self.assertEqual({tool['name'] for tool in self.body['tools']},
                         {'tool_directory__tool_catalog_search','local_history__skill_search','local_history__skill_read'})

    def test_search_results_rehydrate_exact_schema_only_for_current_turn(self):
        initial=tool_directory.register_tools(self.body)
        result=tool_directory.search(initial['request_key'],'Android screenshot')
        self.assertEqual(result['matches'][0]['name'],'android__screen_capture')
        self.assertNotIn('parameters',result['matches'][0])
        self.body['input'].extend([
            {'type':'function_call','call_id':'catalog-1','name':'tool_directory__tool_catalog_search'},
            {'type':'function_call_output','call_id':'catalog-1',
             'output':'Wall time 0.0131 seconds\nOutput:\n'+json.dumps(result,ensure_ascii=False)},
        ])
        # The app-server sends its complete configured list again; the gateway
        # rehydrates only the names returned by this turn's catalog search.
        self.body['tools']=list(self.tools)
        selected=tool_directory.register_tools(self.body)
        by_name={tool['name']:tool for tool in self.body['tools']}
        self.assertIn('android__screen_capture',by_name)
        self.assertEqual(by_name['android__screen_capture']['parameters'],
                         {'type':'object','properties':{'serial':{'type':'string'}},'required':['serial']})
        self.assertNotIn('ida_local__inspect_binary',by_name)
        self.assertEqual(selected['selected_tool_names'],['android__screen_capture'])
        # A later user message starts a new selection scope; old MCP schemas
        # remain in transcript data but are no longer advertised to the model.
        self.body['input'].append({'type':'message','role':'user','content':[{'type':'input_text','text':'Just say hello.'}]})
        self.body['tools']=list(self.tools)
        reset=tool_directory.register_tools(self.body)
        self.assertEqual(reset['selected_tool_names'],[])
        self.assertNotIn('android__screen_capture',{tool['name'] for tool in self.body['tools']})

    def test_incremental_wrapped_tool_output_rehydrates_exact_schema(self):
        initial=tool_directory.register_tools(self.body)
        result=tool_directory.search(initial['request_key'],'Android screenshot')
        # This mirrors Codex's persisted MCP output wrapper. Incremental
        # Responses requests may carry only function_call_output because the
        # call itself is retained by previous_response_id.
        self.body={
            'input':[{'type':'function_call_output','call_id':'catalog-1',
                      'output':'Wall time 0.0131 seconds\nOutput:\n'+
                               json.dumps(result,ensure_ascii=False)}],
            'tools':list(self.tools),
        }
        selected=tool_directory.register_tools(self.body)
        by_name={tool['name']:tool for tool in self.body['tools']}
        self.assertEqual(selected['selected_tool_names'],['android__screen_capture'])
        self.assertEqual(by_name['android__screen_capture']['parameters'],
                         {'type':'object','properties':{'serial':{'type':'string'}},'required':['serial']})
        self.assertNotIn('ida_local__inspect_binary',by_name)

    def test_exec_command_from_real_catalog_result_is_advertised_next(self):
        command={'type':'function','name':'exec_command','description':'Runs a command in a PTY.',
                 'parameters':{'type':'object','properties':{'cmd':{'type':'string'}},'required':['cmd']}}
        original_tools=list(self.tools)+[command]
        first={'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'check process'}]}],
               'tools':original_tools}
        initial=tool_directory.register_tools(first)
        result=tool_directory.search(initial['request_key'],'exec_command')
        self.assertEqual(result['matches'][0]['name'],'exec_command')
        following={'input':[{'type':'function_call_output','call_id':'directory-call',
                             'output':'Wall time 0.0131 seconds\nOutput:\n'+
                                      json.dumps(result,ensure_ascii=False)}],
                   'tools':original_tools}
        selected=tool_directory.register_tools(following)
        by_name={tool['name']:tool for tool in following['tools']}
        self.assertIn('exec_command',selected['selected_tool_names'])
        self.assertEqual(by_name['exec_command'],command)

    def test_incremental_output_survives_unrelated_earlier_call(self):
        initial=tool_directory.register_tools(self.body)
        result=tool_directory.search(initial['request_key'],'Android screenshot')
        self.body={
            'input':[
                {'type':'function_call','call_id':'old-call','name':'some_other_tool'},
                {'type':'function_call_output','call_id':'new-catalog-call',
                 'output':'Wall time 0.01 seconds\nOutput:\n'+json.dumps(result,ensure_ascii=False)},
            ],
            'tools':list(self.tools),
        }
        selected=tool_directory.register_tools(self.body)
        self.assertEqual(selected['selected_tool_names'],['android__screen_capture'])
        self.assertIn('android__screen_capture',{tool['name'] for tool in self.body['tools']})

    def test_incremental_tool_output_with_wrong_request_key_is_ignored(self):
        initial=tool_directory.register_tools(self.body)
        result=tool_directory.search(initial['request_key'],'Android screenshot')
        result['request_key']='0'*32
        self.body={
            'input':[{'type':'function_call_output','call_id':'catalog-1',
                      'output':'Wall time 0.0131 seconds\nOutput:\n'+
                               json.dumps(result,ensure_ascii=False)}],
            'tools':list(self.tools),
        }
        selected=tool_directory.register_tools(self.body)
        self.assertEqual(selected['selected_tool_names'],[])
        self.assertNotIn('android__screen_capture',{tool['name'] for tool in self.body['tools']})


def _append_mcp_result(body, tool_name, arguments, result, call_id):
    body['input'].append({'type': 'function_call', 'call_id': call_id,
                          'name': 'local_history__' + tool_name,
                          'arguments': json.dumps({'input': json.dumps(arguments, ensure_ascii=False)},
                                                  ensure_ascii=False)})
    body['input'].append({'type': 'function_call_output', 'call_id': call_id,
                          'output': json.dumps(result, ensure_ascii=False)})


def actual_request_body(prompt, search_queries=(), read_names=(), mcp_search_queries=(), memory=None,
                        include_resident_index=True, extra_context='', filter_mcp_schemas=True):
    context = memory_instructions('00000000-0000-4000-8000-000000000001') + core.mcp_skill_index(prompt)
    if include_resident_index:
        context += '\n' + core.skill_reference_context(prompt, root=ROOT,
                                                       bundle_root=DEPLOY_SKILLS)
    if extra_context:
        context += '\n' + extra_context
    turn_text = core.compose_turn_input(prompt, context)
    body = {
        'model': core.selected_model(core.load_settings()),
        'instructions': core.INSTRUCTIONS + '\n' + app_developer_instructions(),
        'input': [{'type': 'message', 'role': 'user',
                   'content': [{'type': 'input_text', 'text': turn_text}]}],
        'tools': request_tools(),
        'max_output_tokens': 1024,
        'stream': True,
    }
    for index, query in enumerate(search_queries):
        _append_mcp_result(body, 'skill_search', {'query': query, 'limit': 3},
                           memory.search(query, limit=3), f'skill_search_{index}')
    for index, name in enumerate(read_names):
        offset = 0
        while True:
            result = memory.read(name, offset=offset, max_chars=16000)
            call_id = f'skill_read_{index}_{offset}'
            arguments = json.dumps({'input': json.dumps({'name': name, 'offset': offset,
                                                          'max_chars': 16000}, ensure_ascii=False)},
                                   ensure_ascii=False)
            body['input'].append({'type': 'function_call', 'call_id': call_id,
                                  'name': 'local_history__skill_read', 'arguments': arguments})
            body['input'].append({'type': 'function_call_output', 'call_id': call_id,
                                  'output': json.dumps(result, ensure_ascii=False)})
            if result['next_offset'] is None:
                break
            offset = result['next_offset']
    original_reasoning = gateway.reasoning_budget
    original_catalog_root = tool_directory.ROOT
    try:
        gateway.reasoning_budget = lambda settings=None: 1024
        tool_directory.ROOT = OUT / 'tool-catalogs'
        body = gateway.normalize(body)
        original_tools=list(body['tools'])
        directory_state=gateway.register_tools(body,filter_schemas=filter_mcp_schemas)
        if mcp_search_queries:
            for index,query in enumerate(mcp_search_queries):
                result=tool_directory.search(directory_state['request_key'],query,limit=4)
                call_id=f'tool_catalog_search_{index}'
                call_name=next(tool['name'] for tool in original_tools
                               if tool['name'].endswith('__tool_catalog_search'))
                body['input'].append({'type':'function_call','call_id':call_id,
                    'name':call_name,'arguments':json.dumps({'request_key':directory_state['request_key'],
                        'query':query,'limit':6},ensure_ascii=False)})
                body['input'].append({'type':'function_call_output','call_id':call_id,
                    'output':json.dumps(result,ensure_ascii=False)})
            body['tools']=original_tools
            gateway.register_tools(body,filter_schemas=filter_mcp_schemas)
        gateway.append_runtime_state(body, BATCH_GUIDANCE)
        return body
    finally:
        gateway.reasoning_budget = original_reasoning
        tool_directory.ROOT = original_catalog_root


def resident_request_body(include_skill_index=True, include_tools=True, filter_mcp_schemas=True):
    # Mirror a real turn: the chat template requires a user query, so the
    # resident request is the same skeleton as actual_request_body with no
    # Skill context and a minimal probe prompt.
    context = memory_instructions('00000000-0000-4000-8000-000000000001') + core.mcp_skill_index('')
    if include_skill_index:
        context += '\n' + core.skill_reference_context('', root=ROOT,
                                                       bundle_root=DEPLOY_SKILLS)
    turn_text = core.compose_turn_input(' ', context)
    body = {
        'model': core.selected_model(core.load_settings()),
        'instructions': core.INSTRUCTIONS + '\n' + app_developer_instructions(),
        'input': [{'type': 'message', 'role': 'user',
                   'content': [{'type': 'input_text', 'text': turn_text}]}],
        'tools': request_tools() if include_tools else [],
        'max_output_tokens': 1024,
        'stream': True,
    }
    original_reasoning=gateway.reasoning_budget
    original_catalog_root=tool_directory.ROOT
    try:
        gateway.reasoning_budget=lambda settings=None:1024
        tool_directory.ROOT = OUT / 'tool-catalogs'
        body = gateway.normalize(body)
        if body['tools']:
            gateway.register_tools(body,filter_schemas=filter_mcp_schemas)
            gateway.append_runtime_state(body, BATCH_GUIDANCE)
        return body
    finally:
        gateway.reasoning_budget=original_reasoning
        tool_directory.ROOT=original_catalog_root


def skill_file_inventory():
    # Use effective precedence resolution so nested on-demand Skills are included.
    memory = SkillMemory(ROOT, bundle_root=DEPLOY_SKILLS)
    rows = []
    for entry in memory.index():
        name=entry['name']
        base=Path(entry['path']).parent
        for path in sorted(base.rglob('*')):
            if path.is_file():
                rows.append({'skill': name, 'relative_path': str(path.relative_to(base)),
                             'path': str(path), 'bytes': path.stat().st_size,
                             'source': 'user' if path.is_relative_to(ROOT/'codex-home'/'skills') else 'bundled'})
    return rows


def previous_candidate_context(prompt, memory):
    """Reproduce the pre-change per-turn top-three Skill metadata injection."""
    matches=memory.search(prompt,limit=3)['skills']
    matches=[row for row in matches if int(row.get('score',0))>=4][:3]
    if not matches:return ''
    lines=['本轮 Skill 候选元数据（仅名称/用途/路径；正文尚未加载）：']
    for row in matches:
        description=' '.join(str(row.get('description','')).split())[:240]
        lines.append(f"- {row['name']}: {description} | {row['path']}")
    lines.append('仅当候选流程确实适用时调用 skill_read；默认读取 1–3 个，更多时先说明原因。')
    return '\n'.join(lines)+'\n'


def request_token_scenarios():
    memory = SkillMemory(ROOT, bundle_root=DEPLOY_SKILLS)
    tools = request_tools()
    tool_namespaces = [namespace['name'] for namespace in tools]
    tool_count = sum(len(namespace.get('tools', [])) for namespace in tools)
    if len(tools) < 2 or tool_count < 150:
        raise AssertionError(
            f'expected the full live MCP tool set, got {tool_count} tools in {len(tools)} namespaces')
    configured_names=set(tomllib.loads((ROOT/'codex-home'/'config.toml').read_text(
        encoding='utf-8')).get('mcp_servers',{}))
    schema_inventory=json.loads(MCP_TOOLS_JSON.read_text(encoding='utf-8'))
    if configured_names != set(schema_inventory) or any(row.get('status')!='ok'
            for row in schema_inventory.values()):
        raise AssertionError('Captured tools/list schemas no longer match configured MCP server names/statuses.')
    scenarios = [
        {'label':'ordinary','prompt':'What is 7 multiplied by 9? Give only the result.',
         'search_queries':[],'read_names':[]},
        {'label':'one_skill',
         'prompt':'On my Android test phone, check an APK package name, target SDK and ABI before installation.',
         'search_queries':['On my Android test phone, check an APK package name, target SDK and ABI before installation.'],
         'mcp_search_queries':['Android APK package name target SDK ABI inspect metadata'],
         'read_names':['android-package-management']},
        {'label':'multiple_skills',
         'prompt':'On Android, use a fresh screenshot and CPU OCR to locate a visible button; inspect the APK in IDA Pro.',
         'search_queries':['fresh Android screenshot CPU OCR visible button coordinate',
                           'IDA Pro inspect binary functions MCP',
                           ],
         'mcp_search_queries':['Android screenshot OCR locate visible button coordinate',
                              'IDA Pro inspect executable functions pseudocode',
                              ],
         'read_names':['snapshot-bound-ui-control','r0idamcp-ida-local','android-demo-ui']},
    ]
    resident_body = resident_request_body()
    empty_resident_body = resident_request_body(include_skill_index=False,include_tools=True)
    no_tools_body = resident_request_body(include_skill_index=False,include_tools=False)
    resident_tokens = gateway.count_prompt_tokens(resident_body, '/v1/responses')
    empty_resident_tokens = gateway.count_prompt_tokens(empty_resident_body, '/v1/responses')
    no_tools_tokens = gateway.count_prompt_tokens(no_tools_body, '/v1/responses')
    unfiltered_resident_body=resident_request_body(filter_mcp_schemas=False)
    unfiltered_resident_tokens=gateway.count_prompt_tokens(unfiltered_resident_body,'/v1/responses')
    if (core.WORK_CONTEXT,core.WORK_COMPACT)!=(95000,91000):
        raise AssertionError('Active source constants do not set 95,000 / 91,000.')
    results = []
    actual_outbound = []
    for scenario in scenarios:
        label=scenario['label'];prompt=scenario['prompt']
        queries=scenario['search_queries'];chosen=scenario['read_names']
        initial_body = actual_request_body(prompt, memory=memory)
        initial_tokens = gateway.count_prompt_tokens(initial_body, '/v1/responses')
        old_context=previous_candidate_context(prompt,memory)
        previous_body=actual_request_body(prompt,memory=memory,include_resident_index=False,
                                          extra_context=old_context,filter_mcp_schemas=True)
        previous_initial_tokens=gateway.count_prompt_tokens(previous_body,'/v1/responses')
        metadata_body = actual_request_body(prompt,search_queries=queries,
            mcp_search_queries=scenario.get('mcp_search_queries',()),memory=memory)
        metadata_tokens = gateway.count_prompt_tokens(metadata_body, '/v1/responses')
        full_body = actual_request_body(prompt,search_queries=queries,read_names=chosen,
            mcp_search_queries=scenario.get('mcp_search_queries',()),memory=memory)
        full_tokens = gateway.count_prompt_tokens(full_body, '/v1/responses')
        unfiltered_body=actual_request_body(prompt,search_queries=queries,read_names=chosen,
            mcp_search_queries=scenario.get('mcp_search_queries',()),memory=memory,
            filter_mcp_schemas=False)
        unfiltered_tokens=gateway.count_prompt_tokens(unfiltered_body,'/v1/responses')
        outbound = gateway.encode_upstream_body(full_body)
        decoded = json.loads(outbound)
        usage = gateway.skill_read_request_stats(decoded)
        actual_names={row['name'] for row in usage['skill_reads_this_turn']}
        if actual_names != set(chosen):
            raise AssertionError(f'{label}: final request loaded {sorted(actual_names)}, expected {sorted(chosen)}')
        if label=='ordinary' and (queries or chosen or usage['skill_reads_this_turn']):
            raise AssertionError('Ordinary question loaded or searched an unrelated Skill.')
        if chosen and not all(name in outbound.decode('utf-8') for name in chosen):
            raise AssertionError(f'{label}: selected Skill output missing from final upstream body')
        results.append({
            'scenario': label,
            'prompt': prompt,
            'selected_skills': chosen,
            'fixed_prompt_and_tools_tokens': resident_tokens,
            'local_toolchain_metadata_tokens': resident_tokens-empty_resident_tokens,
            'previous_candidate_metadata_tokens':previous_initial_tokens-
                gateway.count_prompt_tokens(actual_request_body(prompt,memory=memory,
                    include_resident_index=False),'/v1/responses'),
            'initial_request_tokens_before_skill_search': initial_tokens,
            'previous_initial_request_tokens_before_skill_search':previous_initial_tokens,
            'initial_request_tokens_saved':previous_initial_tokens-initial_tokens,
            'skill_and_tool_search_output_incremental_tokens': metadata_tokens-initial_tokens,
            'skill_body_incremental_tokens': full_tokens-metadata_tokens,
            'mcp_schema_index_savings_tokens':unfiltered_tokens-full_tokens,
            'tool_schema_count_in_final_request':len(full_body.get('tools',[])),
            'selected_mcp_tools':[tool['name'] for tool in full_body.get('tools',[])
                                  if not tool_directory._always_available(tool)],
            'total_input_tokens': full_tokens,
            'skill_read_output_tokens': usage['skill_output_tokens_this_turn'],
            'skill_reads_this_turn': usage['skill_reads_this_turn'],
            'final_request_bytes': len(outbound),
            'final_request_sha256': __import__('hashlib').sha256(outbound).hexdigest(),
            'body_contains_selected_skill_results': bool(chosen) and all(name in outbound.decode('utf-8') for name in chosen),
        })
        actual_outbound.append(decoded)
    # A new user message makes prior Skill results historical, but they remain in this thread's input.
    old_body = actual_outbound[1]
    old_call = next(item for item in old_body['input'] if item.get('type') == 'function_call' and
                    item.get('name','').endswith('__skill_read'))
    old_output = next(item for item in old_body['input'] if item.get('type') == 'function_call_output' and
                      item.get('call_id') == old_call.get('call_id'))
    switched = dict(old_body)
    switched['input'] = [old_body['input'][0], old_call, old_output,
                         {'type': 'message', 'role': 'user', 'content': [
                             {'type': 'input_text', 'text': 'What is the current weather?'}]}]
    history_stats = gateway.skill_read_request_stats(switched)
    if history_stats['skill_reads_this_turn'] or not history_stats['skill_reads_earlier_history']:
        raise AssertionError('Prior Skill output was not distinguished from the new turn.')
    config_test=generated_compaction_config_test()
    return {'tokenizer_backend': core.selected_backend(),
            'tool_namespaces': tool_namespaces,
            'tool_count': tool_count,
            'mcp_schema_snapshot':{'path':str(MCP_TOOLS_JSON),
                'last_modified':__import__('datetime').datetime.fromtimestamp(
                    MCP_TOOLS_JSON.stat().st_mtime).isoformat(),
                'configured_names_match':True,'server_count':len(schema_inventory)},
            'token_method': 'gateway.count_prompt_tokens -> /apply-template -> model /tokenize',
            'fixed_prompt_and_tools_tokens': resident_tokens,
            'base_instructions_without_tools_or_skill_index_tokens':no_tools_tokens,
            'mcp_schemas_and_directory_incremental_tokens':empty_resident_tokens-no_tools_tokens,
            'unfiltered_fixed_prompt_and_tool_schemas_tokens':unfiltered_resident_tokens,
            'tool_schema_index_savings_tokens':unfiltered_resident_tokens-resident_tokens,
            'initial_tool_schema_count':len(resident_body.get('tools',[])),
            'local_toolchain_metadata_tokens':resident_tokens-empty_resident_tokens,
            'generated_compaction_config':config_test,
            'scenarios': results,
            'task_switch_history_check': {
                'current_turn_skill_reads': history_stats['skill_reads_this_turn'],
                'earlier_history_skill_reads': history_stats['skill_reads_earlier_history'],
                'older_skill_output_remains_in_model_request': any(
                    item.get('type') == 'function_call_output' for item in switched['input']),
            }}


def generated_compaction_config_test():
    with tempfile.TemporaryDirectory(prefix='compact-config-',dir=OUT) as directory:
        root=Path(directory)
        settings={'model':core.HUIHUI_IQ3S_MODEL,'api_key':'test-only','context':96256,
                  'model_contexts':{core.HUIHUI_IQ3S_MODEL:96256},'history_mode':'memory',
                  'work_context':95000,'backend':'vulkan','project':str(root/'project')}
        with patch.object(core,'ROOT',root), patch('skill_memory.install_bundled_skills'):
            prepared=core.prepare(settings)
        config=tomllib.loads((root/'codex-home'/'config.toml').read_text(encoding='utf-8'))
        profile=tomllib.loads((root/'codex-home'/'huihui-iq3s-local.config.toml').read_text(encoding='utf-8'))
        catalog=json.loads((root/'codex-model-catalog.json').read_text(encoding='utf-8'))
        model=next(item for item in catalog['models'] if item['slug']==core.HUIHUI_IQ3S_MODEL)
        values={'settings_compact':prepared['compact'],
                'config_context':config['model_context_window'],
                'config_compact':config['model_auto_compact_token_limit'],
                'profile_compact':profile['model_auto_compact_token_limit'],
                'model_catalog_compact':model['auto_compact_token_limit'],
                'scope':config.get('model_auto_compact_token_limit_scope')}
        if (values['config_context'],values['config_compact'],values['profile_compact'],
                values['model_catalog_compact'])!=(95000,91000,91000,91000):
            raise AssertionError('Generated profile/config/catalog do not all carry the 95,000 / 91,000 limits: '+str(values))
        legacy={**settings,'work_context':96000,'work_context_migration_version':81}
        with patch.object(core,'ROOT',root/'legacy'), patch('skill_memory.install_bundled_skills'):
            migrated=core.prepare(legacy)
        if migrated['work_context']!=95000 or migrated['compact']!=91000:
            raise AssertionError('The v81 96k default was not migrated to the requested 95k / 91k settings.')
        values['legacy_96k_migrates_to_95k']=migrated['work_context']==95000
        return values


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LazyIndexTests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ToolSchemaIndexTests))
    test_result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not test_result.wasSuccessful():
        raise SystemExit(1)
    inventory = skill_file_inventory()
    token_results = request_token_scenarios()
    report = {
        'source': str(SOURCE),
        'runtime_user_skill_root': str(ROOT / 'codex-home' / 'skills'),
        'runtime_bundled_skill_root': str(DEPLOY_SKILLS),
        'skill_count': len({row['skill'] for row in inventory}),
        'file_count': len(inventory),
        'total_bytes': sum(row['bytes'] for row in inventory),
        'inventory': inventory,
        'unit_tests': {'run': test_result.testsRun, 'failures': len(test_result.failures),
                       'errors': len(test_result.errors)},
        'request_token_tests': token_results,
    }
    path = OUT / 'verification.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (OUT / 'skill-file-inventory.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        import csv
        writer = csv.DictWriter(stream, fieldnames=['skill','relative_path','path','bytes','source'])
        writer.writeheader(); writer.writerows(inventory)
    print(json.dumps({'report':str(path),'inventory_csv':str(OUT/'skill-file-inventory.csv'),
                      'skill_count':report['skill_count'],'file_count':report['file_count'],
                      'total_bytes':report['total_bytes'],'unit_tests':report['unit_tests'],
                      'request_token_tests':token_results},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
