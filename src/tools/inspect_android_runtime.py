"""Read-only Android diagnostics without nesting shell pipelines in PowerShell."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--adb',required=True);parser.add_argument('--device',required=True)
    parser.add_argument('--package',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--server',default='/data/local/tmp/frida-server-17.22.2')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.]+',args.package):raise ValueError('Invalid package name')
    if not args.server.startswith('/data/local/tmp/') or not re.fullmatch(r'/[A-Za-z0-9_./-]+',args.server):raise ValueError('Invalid server path')
    def run(*command):
        result=subprocess.run([args.adb,'-s',args.device,*command],capture_output=True,
            encoding='utf-8',errors='replace',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        text=(result.stdout+'\n'+result.stderr).strip()
        if result.returncode or re.search(r'Permission denied|not found|not permitted|unauthorized',text,re.I):
            raise RuntimeError('ADB diagnostic failed: '+text[:500])
        return result.stdout.strip()
    report={'package':args.package,'read_only':True,'stages':{},'errors':[]}
    def stage(name,callback):
        try:report['stages'][name]=callback()
        except (OSError,RuntimeError,subprocess.TimeoutExpired,ValueError) as error:report['errors'].append({'stage':name,'message':str(error)})
    def root_run(*command):
        return run('shell','su -c '+shlex.quote(shlex.join(command)))
    stage('device_abi',lambda:run('shell','getprop','ro.product.cpu.abilist'))
    stage('pid',lambda:run('shell','pidof',args.package))
    pid=(report['stages'].get('pid') or '').split()
    if pid and pid[0].isdigit():
        stage('loaded_libraries',lambda:sorted({line.split()[-1] for line in root_run('cat','/proc/'+pid[0]+'/maps').splitlines()
            if any(name in line for name in ('libart','libandroid_runtime','/libc.so','libbase'))})[:20])
    else:report['errors'].append({'stage':'loaded_libraries','message':'App is not running; no maps were read.'})
    stage('server_elf_header',lambda:root_run('od','-An','-tx1','-N20',args.server))
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
