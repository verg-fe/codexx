"""Exercise the real Photoslop stdio server and inspect files it actually writes."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PYTHON = Path(r'G:\LocalCodex\tools\photoslop-mcp-venv\Scripts\python.exe')
ROOT = Path(r'G:\LocalCodex\image-jobs')
EVIDENCE = Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\mcp-acceptance\photoslop-live.json')
ADAPTER = Path(r'G:\LocalCodex\tools\photoslop_huihui_mcp.py')

async def main():
    folder = ROOT / ('acceptance-' + time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    source = Image.new('RGB', (64,48), (30,100,200))
    source.paste((240,60,40), (0,0,32,48))
    source.save(folder/'source.png')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_OPENGL='software',
               QT_QUICK_BACKEND='software', PYTHONUTF8='1')
    results = {'root':str(ROOT),'files':str(folder),'mode':'CPU headless; no GUI or AI model'}
    async with stdio_client(StdioServerParameters(command=str(PYTHON),
        args=[str(ADAPTER),'--root',str(ROOT)],env=env)) as (r,w):
        async with ClientSession(r,w) as session:
            await session.initialize()
            results['tools'] = [t.name for t in (await session.list_tools()).tools]
            async def call(label, name, args, expect_error=False):
                reply = await session.call_tool(name,args)
                is_error=getattr(reply,'is_error',getattr(reply,'isError',False))
                structured=getattr(reply,'structured_content',getattr(reply,'structuredContent',None))
                results[label]={'isError':is_error,'result':structured or [c.model_dump() for c in reply.content]}
                assert bool(is_error)==expect_error, (label,results[label])
            await call('catalog','list_operations',{})
            await call('inspect_input','document_info',{'input':str(folder/'source.png')})
            await call('edit_and_save_layers','edit_image',{'input':str(folder/'source.png'),
                'operations':[{'op':'resize','value':'32x24'},{'op':'gaussian-blur','value':'1'}],
                'output':str(folder/'edited.ora'),'info':True})
            await call('export_png','edit_image',{'input':str(folder/'edited.ora'),
                'output':str(folder/'edited.png'),'info':True,'operations':[]})
            await call('reopen_layers','document_info',{'input':str(folder/'edited.ora')})
            await call('missing_input','document_info',{'input':str(folder/'missing.png')},True)
            await call('invalid_operation','edit_image',{'new':'32x24','info':True,
                'operations':[{'op':'does-not-exist','value':''}]},True)
            await call('overwrite_refused','edit_image',{'new':'32x24','output':str(folder/'edited.png'),'operations':[]},True)
            await call('outside_root','document_info',{'input':r'C:\Windows\win.ini'},True)
            command = "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -match 'photoslop_huihui_mcp.py' -and $_.Name -eq 'python.exe'} | ForEach-Object {Get-Process -Id $_.ProcessId} | Select-Object Id,WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress"
            results['process_memory']=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',command],text=True))
    with Image.open(folder/'edited.png') as output:
        assert output.size==(32,24)
        assert output.convert('RGB').getpixel((2,12)) != output.convert('RGB').getpixel((29,12))
        results['actual_png']={'width':output.width,'height':output.height,'bytes':(folder/'edited.png').stat().st_size}
    results['completed']=True
    EVIDENCE.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in results.items() if k in ['tools','completed','actual_png','process_memory','files']},indent=2))

if __name__=='__main__': asyncio.run(main())
