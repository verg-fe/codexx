"""Keep old and newly migrated native turns intact before changing the shared template."""
from pathlib import Path
from verify_kv20 import guard as old_guard, native_state


def guard():
    status=old_guard()
    if not status['safe']:
        return status
    project=Path(r'C:\my_projects\my_codex')
    for relative in ('data/codex-home/sessions','codex-home/sessions','.codex/sessions'):
        home=project/relative
        if not home.exists():
            continue
        for path in sorted(home.rglob('*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)[:6]:
            latest,terminal,_=native_state(path)
            if latest and not terminal:
                return {'safe':False,'reason':'Migrated project has an active native turn','file':str(path)}
    return status
