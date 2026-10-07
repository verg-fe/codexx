"""Check the packaged widgets in a private populated project, preserving the user's current project."""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
import core

def main(exe=None,report_name='verification-build23.json',xml_disabled=False,directive_mode=None):
    saved=(core.ROOT/'settings.json').read_bytes()
    with tempfile.TemporaryDirectory(prefix='draft-ui23-',dir=core.ROOT/'verification-project') as folder:
        root=Path(folder);project=root/'project';project.mkdir()
        (project/'probe.txt').write_text('Private UI fixture; no model call.',encoding='utf-8')
        settings=core.load_settings();settings['project']=str(project)
        if xml_disabled:settings.update(jack_xml_enabled=False,directive_mode='native')
        if directive_mode:settings.update(directive_mode=directive_mode,jack_xml_enabled=directive_mode=='legacy')
        if directive_mode=='custom':settings.update(directive_custom_tag='my_preferences',directive_custom_text='测试自定义内容：用中文给出真实结果。')
        (root/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
        env={**os.environ,'LOCAL_CODEX_ROOT':str(root)}
        exe=Path(exe) if exe else core.ROOT/'staging/draft-guard-23-final/MyCodex/MyCodex.exe'
        result=subprocess.run([str(exe),'--verify-draft-guard'],env=env,creationflags=core.NO_WINDOW,timeout=30)
        report=json.loads((root/'verification-build23.json').read_text(encoding='utf-8'))
        report['private_populated_project']=True
        report['real_user_settings_unchanged']=saved==(core.ROOT/'settings.json').read_bytes()
        report['ok']=report['ok'] and report['real_user_settings_unchanged'] and result.returncode==0
        (core.ROOT/report_name).write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
        assert report['ok']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe');parser.add_argument('--report',default='verification-build23.json')
    parser.add_argument('--xml-disabled',action='store_true')
    parser.add_argument('--directive-mode',choices=('native','angry','desperate','obedient','open_xml','custom','legacy'))
    args=parser.parse_args();main(args.exe,args.report,args.xml_disabled,args.directive_mode)
