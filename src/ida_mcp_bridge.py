"""Stdio MCP bridge to the local IDA Python 3.8 plugin."""
import json,sys,urllib.request
from pathlib import Path

def serve():
    root=Path(r'D:\LocalCodex\tools\ida-mcp')
    config=json.loads((root/'connection.json').read_text(encoding='utf-8'))
    tools=json.loads((root/'tools.json').read_text(encoding='utf-8'))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for line in sys.stdin.buffer:
        req=json.loads(line);method=req.get('method');params=req.get('params') or {}
        if 'id' not in req:continue
        if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'codexx-ida-local','version':'1.0'}}
        elif method in ('ping','resources/list','resources/templates/list'):result={} if method=='ping' else ({'resources':[]} if method=='resources/list' else {'resourceTemplates':[]})
        elif method=='tools/list':result={'tools':tools}
        elif method=='tools/call':
            try:
                request=urllib.request.Request(config['url'],data=json.dumps(params).encode('utf-8'),headers={'Authorization':'Bearer '+config['token'],'Content-Type':'application/json'})
                with opener.open(request,timeout=90) as response:answer=json.load(response)
                result={'content':[{'type':'text','text':json.dumps(answer.get('result',answer),ensure_ascii=False)}],'isError':'error' in answer}
            except Exception as exc:result={'content':[{'type':'text','text':'IDA connection failed: '+str(exc)+'. Open IDA with the target database and check Codexx IDA MCP plugin.'}],'isError':True}
        else:
            reply={'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'Method not found'}}
            sys.stdout.buffer.write(json.dumps(reply).encode()+b'\n');sys.stdout.buffer.flush();continue
        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result},ensure_ascii=False).encode('utf-8')+b'\n');sys.stdout.buffer.flush()

if __name__=='__main__':serve()
