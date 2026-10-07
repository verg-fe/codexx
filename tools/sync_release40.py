"""Upload the researched v40 configuration to the already authorized private repo."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time
import prepare_github_upload as packaging
import upload_github_private as github

BASE=Path(__file__).resolve().parent
SOURCE=BASE/'release40'
ROOT=Path(r'D:\LocalCodex')
WORK=ROOT/'github-upload-work'/'v40'
ASSETS=WORK/'assets'
REPO=ROOT/'github-upload-work'/'repo'
TAG='v40-20261007'

def main():
    github.ensure_private();WORK.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(exist_ok=True)
    packaging.WORK=WORK;packaging.ASSETS=ASSETS
    source_files=list(packaging.walk(SOURCE))
    current=[ROOT/'settings.json',ROOT/'deployment-search40.json',ROOT/'instructions.md',ROOT/'model-catalog.json']
    current+=list((ROOT/'codex-home').glob('*.toml'))
    rollback=list(packaging.walk(ROOT/'backups'/'before-search40'))
    packaging.collect_secrets(source_files+current+rollback)
    for original in source_files:
        if original.suffix.lower() in ('.exe','.dll','.zip','.gguf'):continue
        clean=packaging.sanitized_file(original)
        if clean:
            target=REPO/'src'/original.relative_to(SOURCE)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(clean,target)
    docs=REPO/'docs';docs.mkdir(exist_ok=True)
    document=SOURCE/'精准搜索-v40.md';shutil.copy2(document,docs/document.name)
    shutil.copy2(packaging.sanitized_file(ROOT/'deployment-search40.json'),docs/'deployment-search40.json')
    shutil.copy2(BASE/'sync_release40.py',REPO/'tools'/'sync_release40.py')
    readme=REPO/'README.md';old=readme.read_text(encoding='utf-8')
    if '# codexx / 我的 Codex v40' not in old:
        readme.write_text('''# codexx / 我的 Codex v40

## 精准搜索与异常恢复

保留具体报错、版本和 API，优先官方来源并按相关性排序；跑偏时换查询，自动读取相关正文。
重复异常改为恢复提示并继续，不因历史失败永久阻塞；保留生成时限和无输出保护。
桌面入口使用 MyCodex-search40，v39 和升级前设置留在本机。
构建已完成；没有运行新的测试套件或性能对比。搜索精准度仍受网络与资料覆盖影响。

- [版本说明](docs/精准搜索-v40.md)
- [程序、源码和脱敏配置](https://github.com/verg-fe/codexx/releases/tag/v40-20261007)

---

'''+old,encoding='utf-8')
    application=ROOT/'app'/'MyCodex-search40'
    archives=[packaging.write_archive('MyCodex-v40-windows.zip',list(packaging.walk(application)),application),
        packaging.write_archive('codexx-source-v40.zip',source_files,SOURCE),
        packaging.write_archive('current-v40-config-and-rollback-settings.zip',current+rollback,ROOT)]
    assets=[dict(name=p.name,bytes=p.stat().st_size,sha256=packaging.digest(p)) for p in archives]
    manifest=dict(tag=TAG,private_required=True,assets=assets,credentials_redacted=True,
        models_included=False,local_original_settings_backup_modified=False)
    manifest_path=ASSETS/'release-assets-v40.json'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(manifest_path,docs/manifest_path.name)
    assets.append(dict(name=manifest_path.name,bytes=manifest_path.stat().st_size,sha256=packaging.digest(manifest_path)))
    for path in packaging.walk(REPO):
        if any(value.encode('utf-8') in path.read_bytes() for value in packaging.secrets):raise RuntimeError('Residual credential')
    git=lambda *args:github.run([github.GIT,*args],cwd=REPO)
    git('add','--all')
    if git('status','--porcelain'):git('commit','-m','Improve focused search evidence and recover from repeated failures in v40')
    commit=git('rev-parse','HEAD');github.ensure_private();git('push','origin','main')
    if not git('tag','--list',TAG):git('tag','-a',TAG,'-m','Codex v40 researched deep thinking profile')
    git('push','origin','refs/tags/'+TAG)
    publish(assets,commit)

def publish(assets,commit):
    notes=WORK/'release-notes.md'
    notes.write_text('''# 我的 Codex v40 · 精准搜索与异常恢复

- 搜索保留确切错误、库名、版本和 API；已识别的技术主题优先官方域名。
- 相关性排序、同名歧义过滤、无关结果换查询；保留独立来源的有效结果。
- 自动读取最多两页正文；主题匹配不是具体结论验证，无证据时明确返回状态。
- 重复异常提示修复并继续；旧版重复异常阻塞自动解除。
- Python 最终错误类型优先于 Traceback；缺依赖时检查实际解释器和对应 pip。
- 保留预算与无输出保护。桌面入口更新，v39 程序和升级前设置保留。
- 附件包含程序、完整源码、脱敏配置和回退设置。没有运行新的测试套件或性能对比。
''',encoding='utf-8')
    github.TAG=TAG
    if not any(r['tag_name']==TAG for r in github.api('repos/verg-fe/codexx/releases?per_page=100')):
        github.run([github.GH,'release','create',TAG,'--repo',github.NAME,'--verify-tag','--draft',
            '--title','我的 Codex v40 · 精准搜索与异常恢复','--notes-file',notes])
    release=None
    for attempt in range(12):
        try:release=github.current_release();break
        except StopIteration:time.sleep(2)
    if release is None:raise RuntimeError('New release is not visible yet; retry --publish-prepared')
    existing={a['name']:a for a in release['assets']}
    pending=[]
    for item in assets:
        if item['name'] in existing:
            if existing[item['name']].get('digest')!='sha256:'+item['sha256']:raise RuntimeError('Existing asset differs')
        else:pending.append(item)
    print(json.dumps(dict(phase='uploading v40',assets=len(assets),bytes=sum(i['bytes'] for i in pending))),flush=True)
    def upload(item):
        github.run([github.GH,'release','upload',TAG,ASSETS/item['name'],'--repo',github.NAME],timeout=7200)
        return item['name']
    with ThreadPoolExecutor(max_workers=3) as executor:
        for job in as_completed([executor.submit(upload,i) for i in pending]):print(json.dumps({'uploaded':job.result()}),flush=True)
    github.ensure_private()
    remote={a['name']:a for a in github.current_release()['assets']}
    for item in assets:
        asset=remote.get(item['name'],{})
        if asset.get('state')!='uploaded' or asset.get('size')!=item['bytes'] or asset.get('digest')!='sha256:'+item['sha256']:
            raise RuntimeError('Remote digest mismatch')
    if github.api('repos/verg-fe/codexx/git/ref/heads/main')['object']['sha']!=commit:raise RuntimeError('Remote source differs')
    github.run([github.GH,'release','edit',TAG,'--repo',github.NAME,'--draft=false'])
    release=github.current_release()
    if release['draft']:raise RuntimeError('Release unpublished')
    report=dict(complete=True,private=True,release=release['html_url'],commit=commit,assets=assets,
        all_remote_sha256_match=True,credentials_redacted=True,completed_at=datetime.now(timezone.utc).isoformat())
    (ROOT/'github-upload-v40.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('complete','private','release','commit','all_remote_sha256_match')}),flush=True)

if __name__=='__main__':
    if '--publish-prepared' in sys.argv:
        github.ensure_private()
        manifest_path=ASSETS/'release-assets-v40.json'
        assets=json.loads(manifest_path.read_text(encoding='utf-8'))['assets']
        assets.append(dict(name=manifest_path.name,bytes=manifest_path.stat().st_size,sha256=packaging.digest(manifest_path)))
        for asset in assets:
            if packaging.digest(ASSETS/asset['name'])!=asset['sha256']:raise RuntimeError('Prepared asset changed')
        commit=github.run([github.GIT,'rev-parse','HEAD'],cwd=REPO)
        publish(assets,commit)
    else:main()


