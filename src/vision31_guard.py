"""Respect all live native turns and the exact migration cancelled before v29."""
import json
from unittest.mock import patch
import core
import profiles26_guard

_original_cancellation = profiles26_guard.cancellation_covers


def cancellation_covers(path, turn):
    if _original_cancellation(path, turn):
        return True
    try:
        receipt=json.loads((core.ROOT/'cancelled-upgrade-moe32.json').read_text(encoding='utf-8'))
        if (receipt.get('authorized_by_user') is True and receipt.get('model_stopped') is True
                and receipt.get('thread_id') in path.name and receipt.get('turn_id')==turn
                and path.stat().st_mtime_ns==receipt.get('native_file_mtime_ns')
                and not profiles26_guard.process_alive(receipt['engine_pid'])
                and not profiles26_guard.process_alive(receipt['gui_pid'])):
            return True
    except (OSError,ValueError,KeyError):pass
    try:
        receipt=json.loads((core.ROOT/'cancelled-migration-huihui29.json').read_text(encoding='utf-8'))
        evidence=json.loads((core.ROOT/'deployment-huihui29.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return False
    return (receipt.get('authorized_by_user') is True and receipt.get('engine_exited') is True
        and evidence.get('abandoned_migration_task_stopped') is True
        and receipt.get('thread_id') in path.name and receipt.get('turn_id')==turn
        and path.stat().st_mtime_ns==receipt.get('native_file_mtime_ns')
        and not profiles26_guard.process_alive(receipt['engine_pid']))


def guard():
    with patch.object(profiles26_guard,'cancellation_covers',cancellation_covers):
        return profiles26_guard.guard()


if __name__=='__main__':print(json.dumps(guard(),ensure_ascii=False))
