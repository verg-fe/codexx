"""Recoverable local conversation deletion; native rollouts are archived separately."""
import json
from pathlib import Path
import re
import time


class ConversationStore:
    def __init__(self, root):
        self.root=Path(root)/'conversations'
        self.deleted=self.root/'deleted'
        self.index=self.root/'index.json'
        self.trash_index=self.deleted/'index.json'

    @staticmethod
    def read(path):
        if not path.exists():return []
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,list):raise ValueError('会话索引格式不正确，未修改记录。')
        return data

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)

    def path_for(self, thread_id, deleted=False):
        if not re.fullmatch(r'[0-9a-fA-F-]{36}',thread_id):
            raise ValueError('会话编号无效。')
        return (self.deleted if deleted else self.root)/(thread_id+'.txt')

    def sessions(self):
        return self.read(self.index)

    def deleted_sessions(self):
        return self.read(self.trash_index)

    def delete(self, thread_id):
        sessions=self.sessions()
        position=next((i for i,s in enumerate(sessions) if s['id']==thread_id),None)
        if position is None:
            raise ValueError('会话已经不在列表中。')
        record={'session':sessions[position],'position':position,'deleted_at':time.time()}
        source,destination=self.path_for(thread_id),self.path_for(thread_id,True)
        self.deleted.mkdir(parents=True,exist_ok=True)
        records=self.deleted_sessions()
        if destination.exists() or any(r['session']['id']==thread_id for r in records):
            raise ValueError('删除备份已存在，未覆盖已有记录。')
        moved=False
        try:
            if source.exists():source.replace(destination);moved=True
            self.write(self.trash_index,[*records,record])
            self.write(self.index,[s for s in sessions if s['id']!=thread_id])
        except Exception:
            if moved:destination.replace(source)
            self.write(self.trash_index,records)
            raise
        return record

    def restore(self, thread_id):
        records=self.deleted_sessions()
        record=next((r for r in records if r['session']['id']==thread_id),None)
        if record is None:raise ValueError('找不到已删除会话。')
        sessions=self.sessions()
        if any(s['id']==thread_id for s in sessions):raise ValueError('会话已恢复。')
        source,destination=self.path_for(thread_id,True),self.path_for(thread_id)
        if destination.exists():raise ValueError('当前会话文件已存在，未覆盖。')
        restored=list(sessions)
        restored.insert(min(record['position'],len(restored)),record['session'])
        moved=False
        try:
            if source.exists():source.replace(destination);moved=True
            self.write(self.index,restored)
            self.write(self.trash_index,[r for r in records if r['session']['id']!=thread_id])
        except Exception:
            if moved:destination.replace(source)
            self.write(self.index,sessions)
            raise
        return record['session']
