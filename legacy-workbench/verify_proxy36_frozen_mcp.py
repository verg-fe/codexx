"""Verify the shipped MCP executable against real public pages."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

SOURCE = Path(__file__).parent / 'release36'
sys.path.insert(0, str(SOURCE))
from proxy_service import ProxyLease

ROOT = Path(r'D:\LocalCodex')
EXE = ROOT / 'staging' / 'proxy-model36-ready' / 'MyCodex' / 'MyCodex.exe'


def main():
    lease = ProxyLease(ROOT)
    process = None
    stderr = None
    checks = {}
    report = {'checks': checks}
    started = time.monotonic()
    try:
        lease.start()
        env = lease.apply_environment(os.environ.copy())
        stderr = (ROOT / 'logs' / 'verify-proxy36-frozen-mcp.log').open('wb')
        process = subprocess.Popen([str(EXE), '--web-tools'], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW)
        replies = queue.Queue()

        def receive():
            for line in process.stdout:
                try:
                    replies.put(json.loads(line))
                except Exception:
                    replies.put({'invalid': line.decode('utf-8', errors='replace')[:300]})
            replies.put({'eof': True})

        threading.Thread(target=receive, daemon=True).start()

        def call(number, method, params):
            request = {'jsonrpc': '2.0', 'id': number, 'method': method, 'params': params}
            process.stdin.write(json.dumps(request, ensure_ascii=False).encode('utf-8') + b'\n')
            process.stdin.flush()
            response = replies.get(timeout=30)
            if response.get('id') != number or 'error' in response:
                raise RuntimeError('Unexpected MCP response: ' + str(response)[:400])
            return response['result']

        init = call(1, 'initialize', {'protocolVersion': '2024-11-05',
            'capabilities': {}, 'clientInfo': {'name': 'codexx-package-check', 'version': '1'}})
        checks['frozen_stdio_initializes'] = init['serverInfo']['name'] == 'local-web-research'
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        process.stdin.flush()
        listed = call(2, 'tools/list', {})
        names = [tool['name'] for tool in listed['tools']]
        checks['frozen_tools_registered'] = set(names) == {'search_web', 'read_webpage'}
        report['tool_names'] = names

        searched = call(3, 'tools/call', {'name': 'search_web',
            'arguments': {'query': 'pathlib', 'domains': ['docs.python.org'], 'limit': 5}})
        if searched.get('isError'):
            raise RuntimeError('Search failed: ' + searched['content'][0]['text'][:600])
        results = json.loads(searched['content'][0]['text'])
        checks['frozen_real_search_via_proxy'] = bool(results['results']) and results['via_proxy']
        report['search_sources'] = results['sources']
        report['search_links'] = [row['url'] for row in results['results']]

        webpage = call(4, 'tools/call', {'name': 'read_webpage',
            'arguments': {'url': 'https://docs.python.org/3/library/pathlib.html',
                'max_chars': 2200, 'find': 'Path'}})
        if webpage.get('isError'):
            raise RuntimeError('Page failed: ' + webpage['content'][0]['text'][:600])
        page = json.loads(webpage['content'][0]['text'])
        checks['frozen_reads_official_page_via_proxy'] = 'pathlib' in page['title'].lower() and page['via_proxy'] and len(page['text']) > 500
        report['read_page'] = {'url': page['url'], 'title': page['title'], 'chars': len(page['text'])}
        process.stdin.close()
        process.wait(timeout=8)
        checks['frozen_exits_cleanly'] = process.returncode == 0
    except Exception as error:
        report['error'] = str(error)
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=8)
        if stderr:
            stderr.close()
        lease.close()
        checks['proxy_cleaned_up'] = not lease.active and lease.config_path is None
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report['ok'] = len(checks) == 6 and all(checks.values()) and 'error' not in report
        (ROOT / 'verification-proxy36-frozen-mcp.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
