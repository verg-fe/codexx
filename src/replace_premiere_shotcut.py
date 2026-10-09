"""Remove retired Premiere registrations while preserving documents and backups."""
import json, re, shutil, time, tomllib
from pathlib import Path

root=Path(r'D:\LocalCodex')
backup=root/'backups'/('replace-premiere-shotcut-'+time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
changed=[]
for p in (root/'codex-home').glob('*.toml'):
    text=p.read_text(encoding='utf-8-sig')
    parts=re.split(r'(?=^\[)',text,flags=re.M)
    updated=''.join(part for part in parts if not re.match(r'\[mcp_servers\.premiere(?:\.|\])',part))
    tomllib.loads(updated)
    if updated!=text:
        shutil.copy2(p,backup/p.name)
        p.write_text(updated,encoding='utf-8')
        changed.append(str(p))
for p in [Path('release54/adobe-panel/CSXS/manifest.xml'),Path(r'C:\Users\18213\AppData\Roaming\Adobe\CEP\extensions\local.mycodex.bridge54\CSXS\manifest.xml')]:
    if p.is_file():
        shutil.copy2(p,backup/('manifest-source.xml' if str(p).startswith('release54') else 'manifest-installed.xml'))
        p.write_text(re.sub(r'<Host Name="PPRO"[^>]*/>','',p.read_text(encoding='utf-8')),encoding='utf-8')
core=Path('release54/core.py')
text=core.read_text(encoding='utf-8')
shutil.copy2(core,backup/'core.py')
text=text.replace("'photoshop','premiere','voice'","'photoshop','voice'").replace("('photoshop', 'premiere')","('photoshop',)")
text=text.replace('Media tools: Photoshop uses photoshop_status/open/document_info/execute_script; Premiere needs a connected\nMyCodex Bridge panel before premiere_* calls. Check status first.', 'Media tools: Photoshop uses photoshop_status/open/document_info/execute_script. Premiere was retired;\nuse Shotcut for video editing, with CPU processing and hardware encoding disabled. Check status first.')
core.write_text(text,encoding='utf-8')
record={'backup':str(backup),'configs_removed':changed,'photoshop_bridge_preserved':True,'user_documents_preserved':True}
(root/'staging/release54-verification/premiere-retirement.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False))
