"""Fetch the official portable GitHub CLI and verify its release digest."""
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error
import zipfile

ROOT = Path(r'D:\LocalCodex\github-upload-work')
ROOT.mkdir(parents=True, exist_ok=True)
URL = 'https://api.github.com/repos/cli/cli/releases/latest'
HEADERS = {'User-Agent': 'codexx-private-upload', 'Accept': 'application/vnd.github+json'}
try:
    with urllib.request.urlopen(urllib.request.Request(URL, headers=HEADERS), timeout=30) as response:
        release = json.load(response)
    asset = next(item for item in release['assets'] if item['name'].endswith('_windows_amd64.zip'))
except urllib.error.HTTPError as error:
    if error.code != 403:
        raise
    # The current version was independently read from the official release page.
    release = {'tag_name': 'v2.102.0'}
    asset = {'name': 'gh_2.102.0_windows_amd64.zip',
        'browser_download_url': 'https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_windows_amd64.zip'}
archive = ROOT / asset['name']
with urllib.request.urlopen(urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': HEADERS['User-Agent']}), timeout=30) as response, archive.open('wb') as target:
    while chunk := response.read(1024 * 1024):
        target.write(chunk)
with archive.open('rb') as stream:
    actual = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
expected = asset.get('digest')
if not expected:
    checksums_url = asset['browser_download_url'].rsplit('/', 1)[0] + '/gh_2.102.0_checksums.txt'
    with urllib.request.urlopen(urllib.request.Request(checksums_url, headers={'User-Agent': HEADERS['User-Agent']}), timeout=30) as response:
        checksums = response.read().decode('utf-8')
    expected = 'sha256:' + next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == asset['name'])
if actual != expected:
    raise RuntimeError('GitHub CLI release digest mismatch or missing digest')
destination = ROOT / 'gh'
destination.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as package:
    package.extractall(destination)
executable = next(destination.rglob('gh.exe'))
(ROOT / 'gh-download.json').write_text(json.dumps({'version': release['tag_name'], 'exe': str(executable), 'sha256': actual, 'source': asset['browser_download_url']}, indent=2), encoding='utf-8')
print(json.dumps({'version': release['tag_name'], 'exe': str(executable), 'sha256_verified': True}))
