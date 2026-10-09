"""One fresh directory per new chat, with metadata outside the empty folder."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import uuid

DEFAULT_WORKSPACE_ROOT = r'G:\LocalCodex\CodexSessions'

class SessionWorkspaces:
    def __init__(self,root):
        self.metadata=Path(root)/'session-workspaces'
        self.metadata.mkdir(parents=True,exist_ok=True)

    def create(self,settings):
        parent=Path(settings.get('session_workspace_root') or DEFAULT_WORKSPACE_ROOT).expanduser().resolve()
        parent.mkdir(parents=True,exist_ok=True)
        identifier=uuid.uuid4().hex
        stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d_%H-%M-%S')
        folder=parent/(stamp+'_'+identifier[:8])
        folder.mkdir(exist_ok=False)
        value=dict(id=identifier,workspace=str(folder),project=str(folder),thread_id=None)
        self.save(value)
        return value

    def save(self,value):
        identifier=value['id']
        if not identifier.isalnum():raise ValueError('Invalid workspace identifier')
        path=self.metadata/(identifier+'.json');temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

    def instructions(self,value):
        if not value:return ''
        return ('\nApplication session directory: '+value['workspace']+'. '
                'Keep newly generated helpers, downloads and deliverables in this directory. '
                'The user-selected project directory is '+value['project']+'. '
                'Modify that project when requested; do not silently reuse files from other sessions.\n')
