"""Prepare only shared-runtime template functions; retain the CLI's own adapter and archive behavior."""
import ast
import hashlib
import json
from pathlib import Path
import shutil


def functions(text):
    return {node.name:(node.lineno-1,node.end_lineno) for node in ast.parse(text).body if isinstance(node,ast.FunctionDef)}


def main():
    source=Path(__file__).parent
    original=Path(r'C:\Users\18213\Desktop\codex-jack-cli\vendor\core.py')
    stage=Path(r'D:\LocalCodex\staging\native-thinking-25-cli-ready')
    stage.mkdir(parents=True,exist_ok=True)
    old=original.read_text(encoding='utf-8');new=(source/'core.py').read_text(encoding='utf-8')
    old_nodes=functions(old);new_nodes=functions(new);lines=old.splitlines(keepends=True);new_lines=new.splitlines(keepends=True)
    replacements=[]
    for name in ('runtime_matches_settings','model_args','_start_model'):
        a,b=old_nodes[name];c,d=new_nodes[name]
        replacements.append((a,b,''.join(new_lines[c:d])))
    a,b=new_nodes['chat_template_state']
    helper=''.join(new_lines[a:b])+'\n\n'
    for a,b,body in sorted(replacements,reverse=True):
        lines[a:b]=[body]
    result=''.join(lines)
    if 'def chat_template_state(' not in result:
        result=result.replace('def runtime_matches_settings(',helper+'def runtime_matches_settings(',1)
    compile(result,str(stage/'core.py'),'exec')
    (stage/'core.py').write_text(result,encoding='utf-8',newline='')
    for name in ('model_templates.py','gguf_info.py'):
        shutil.copy2(source/name,stage/name)
    manifest={'files':[{ 'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in stage.glob('*.py')],
              'legacy_cli_adapter_version_preserved':"ADAPTER_VERSION = '2026-10-03-history-workspace-22'" in result or
                  [line for line in old.splitlines() if line.startswith('ADAPTER_VERSION')]==[line for line in result.splitlines() if line.startswith('ADAPTER_VERSION')]}
    (stage/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'staged_cli_helpers':len(manifest['files']),'version_preserved':manifest['legacy_cli_adapter_version_preserved']}))


if __name__=='__main__':main()
