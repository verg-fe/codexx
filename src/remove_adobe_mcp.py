"""Remove the retired Photoshop/Premiere MCP code and move local panels to backup."""
from __future__ import annotations
import ast, json, os, re, shutil, time, tomllib
from pathlib import Path

root=Path(r'D:\LocalCodex')
backup=root/'backups'/('remove-adobe-mcp-'+time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
done={}

# Adobe functionality lived beside narration in one source module. Remove only
# Adobe-specific functions and routing branches; retain voice jobs unchanged.
p=Path('release54/creative_tools.py'); src=p.read_text(encoding='utf-8'); tree=ast.parse(src)
spans=[]
for node in ast.walk(tree):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in ('adobe_status','adobe_script'):
        spans.append((node.lineno,node.end_lineno))
for node in ast.walk(tree):
    if isinstance(node,ast.If) and isinstance(node.test,ast.Compare):
        seg=ast.get_source_segment(src,node.test) or ''
        if "service in ('photoshop', 'premiere')" in seg:
            spans.append((node.lineno,node.end_lineno))
lines=src.splitlines(keepends=True)
for start,end in sorted(set(spans),reverse=True):
    del lines[start-1:end]
updated=''.join(lines)
ast.parse(updated)
shutil.copy2(p,backup/'creative_tools.py'); p.write_text(updated,encoding='utf-8')
done['source_media_router']=str(p)

# Remove Adobe MCP registrations from all profiles; Shotcut is registered only
# for Huihui profiles. Validate the resulting TOML before changing each file.
for p in (root/'codex-home').glob('*.toml'):
    old=p.read_text(encoding='utf-8-sig')
    parts=re.split(r'(?=^\[)',old,flags=re.M)
    new=''.join(x for x in parts if not re.match(r'\[mcp_servers\.(?:premiere|photoshop)(?:\.|\])',x))
    tomllib.loads(new)
    if old!=new:
        shutil.copy2(p,backup/p.name); p.write_text(new,encoding='utf-8'); done.setdefault('configs',[]).append(str(p))

# Relocate our extension source and installed Adobe CEP panel out of discovery paths.
for src,destname in ((Path('release54/adobe-panel'),'adobe-panel-source'),
    (Path.home()/'AppData/Roaming/Adobe/CEP/extensions/local.mycodex.bridge54','adobe-panel-installed')):
    if src.exists():
        dest=backup/destname
        shutil.move(str(src),str(dest)); done[destname]=str(dest)

# Remove stale App Paths only when the registered executable is already absent.
import winreg
removed=[]
for name in ('Adobe Premiere Pro.exe','Photoshop.exe'):
    keypath='Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\'+name
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,keypath,0,winreg.KEY_QUERY_VALUE) as key:
            target=winreg.QueryValueEx(key,'')[0]
        if not Path(target).is_file():
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER,keypath); removed.append({'name':name,'stale_target':target})
    except OSError: pass
done['stale_app_paths_removed']=removed

status={'completed':True,'details':done,'backup':str(backup),'photoslop_kept_as_separate_image_mcp':True,
        'shotcut_mcp':'D:\\LocalCodex\\tools\\shotcut_huihui_mcp.py'}
(root/'staging/release54-verification/adobe-mcp-removal.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(status,ensure_ascii=False))
