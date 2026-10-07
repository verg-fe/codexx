"""Upload the researched v39 configuration to the already authorized private repo."""
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
SOURCE=BASE/'release39'
ROOT=Path(r'D:\LocalCodex')
WORK=ROOT/'github-upload-work'/'v39'
ASSETS=WORK/'assets'
REPO=ROOT/'github-upload-work'/'repo'
TAG='v39-20261007'

def main():
    github.ensure_private();WORK.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(exist_ok=True)
    packaging.WORK=WORK;packaging.ASSETS=ASSETS
    source_files=list(packaging.walk(SOURCE))
    current=[ROOT/'settings.json',ROOT/'deployment-debug39.json',ROOT/'instructions.md',ROOT/'model-catalog.json']
    current+=list((ROOT/'codex-home').glob('*.toml'))
    rollback=list(packaging.walk(ROOT/'backups'/'before-debug39'))
    packaging.collect_secrets(source_files+current+rollback)
    for original in source_files:
        if original.suffix.lower() in ('.exe','.dll','.zip','.gguf'):continue
        clean=packaging.sanitized_file(original)
        if clean:
            target=REPO/'src'/original.relative_to(SOURCE)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(clean,target)
    docs=REPO/'docs';docs.mkdir(exist_ok=True)
    document=SOURCE/'调试修复-v39.md';shutil.copy2(document,docs/document.name)
    shutil.copy2(packaging.sanitized_file(ROOT/'deployment-debug39.json'),docs/'deployment-debug39.json')
    shutil.copy2(BASE/'sync_release39.py',REPO/'tools'/'sync_release39.py')
    readme=REPO/'README.md';old=readme.read_text(encoding='utf-8')
    if '# codexx / 我的 Codex v39' not in old:
        readme.write_text('''# codexx / 我的 Codex v39

## 压缩误判与命令引号修复

修复压缩摘要被伪工具标记错误中断、PowerShell 报错却记为成功、故障输出丢失。
提供 Python 参数列表的 Android 只读诊断助手，已读取实际 ART 库并确认应用、server 为 64 位。
继续使用 xhigh 深入思考、16,384 token 思考预算、32,768 token 总输出。
本机采用 15 分钟思考、20 分钟生成上限；仍保留重复异常暂停、90 秒无输出取消与每会话独立目录。
“模型与性能”提供 8K 日常、16K 推荐、32K 复杂三档，会同步调整预算与时间限制。

- [故障原因与修复范围](docs/调试修复-v39.md)。
- [v39 程序及完整源码](https://github.com/verg-fe/codexx/releases/tag/v39-20261007)。桌面入口使用 `MyCodex-debug39`。
- v37 程序和升级前设置留在本机；GitHub 配置副本已脱敏，不含真实代理或登录凭据。
- 完成构建和实际启动检查，未运行新性能测试或完整任务对比；16K 为本机工程折中，尚未证明是唯一最优值。

---

## 历史版本说明

'''+old,encoding='utf-8')
    application=ROOT/'app'/'MyCodex-debug39'
    archives=[packaging.write_archive('MyCodex-v39-windows.zip',list(packaging.walk(application)),application),
        packaging.write_archive('codexx-source-v39.zip',source_files,SOURCE),
        packaging.write_archive('current-v39-config-and-rollback-settings.zip',current+rollback,ROOT)]
    assets=[dict(name=p.name,bytes=p.stat().st_size,sha256=packaging.digest(p)) for p in archives]
    manifest=dict(tag=TAG,private_required=True,assets=assets,credentials_redacted=True,
        models_included=False,local_original_settings_backup_modified=False)
    manifest_path=ASSETS/'release-assets-v39.json'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(manifest_path,docs/manifest_path.name)
    assets.append(dict(name=manifest_path.name,bytes=manifest_path.stat().st_size,sha256=packaging.digest(manifest_path)))
    for path in packaging.walk(REPO):
        if any(value.encode('utf-8') in path.read_bytes() for value in packaging.secrets):raise RuntimeError('Residual credential')
    git=lambda *args:github.run([github.GIT,*args],cwd=REPO)
    git('add','--all')
    if git('status','--porcelain'):git('commit','-m','Fix compaction markup false positives and PowerShell error evidence in v39')
    commit=git('rev-parse','HEAD');github.ensure_private();git('push','origin','main')
    if not git('tag','--list',TAG):git('tag','-a',TAG,'-m','Codex v39 researched deep thinking profile')
    git('push','origin','refs/tags/'+TAG)
    publish(assets,commit)

def publish(assets,commit):
    notes=WORK/'release-notes.md'
    notes.write_text('''# 我的 Codex v39 · 压缩误判与命令引号修复

- 无工具摘要不拦截伪工具标记；完整消息检查区分裸调用、代码块与引用。
- PowerShell 命令不存在的错误即使返回 0 也按失败保留；先记录输出再进行防护检查。
- 提供正确传参的 Android 只读诊断脚本，已确认当前应用的 ART 和 64 位运行时。

- 根据千问官方模型卡设置 xhigh 与官方采样参数，保留历史思考。
- 默认 16K 思考、32K 总输出；允许 15 分钟思考、20 分钟生成。三档可切换。
- 重复异常仍暂停，生成开始后 90 秒无新内容取消；长输出预留上下文空间。
- 每会话独立文件夹、代理按钮与模型目录按钮继续保留，桌面入口已更新。
- v37 程序与升级前设置在本机保留；附件提供 v39 程序、源码及脱敏配置和回退设置。
- 速度依据来自已有日志，未重跑性能测试。16K 是本机折中配置，不是已证明的唯一最优值。
''',encoding='utf-8')
    github.TAG=TAG
    if not any(r['tag_name']==TAG for r in github.api('repos/verg-fe/codexx/releases?per_page=100')):
        github.run([github.GH,'release','create',TAG,'--repo',github.NAME,'--verify-tag','--draft',
            '--title','我的 Codex v39 · 压缩误判与命令引号修复','--notes-file',notes])
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
    print(json.dumps(dict(phase='uploading v39',assets=len(assets),bytes=sum(i['bytes'] for i in pending))),flush=True)
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
    (ROOT/'github-upload-v39.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('complete','private','release','commit','all_remote_sha256_match')}),flush=True)

if __name__=='__main__':
    if '--publish-prepared' in sys.argv:
        github.ensure_private()
        manifest_path=ASSETS/'release-assets-v39.json'
        assets=json.loads(manifest_path.read_text(encoding='utf-8'))['assets']
        assets.append(dict(name=manifest_path.name,bytes=manifest_path.stat().st_size,sha256=packaging.digest(manifest_path)))
        for asset in assets:
            if packaging.digest(ASSETS/asset['name'])!=asset['sha256']:raise RuntimeError('Prepared asset changed')
        commit=github.run([github.GIT,'rev-parse','HEAD'],cwd=REPO)
        publish(assets,commit)
    else:main()

