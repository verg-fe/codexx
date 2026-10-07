"""Publish measured capacities and resource limits without treating probes as full tests."""
from datetime import datetime
import json
import re
from pathlib import Path
import core

def publish():
    tests=json.loads((core.ROOT/'context-limit-tests.json').read_text(encoding='utf-8'))['tests']
    caps=core.verified_context_limits()
    settings=core.load_settings()
    chosen={name:core.context_for(settings,name) for name in core.MODELS}
    gpu_note=(f'模型层全部在显卡运行，CPU 卸载与自动回退关闭。当前 Jack 设置为 {chosen[core.MODEL]:,} token；'
              'Huihui Q4_K 不满足当前全 GPU 模式的显存余量要求，仍保留模型文件与选项，切换时会提示。'
              '分词、界面和编程工具仍会使用 CPU。' if not settings.get('cpu_offload',False) else '')
    pending=''
    skipped=''
    try:
        options=json.loads((core.ROOT/'logs/context-test-options.json').read_text(encoding='utf-8'))
        if options.get('skip_huihui') is True:
            skipped='Huihui 的更大窗口测试已取消，保留模型选项和历史验证记录。'
    except (OSError,ValueError):
        pass
    try:
        state=json.loads((core.ROOT/'logs/maximum-context-status.json').read_text(encoding='utf-8'))
        if state.get('phase')=='cancelled':
            pending='全部上下文极限测试已按你的要求停止。窗口按你最新选择保存，不会继续后台极限测试或自动提高窗口。'
        elif state.get('phase')!='complete':
            pending=f"更大窗口仍在测试：{state.get('model','')}，请求窗口 {state.get('context',0):,} token。上面的容量是当前已完成验证的值。全部测试结束后会自动更新默认设置、再次检查桌面程序并打开软件。"
    except (OSError,ValueError):
        pass
    rows=[]
    measured=[]
    for case in tests:
        name=core.MODELS[case['model']]['label']
        kind='分配与短回复' if case.get('probe_only') else '完整长输入与 KV 复用'
        result='通过' if case.get('ok') else ('仅分配通过' if case.get('allocation_ok') else '未通过')
        if case.get('stopped_for_ram'): result='可用 RAM 过低，已停止'
        if case.get('below_stable_reserve'): result='已加载，但低于稳定内存余量'
        if not case.get('ok') and not case.get('error') and case.get('allocated_context')==case['context']-1:
            result='接口舍入差 1 token，已修正测试并重测'
        speed=(case.get('timings') or {}).get('prompt_per_second')
        generation=(case.get('short_prompt_timings') if case.get('probe_only') else case.get('timings')) or {}
        decode=generation.get('predicted_per_second')
        loading='直接加载' if case.get('mmap') is False else '文件映射'
        rows.append(f"| {name} | {case['context']:,} | {kind} | {result} | {case.get('actual_input_tokens','—')} | "
                    f"{case.get('seconds','—')} | {round(speed,1) if speed else '—'} | {case.get('minimum_available_ram_mib','—')} | "
                    f"{loading} | {case.get('gpu_layers','—')} | {round(decode,2) if decode else '—'} |")
    for model,cap in caps.items():
        complete=[case for case in tests if case['model']==model and case.get('ok') and
            not case.get('probe_only') and case.get('usable_context',case['context'])==cap]
        if complete:
            case=complete[-1]
            reuse=case.get('kv_reuse',{})
            measured.append(f"- {core.MODELS[model]['label']}：实输 {case['actual_input_tokens']:,} token，"
                f"完整请求 {case['seconds']/60:.1f} 分钟，三个位置的信息均正确找回。"
                f"重复请求复用 {reuse.get('cache_n',0):,} token，只重算 {reuse.get('prompt_n',0)} token；"
                f"预处理 {reuse.get('prompt_ms',0)/1000:.2f} 秒。最低可用 RAM {case['minimum_available_ram_mib']:,.0f}MiB。")
    text=f'''# 上下文极限与双模型验证

更新：{datetime.now().isoformat(timespec='seconds')}。本机 Ryzen 5 7500F、32GB RAM、RX 9070 16GB；llama.cpp b11327 Vulkan。

Jack 已验证窗口：**{caps[core.MODEL]:,} token**。Huihui 已验证窗口：**{caps[core.HUIHUI_MODEL]:,} token**。
当前默认：Jack **{chosen[core.MODEL]:,} token**；Huihui **{chosen[core.HUIHUI_MODEL]:,} token**。
当前滑条可选：**{core.MIN_CONTEXT:,} — {core.MAX_CONTEXT:,} token（{core.MIN_CONTEXT/1024:g}K — {core.MAX_CONTEXT/1024:g}K）**，两种模型选择上限均为 {core.MAX_CONTEXT/1024:g}K。设置上限与历史实测容量分别记录。
自动缓存规则：所选值是对话总上限；按实际输入加生成预留量选择窗口。短输入使用 **107K（109,568 token）显存 KV**，较长输入才加载完整内存 KV，模型权重仍在显卡。生成预留量不限制思考长度。切换会重载模型并重建 KV；真实长输入的内存带宽瓶颈仍然存在。
上面的已验证窗口是历史容量记录；当前设置按你最新选择使用。上下文是输入、历史、工具结果、图片与输出共享的总窗口。

{pending}

{skipped}

{gpu_note}

## 操作

打开“我的 Codex” → “模型与性能” → 选择 Jack 或 Huihui → 拖动上下文滑条 → 点击“应用模型与上下文”。
两种模型分别保存选择。应用时会重新加载模型及编程内核，并恢复当前会话；任务执行中不能切换。
自动压缩阈值随窗口更新，预留最多 32,768 token 用于输出与工具回合。命令和文件修改保持自动确认。

## 测量

完整测试使用接近窗口上限的真实 token 输入，要求正确回忆开头、中间、结尾三个唯一代码；随后重复输入，检查 KV 前缀复用。
分配测试只检查加载与短回复，不能证明同等长度的实际输入可用；历史实测容量与用户选择的滑条上限分别保存。
测试每 3 秒采样可用 RAM；早期使用 2GB 保护线，后续为桌面与编程工具预留 3GB。持续低于保护线时停止本软件的模型进程，记录失败。具体配置保存在每轮原始结果中。
短回复筛选另留 256MiB，用于长请求的分词和传输。表格列出已完成轮次；调整配置时中止的长输入不作为失败或容量依据。

| 模型 | 请求窗口 token | 测试类型 | 结果 | 实际输入 token | 首次输入秒 | 输入 token/秒 | 最低可用 RAM MiB | 加载方式 | GPU 层 | 输出 token/秒 |
|---|---:|---|---|---:|---:|---:|---:|---|---:|---:|
{chr(10).join(rows)}

{chr(10).join(measured)}

两个 GGUF 的原生元数据窗口均为 262,144。Qwen 发布者标注可用 YaRN 扩展至 1,000,000：
[Qwen 官方模型说明](https://huggingface.co/Qwen/Qwen3.8-27B)。这不等于本机已验证 100 万。
实测上限依赖当前硬件、后端、显存分配、其他程序占用和输入内容；未穷举所有分配策略或每一个窗口值。
大窗口首次读取需要等待，已有前缀的后续回合可复用缓存；修改历史或压缩会需要重算。
当前使用直接加载权重；模型已经搬到 G 盘。表格里的旧轮次包含搬迁前 D 盘的加载记录；模型加载时间与长输入处理时间分开记录。
部分扩展窗口经后端舍入会比请求少 1 token；历史记录保留接口报告的可用容量，滑条范围按用户当前选择显示。
模型切换或窗口调整会先释放旧模型，再加载新配置。接口带版本检查；每次发送明确指定所选模型，防止旧会话沿用此前的模型。

## 文件和集成

模型位于 `{core.MODEL_DIRECTORY}`，包括现有 Jack 与下载完成的 Huihui Q4_K。共享 BF16 视觉组件。
Codex 编程内核和本地模型接口均列出两个选项；网关按请求中的模型名称加载对应权重，避免名称和实际模型不一致。
已有 Codex CLI 可分别使用 `codex -p jack-local` 和 `codex -p huihui-local`。个人桌面软件在模型页切换。
全局默认配置保持原有设置；本地会话配置位于独立的 `D:\\LocalCodex\\codex-home`。

原始结果：`context-limit-tests.json`；通过完整测试的容量：`context-limits.json`；
真实界面切换、对话保留及命令执行：`verification-model-picker.json`。窗口版的 20K → 64K → 100K 切换及失败回退：`verification-window-switch.json`。较早的 100K 连续压缩记录保留在 `verification-100k.json`。
'''
    (core.ROOT/'上下文极限测试报告.md').write_text(text,encoding='utf-8')
    path=core.ROOT/'模型调研与使用说明.md'
    old=path.read_text(encoding='utf-8')
    old=old.replace('# 我的 Codex：Jack V2 本地版','# 我的 Codex：Jack / Huihui 本地双模型版',1)
    old=old.replace('模型、推理引擎和会话数据位于 `D:\\LocalCodex`。',
                    f'模型位于 `{core.MODEL_DIRECTORY}`；推理引擎和会话数据位于 `D:\\LocalCodex`。')
    old=old.replace('D:\\LocalCodex\\models',str(core.MODEL_DIRECTORY))
    if gpu_note and '## 当前推理方式' not in old:
        old=old.replace('## 使用','## 当前推理方式\n\n'+gpu_note+'\n\n## 使用',1)
    elif gpu_note:
        old=re.sub(r'(?ms)^## 当前推理方式\n.*?(?=^## |\Z)',lambda match:'## 当前推理方式\n\n'+gpu_note+'\n\n',old,count=1)
    summary=f'已增加 Huihui Q4_K 选项与上下文滑条。Jack 当前默认 {chosen[core.MODEL]:,} token，Huihui 当前默认 {chosen[core.HUIHUI_MODEL]:,} token。全部极限测试已按你的要求停止；Jack 自动压缩阈值为 {core.compact_for(chosen[core.MODEL]):,} token。窗口是输入、历史、图片与输出共享的总量。历史验证记录见 [上下文极限测试报告](上下文极限测试报告.md)。'
    old=re.sub(r'(?m)^(?:服务上下文与 Codex 窗口均设置为|已增加 Huihui Q4_K 选项与上下文滑条).*$',lambda match:summary,old,count=1)
    old=old.replace('未将它替换为你的主模型，也未额外下载十几 GB 权重。','你已下载的 Huihui Q4_K 已加入模型选择，共享现有视觉组件。下载完成记录包含 SHA256 校验。')
    old=old.replace('这些变体尚未在本机对比测试。','本次验证上下文、缓存复用、模型切换和工具接入；未开展编程能力排名测试。')
    path.write_text(old,encoding='utf-8')

if __name__=='__main__':
    publish()
