"""Publish v37 source, program and redacted rollback snapshot to the private repo."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess
import prepare_github_upload as packaging
import upload_github_private as github

BASE=Path(__file__).resolve().parent
SOURCE=BASE/'release37'
ROOT=Path(r'D:\LocalCodex')
WORK=ROOT/'github-upload-work'/'v37'
ASSETS=WORK/'assets'
REPO=ROOT/'github-upload-work'/'repo'
TAG='v37-20261007'

def main():
    github.ensure_private()
    WORK.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(exist_ok=True)
    packaging.WORK=WORK;packaging.ASSETS=ASSETS
    backup=Path(json.loads((ROOT/'backup-before-v37.json').read_text(encoding='utf-8'))['path'])
    source_files=list(packaging.walk(SOURCE))
    backup_files=list(packaging.walk(backup))
    current_files=[ROOT/name for name in ('settings.json','deployment-guard37.json','backup-before-v37.json','instructions.md','model-catalog.json')]
    current_files += list((ROOT/'codex-home').glob('*.toml'))
    previous=Path(r'C:\my_projects\MyCodex-v35-backup-20261007-104748')
    previous_small=[p for p in packaging.walk(previous) if p.stat().st_size<1024*1024 and packaging.is_text(p)]
    packaging.collect_secrets(source_files+backup_files+current_files+previous_small)
    for original in source_files:
        if original.suffix.lower() in ('.exe','.dll','.zip','.gguf'):continue
        clean=packaging.sanitized_file(original)
        if clean:
            target=REPO/'src'/original.relative_to(SOURCE)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(clean,target)
    docs=REPO/'docs';docs.mkdir(exist_ok=True)
    document=SOURCE/'防循环与会话文件夹-v37.md'
    shutil.copy2(document,docs/document.name)
    for original in current_files:
        if not original.is_file():continue
        clean=packaging.sanitized_file(original)
        if clean and original.name in ('deployment-guard37.json','backup-before-v37.json'):
            shutil.copy2(clean,docs/original.name)
    for helper in ('prepare_release37.py','sync_release37.py'):
        clean=packaging.sanitized_file(BASE/helper)
        if clean:shutil.copy2(clean,REPO/'tools'/helper)
    readme=REPO/'README.md'
    previous_readme=readme.read_text(encoding='utf-8')
    if '# codexx / 我的 Codex v37' not in previous_readme:
        readme.write_text('''# codexx / 我的 Codex v37

Windows 本地编程工作台，当前维护源码在 `src/`。

## v37：防止无进展循环与独立会话目录

- 有限思考预算、真实推理取消、同类异常三次暂停、原生工具参数检查与官方 API 资料查证。
- 默认思考 60 秒、单次生成 150 秒、整个任务 10 分钟；模型设置里提供三档限制。
- 每次新会话创建独立文件夹；左侧“会话文件夹位置”修改根目录。恢复旧会话沿用原目录。
- 原 XML 强制自检流程首次升级切换为原生模式，其他预设仍可选择。
- [详细说明和检查范围](docs/防循环与会话文件夹-v37.md)。完成构建与实际启动检查，未运行自动回归测试。

## 下载与安装

[v37 程序、源码和 v36 回退快照](https://github.com/verg-fe/codexx/releases/tag/v37-20261007)。
将程序包解压到 `D:\\LocalCodex\\app\\MyCodex-guard37`，运行 `MyCodex.exe`。
已有本地运行时、引擎与模型配置继续沿用；完整运行组件及此前全部工作目录在 [v36 完整归档](https://github.com/verg-fe/codexx/releases/tag/v36-20261007)。

真实登录凭据和代理配置不上传；已知 API 密钥脱敏。原始本机备份保持不变。GGUF 权重未上传。

---

## v36 安装及历史归档资料

'''+previous_readme.replace('# codexx / 我的 Codex v36\n','',1),encoding='utf-8')
    archives=[packaging.write_archive('MyCodex-v37-windows.zip',list(packaging.walk(ROOT/'app'/'MyCodex-guard37')),ROOT/'app'/'MyCodex-guard37'),
        packaging.write_archive('codexx-source-v37.zip',source_files,SOURCE),
        packaging.write_archive('MyCodex-v36-backup-redacted.zip',backup_files,backup),
        packaging.write_archive('current-v37-config-and-reports.zip',[p for p in current_files if p.is_file()],ROOT)]
    assets=[dict(name=p.name,bytes=p.stat().st_size,sha256=packaging.digest(p)) for p in archives]
    manifest=dict(tag=TAG,assets=assets,private_required=True,credentials_redacted=True,models_included=False,
        original_backup_modified=False,archives=packaging.audit['archive_files'])
    manifest_path=ASSETS/'release-assets-v37.json'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(manifest_path,docs/manifest_path.name)
    assets.append(dict(name=manifest_path.name,bytes=manifest_path.stat().st_size,sha256=packaging.digest(manifest_path)))
    audit=dict(known_secret_values=len(packaging.secrets),redacted_files=len(set(packaging.audit['redacted_files'])),
        excluded_credentials=len(set(packaging.audit['excluded_credentials'])),original_backup_modified=False)
    (docs/'upload-audit-v37.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    for path in packaging.walk(REPO):
        raw=path.read_bytes()
        if any(value.encode('utf-8') in raw for value in packaging.secrets):raise RuntimeError('Residual credential in '+str(path.relative_to(REPO)))
    git=lambda *args:github.run([github.GIT,*args],cwd=REPO)
    git('add','--all')
    if git('status','--porcelain'):git('commit','-m','Add finite inference guards and per-chat workspaces in v37')
    commit=git('rev-parse','HEAD')
    github.ensure_private();git('push','origin','main')
    if not git('tag','--list',TAG):git('tag','-a',TAG,'-m','Codex v37 bounded generation and session directories')
    git('push','origin','refs/tags/'+TAG)
    notes=WORK/'release-notes.md'
    notes.write_text('''# 我的 Codex v37

- 防止长时间思考和重复报错循环，实际取消推理，保留失败证据；接口报错先查证资料。
- 每个新会话一个独立文件夹，可选择保存位置，恢复历史会话使用原目录。
- 默认思考 60 秒、单次生成 150 秒、任务 10 分钟；模型设置提供严格、标准、宽松三档。
- 附件提供 v37 程序、完整源码、当前脱敏配置及升级前 v36 快照。完整运行组件沿用 v36 Release。
- 已完成构建和实际启动检查，未运行自动回归测试；不保证模型永不犯错。
- 本机原始备份保留，上传副本已知密钥脱敏并排除登录和真实代理配置；模型权重不上传。
''',encoding='utf-8')
    github.TAG=TAG
    existing=github.api('repos/verg-fe/codexx/releases?per_page=100')
    if not any(r['tag_name']==TAG for r in existing):
        github.run([github.GH,'release','create',TAG,'--repo',github.NAME,'--verify-tag','--draft',
            '--title','我的 Codex v37 · 防循环与独立会话目录','--notes-file',notes])
    release=github.current_release();present={r['name']:r for r in release['assets']}
    pending=[]
    for item in assets:
        remote=present.get(item['name'])
        if remote:
            if remote.get('digest')!='sha256:'+item['sha256']:raise RuntimeError('Existing asset changed: '+item['name'])
        else:pending.append(item)
    print(json.dumps(dict(phase='uploading v37',assets=len(assets),bytes=sum(a['bytes'] for a in pending))),flush=True)
    def upload(item):
        github.run([github.GH,'release','upload',TAG,ASSETS/item['name'],'--repo',github.NAME],timeout=7200)
        return item['name']
    with ThreadPoolExecutor(max_workers=3) as executor:
        for job in as_completed([executor.submit(upload,a) for a in pending]):print(json.dumps({'uploaded':job.result()}),flush=True)
    github.ensure_private();remote=github.current_release()
    uploaded={a['name']:a for a in remote['assets']}
    for item in assets:
        asset=uploaded.get(item['name'],{})
        if asset.get('state')!='uploaded' or asset.get('size')!=item['bytes'] or asset.get('digest')!='sha256:'+item['sha256']:
            raise RuntimeError('Remote digest mismatch: '+item['name'])
    if github.api('repos/verg-fe/codexx/git/ref/heads/main')['object']['sha']!=commit:raise RuntimeError('Remote source differs')
    github.run([github.GH,'release','edit',TAG,'--repo',github.NAME,'--draft=false'])
    remote=github.current_release()
    if remote['draft']:raise RuntimeError('Still a draft')
    report=dict(complete=True,private=True,release=remote['html_url'],commit=commit,assets=assets,
        all_remote_sha256_match=True,credentials_redacted=True,completed_at=datetime.now(timezone.utc).isoformat())
    (ROOT/'github-upload-v37.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('complete','private','release','commit','all_remote_sha256_match')}),flush=True)

if __name__=='__main__':main()
