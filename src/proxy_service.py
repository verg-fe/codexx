"""Private VLESS client for one Codex app-server and its tool children."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

PROXY_KEYS = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
              'http_proxy', 'https_proxy', 'all_proxy')


def load_proxy_settings(root: Path) -> dict:
    path = root / 'proxy-settings.json'
    if not path.exists():
        return {'enabled': False}
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_proxy_settings(settings: dict) -> None:
    if not settings.get('enabled'):
        return
    for field in ('server', 'sni', 'ws_host'):
        value = settings.get(field, '')
        if not isinstance(value, str) or not value or any(c.isspace() for c in value) or '://' in value:
            raise ValueError('代理主机、SNI 和 WebSocket Host 必须填写有效主机名。')
    if not 1 <= int(settings.get('port', 443)) <= 65535:
        raise ValueError('代理端口必须在 1–65535 之间。')
    uuid.UUID(settings.get('uuid', ''))
    if not str(settings.get('ws_path', '')).startswith('/'):
        raise ValueError('WebSocket 路径必须以 / 开头。')


def save_proxy_settings(root: Path, settings: dict) -> None:
    validate_proxy_settings(settings)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'proxy-settings.json'
    # Reuse the protected destination file so its ACL survives a switch change.
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')


def sing_box_config(settings: dict, port: int) -> dict:
    validate_proxy_settings({**settings, 'enabled': True})
    return {
        'log': {'level': 'warn', 'timestamp': True},
        'inbounds': [{'type': 'mixed', 'tag': 'codex',
                      'listen': '127.0.0.1', 'listen_port': port}],
        'outbounds': [{
            'type': 'vless', 'tag': 'vless', 'server': settings['server'],
            'server_port': int(settings.get('port', 443)), 'uuid': settings['uuid'],
            'network': 'tcp',
            'tls': {'enabled': True, 'server_name': settings['sni']},
            'transport': {'type': 'ws', 'path': settings['ws_path'],
                          'headers': {'Host': settings['ws_host']}},
        }],
        'route': {'final': 'vless'},
    }


class ProxyLease:
    """Own the tunnel process; never change the Windows system proxy."""

    def __init__(self, root: Path):
        self.root = root
        self.settings = load_proxy_settings(root)
        self.enabled = bool(self.settings.get('enabled'))
        self.process = None
        self.config_path = None
        self.log = None
        self.port = None

    @property
    def active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def url(self) -> str | None:
        return f'http://127.0.0.1:{self.port}' if self.active else None

    def start(self) -> None:
        if not self.enabled or self.active:
            return
        validate_proxy_settings(self.settings)
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
        executable = base / 'tools' / 'sing-box.exe'
        if not executable.is_file():
            raise RuntimeError('代理组件缺失，请重新安装工作台。')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            self.port = reservation.getsockname()[1]
        cache = self.root / 'cache'
        cache.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix='codex-proxy-', suffix='.json', dir=cache)
        self.config_path = Path(path)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(sing_box_config(self.settings, self.port), stream)
        logs = self.root / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        self.log = (logs / 'proxy.log').open('a', encoding='utf-8')
        env = os.environ.copy()
        for key in PROXY_KEYS:
            env.pop(key, None)
        try:
            self.process = subprocess.Popen(
                [str(executable), 'run', '-c', str(self.config_path)],
                cwd=executable.parent, env=env, stdin=subprocess.DEVNULL,
                stdout=self.log, stderr=self.log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            atexit.register(self.close)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if not self.active:
                    raise RuntimeError('VLESS 代理启动失败，请查看运行日志中的 proxy.log。')
                try:
                    with socket.create_connection(('127.0.0.1', self.port), timeout=.2):
                        return
                except OSError:
                    time.sleep(.1)
            raise RuntimeError('VLESS 代理启动超时，请查看 proxy.log。')
        except Exception:
            self.close()
            raise

    def apply_environment(self, env: dict, allow_unavailable=False) -> dict:
        if not self.enabled:
            env['LOCAL_CODEX_PROXY_URL'] = 'direct'
            return env
        if not self.active:
            if allow_unavailable:
                for key in PROXY_KEYS:
                    env.pop(key, None)
                # Keep public web tools fail-closed while allowing the local
                # app-server and local MCPs to run without the tunnel.
                env['LOCAL_CODEX_PROXY_URL'] = 'unavailable'
                return env
            raise RuntimeError('VLESS 代理已启用但未运行，请重新应用代理设置。')
        for key in PROXY_KEYS:
            env[key] = self.url
        env['LOCAL_CODEX_PROXY_URL'] = self.url
        # Model inference and the history service stay on their local endpoints.
        for key in ('NO_PROXY', 'no_proxy'):
            env[key] = 'localhost,127.0.0.1,::1'
        return env

    def close(self) -> None:
        atexit.unregister(self.close)
        if self.active:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()
            self.log = None
        if self.config_path is not None:
            self.config_path.unlink(missing_ok=True)
            self.config_path = None
