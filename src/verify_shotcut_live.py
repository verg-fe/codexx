"""End-to-end calls to the configured Shotcut CPU MCP using generated media."""
from __future__ import annotations
import asyncio, json, os, subprocess, time
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PYTHON=Path(r'G:\LocalCodex\tools\photoslop-mcp-venv\Scripts\python.exe')
ADAPTER=Path(r'G:\LocalCodex\tools\shotcut_huihui_mcp.py')
FFMPEG=Path(r'G:\LocalCodex\tools\shotcut\Shotcut\ffmpeg.exe')
ROOT=Path(r'G:\LocalCodex\video-jobs')

async def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    folder=ROOT/('mcp-acceptance-'+time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir()
    source=folder/'source.mp4'
    run=subprocess.run([str(FFMPEG),'-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i',
        'testsrc=size=160x120:rate=10','-f','lavfi','-i','sine=frequency=880:duration=3','-t','3',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],
        capture_output=True,timeout=90)
    if run.returncode or not source.is_file() or source.stat().st_size==0:
        raise RuntimeError(run.stderr.decode('utf-8','replace'))
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_OPENGL='software',QT_QUICK_BACKEND='software',
         PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    evidence={'test_media':str(source),'size':source.stat().st_size,'cpu_source_generation':True}
    params=StdioServerParameters(command=str(PYTHON),args=[str(ADAPTER),'--output-root',str(ROOT)],env=env)
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            await client.initialize()
            evidence['tools']=[tool.name for tool in (await client.list_tools()).tools]
            async def call(name,args,expected_error=False):
                try:
                    result=await client.call_tool(name,args)
                except Exception as exc:
                    if expected_error:
                        return {'rejected':True,'error':str(exc)}
                    raise
                failed=bool(getattr(result,'is_error',getattr(result,'isError',False)))
                body=getattr(result,'structured_content',getattr(result,'structuredContent',None))
                if failed and expected_error:
                    return {'rejected':True,'error':body or [item.text for item in result.content if getattr(item,'text',None)]}
                if failed!=expected_error: raise AssertionError((name,failed,body))
                if body:
                    return body
                texts=[item.text for item in result.content if getattr(item,'text',None)]
                if texts:
                    try: return json.loads(texts[0])
                    except (ValueError,TypeError): return texts
                return texts
            evidence['status']=await call('shotcut_status',{})
            evidence['source_info']=await call('shotcut_media_info',{'input':str(source)})
            name='mcp-cut-'+str(int(time.time()))+'.mp4'
            evidence['trim']=await call('shotcut_trim',{'input':str(source),'output_name':name,
                'start_seconds':0.5,'end_seconds':2.5})
            evidence['invalid_interval']=await call('shotcut_trim',{'input':str(source),'output_name':'bad.mp4',
                'start_seconds':2,'end_seconds':1},True)
            evidence['outside_root']=await call('shotcut_trim',{'input':str(source),'output_name':'..\\escape.mp4',
                'start_seconds':0,'end_seconds':1},True)
            evidence['wrong_input']=await call('shotcut_media_info',{'input':str(folder/'missing.mp4')},True)
            evidence['overwrite']=await call('shotcut_trim',{'input':str(source),'output_name':name,
                'start_seconds':0,'end_seconds':1},True)
    output=Path(evidence['trim']['output'])
    if not output.is_file() or output.stat().st_size==0 or evidence['trim']['video_codec']!='h264':
        raise AssertionError('CPU MP4 export missing or invalid')
    evidence.update(completed=True,output_bytes=output.stat().st_size,output_exists=True,
        limitations='Short synthetic video verified actual MCP CPU export; longer footage, user GUI editing, cancellation and restart recovery remain pending.')
    target=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\mcp-acceptance\shotcut-live.json')
    target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))

if __name__=='__main__': asyncio.run(main())
