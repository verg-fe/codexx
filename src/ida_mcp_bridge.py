"""Stdio MCP bridge to the local IDA Python 3.8 plugin."""
import json,sys,urllib.request,os,subprocess,time
from pathlib import Path

IDA_HOME=Path(r'G:\IDA Pro v7.6.210427')
JOBS=Path(r'G:\LocalCodex\ida-jobs')
START_TOOL={'name':'start_ida','description':'Start the installed IDA Pro with bundled Python 3.8. Use after a connection-refused probe instead of asking the user to start IDA. target_path is optional for a blank IDA session; pass an existing absolute binary or saved database path when the task has a target. Checks existing instances to avoid duplicates. User data and temporary files stay on G:.','inputSchema':{'type':'object','properties':{'target_path':{'type':'string','description':'Optional absolute path to the binary or saved IDA database to analyze. Omit only when restoring MCP connectivity without a target.'}},'additionalProperties':False},'annotations':{'readOnlyHint':False,'destructiveHint':False,'openWorldHint':False}}

def local_call(opener,config,params,timeout=90):
    request=urllib.request.Request(config['url'],data=json.dumps(params).encode('utf-8'),headers={'Authorization':'Bearer '+config['token'],'Content-Type':'application/json'})
    with opener.open(request,timeout=timeout) as response:return json.load(response)

def start_ida(arguments,opener,config):
    target_value=arguments.get('target_path')
    target=Path(target_value) if target_value else None
    if target is not None:
        if not target.is_absolute() or not target.is_file():
            raise ValueError('target_path must be an existing absolute file path when provided.')
        target=target.resolve()
    # Never launch another instance over a live analysis session.
    try:
        state=local_call(opener,config,{'name':'get_project_metadata','arguments':{}},3)
    except (OSError,ValueError):state=None
    if state is not None:
        if 'error' in state:return {'error':'IDA is running but its database is not ready. Check the existing window; no duplicate was started.'}
        return {'status':'already_running','requested_target':str(target) if target else None,'current_project':state.get('result',state),'note':'Verify current_project matches your target before analysis. No second IDA was started.'}
    query="Get-CimInstance Win32_Process -Filter \"Name='ida64.exe'\" | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    check=subprocess.run(['powershell.exe','-NoProfile','-Command',query],capture_output=True,encoding='utf-8',errors='replace',timeout=15)
    if check.returncode:raise RuntimeError('Cannot verify existing IDA processes; no duplicate was started.')
    instances=json.loads(check.stdout.strip() or '[]')
    if isinstance(instances,dict):instances=[instances]
    if instances:return {'error':'An IDA instance already exists but its MCP is not responding. Check its startup dialog or Python/plugin log. No duplicate was started.','process_ids':[p['ProcessId'] for p in instances]}
    exe=IDA_HOME/'ida64.exe'
    if not exe.is_file() or not (IDA_HOME/'python38/python38.dll').is_file():raise FileNotFoundError('Installed IDA or bundled Python 3.8 is missing.')
    temp=JOBS/'tmp';temp.mkdir(parents=True,exist_ok=True)
    user=Path(r'G:\LocalCodex\ida-user');user.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    for key in ('PYTHONHOME','PYTHONPATH','PYTHONSTARTUP','PYTHONUSERBASE'):env.pop(key,None)
    env.update(PATH=str(IDA_HOME/'python38')+os.pathsep+env.get('PATH',''),PYTHONNOUSERSITE='1',IDAUSR=str(user),TEMP=str(temp),TMP=str(temp),QT_OPENGL='software',QT_QUICK_BACKEND='software')
    log=JOBS/('ida-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
    command=[str(exe),'-A','-L'+str(log)]
    if target is not None:command.append(str(target))
    process=subprocess.Popen(command,cwd=str(JOBS),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if process.poll() is not None:return {'error':'IDA exited during startup. Read the startup log.','exit_code':process.returncode,'log_path':str(log)}
        try:
            state=local_call(opener,config,{'name':'get_project_metadata','arguments':{}},2)
            if 'error' not in state:return {'status':'ready','pid':process.pid,'current_project':state.get('result',state),'log_path':str(log)}
        except (OSError,ValueError):pass
        time.sleep(.5)
    return {'status':'starting','pid':process.pid,'log_path':str(log),'note':'IDA is still loading. Check connection again before analyzing; do not launch another instance.'}

def _is_connection_refused(exc):
    pending=[exc]
    seen=set()
    while pending:
        current=pending.pop()
        if current is None or id(current) in seen:continue
        seen.add(id(current))
        if getattr(current,'winerror',None)==10061 or getattr(current,'errno',None) in (61,111,10061):return True
        pending.extend((getattr(current,'reason',None),getattr(current,'__cause__',None),getattr(current,'__context__',None)))
    return False

def call_probe_with_recovery(name,params,opener,config):
    try:
        return local_call(opener,config,params)
    except Exception as exc:
        if name not in ('check_connection','get_project_metadata') or not _is_connection_refused(exc):raise
        startup=start_ida({},opener,config)
        if startup.get('status') in ('ready','already_running'):
            try:
                return local_call(opener,config,params)
            except Exception as retry_exc:
                return {'result':{'error':'IDA Pro started or was already running, but its MCP endpoint still did not answer the read-only probe. Do not launch a duplicate instance.','automatic_start':startup,'probe_error':str(retry_exc)}}
        if startup.get('status')=='starting':
            deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                try:
                    return local_call(opener,config,params,timeout=2)
                except Exception as retry_exc:
                    if not _is_connection_refused(retry_exc):raise
                    time.sleep(.5)
            startup['note']='IDA Pro was started automatically; its MCP plugin is still not listening. Do not start another instance. Check the reported startup log/window before deciding on user action.'
            return {'result':startup}
        return {'result':startup}

def serve():
    root=Path(r'D:\LocalCodex\tools\ida-mcp')
    config=json.loads((root/'connection.json').read_text(encoding='utf-8'))
    tools=json.loads((root/'tools.json').read_text(encoding='utf-8'))
    tools=[tool for tool in tools if tool['name']!='start_ida']+[START_TOOL]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for line in sys.stdin.buffer:
        req=json.loads(line);method=req.get('method');params=req.get('params') or {}
        if 'id' not in req:continue
        if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'codexx-ida-local','version':'1.0'}}
        elif method in ('ping','resources/list','resources/templates/list'):result={} if method=='ping' else ({'resources':[]} if method=='resources/list' else {'resourceTemplates':[]})
        elif method=='tools/list':result={'tools':tools}
        elif method=='tools/call':
            try:
                tool_name=params.get('name')
                answer=({'result':start_ida(params.get('arguments',{}),opener,config)} if tool_name=='start_ida' else call_probe_with_recovery(tool_name,params,opener,config))
                if isinstance(answer.get('result'),dict) and 'error' in answer['result']:answer=answer['result']
                result={'content':[{'type':'text','text':json.dumps(answer.get('result',answer),ensure_ascii=False)}],'isError':'error' in answer}
            except Exception as exc:result={'content':[{'type':'text','text':'IDA MCP call failed: '+str(exc)+'. For connection-refused errors, check_connection/get_project_metadata automatically start IDA Pro and retry once. For a task target, call start_ida with its existing absolute path; for connectivity-only recovery, omit target_path. Do not ask the user to manually start IDA unless an existing instance is detected and its startup log/window requires attention.'}],'isError':True}
        else:
            reply={'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'Method not found'}}
            sys.stdout.buffer.write(json.dumps(reply).encode()+b'\n');sys.stdout.buffer.flush();continue
        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result},ensure_ascii=False).encode('utf-8')+b'\n');sys.stdout.buffer.flush()

if __name__=='__main__':serve()
