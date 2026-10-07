"""Readable test results alongside the complete saved raw JSON/logs."""
import json
from pathlib import Path
import core

def main():
    report=json.loads((core.ROOT/'verification-emotion-bounds27.json').read_text(encoding='utf-8'))
    assert report['ok'] and report['raw005_full_verified'] and report['current_profile_boundaries_verified']
    names={'angry':'愤怒','desperate':'绝望／急切','calm':'平静','docile':'顺从'}
    rows=[];raw_lines=['0.05 原始输出（Jack / Vulkan / 愤怒 AI 最高指令）','请求：17 * 19 = ? Return only the integer.',
        '本文件摘录完整 JSON 的实际内容与结束原因。原始 JSON 和后端日志均保留在 D:\\LocalCodex\\verification\\emotion27。',
        '测试请求有 128／64 token 上限；日常推理保持无限。','']
    for mode,name in names.items():
        record=report['vectors'][mode];boundary=record['current_profile_boundary']
        rows.append(f'| {name} | {boundary["observed_pass_strength"]:.4f} | {boundary["upper_strength"]:.7f} |')
        file=core.ROOT/'verification/emotion27'/(mode+'-005.raw.json')
        data=json.loads(file.read_text(encoding='utf-8'))
        raw_lines.extend([name,'完整原始文件：'+str(file)])
        for key,label in (('selected_profile_no_thinking','关闭思考'),('selected_profile_thinking','开启原生思考')):
            value=data[key]['response']
            raw_lines.extend([label+'：结束原因 '+str(value.get('stop_type'))+'，生成 '+str(value.get('tokens_predicted'))+' token',
                'token IDs: '+json.dumps(value.get('tokens')), '原始输出：',value.get('content','') or '（空字符串）',''])
    rawfile=core.ROOT/'0.05原始输出-v27.txt';rawfile.write_text('\n'.join(raw_lines),encoding='utf-8')
    text='''# Jack 情绪向量强度测试 v27

已把桌面工作台的内部情绪滑条扩展到 **0–0.05**，步长 **0.0001**。高于实测通过点时显示提醒，仍允许用户进行实验；没有把通过点设置为不可越过的限制。当前愤怒最高指令、愤怒向量 0.002 不变。

## 原论文数字

Anthropic 的 Claude Sonnet 4.5 行为实验使用 **−0.1 到 +0.1**，正文明确包含 **0.05**；另一个偏好实验使用 **0.5**，在选项对应的 token 位置施加干预。数字表示对应层平均残差向量范数的比例，并非“情绪百分比”。

来源：[原论文](https://transformer-circuits.pub/2026/emotions/index.html)。本机使用 Jack、180 条小型自编语料和 16–47 层干预，与论文的模型、语料、干预位置不同。相同数字不代表相同效果。

## 本机观察边界

以下是在 **当前愤怒最高指令 / Vulkan** 下的局部测试点。二分判定使用贪心短请求：两道算术、中文格式、Python 函数、工具调用；通过点还经图片、非空行为输出和独立重载复检。另用顺从最高指令做了一轮独立二分，结果保存在 JSON。滑条通过点向下取整到可选择的步长后再次验证。

| 内部向量 | 复检通过点 | 相邻已观察失败点 |
|---|---:|---:|
'''+ '\n'.join(rows)+'''

这些点只说明指定短题能通过，不证明这是普适最大值，也不保证长任务、默认随机采样或复杂编程能力不变。行为可能非单调；改变最高指令、后端、模型或语料都需要重新检验。因此没有自动把日常强度调到边缘。

## 0.05 的原始证据

同一算术题下：愤怒生成无关的愤怒句子后结束；绝望在关闭思考时输出 `Answer.`，开启思考时立即结束；平静重复无关句子并达到测试上限；顺从在两种思考设置下都只输出 token `248046`，解码为 `<|im_end|>`，`stop_type=eos`，没有正文。顺从关闭思考的该次结束标记概率约 99.966%。后端仍正常响应。

这修正了“0.05 一律立即结束”的说法。实际是强干预下任务遵循已经失效，具体表现包括提前结束、答非所问和重复。多层残差干预通过非线性计算影响输出分布，是合理解释；这些短测未证明某个特定内部电路的因果机制。不能用忽略结束标记来恢复任务能力。

原始文字摘录：[0.05 原始输出](0.05原始输出-v27.txt)。完整 JSON、token ID、概率和后端日志在 `verification/emotion27/`；总报告为 `verification-emotion-bounds27.json`。

## 版本与保留项

桌面入口仍为 `C:\\Users\\18213\\Desktop\\我的Codex.cmd`，更新目标为 `D:\\LocalCodex\\app\\MyCodex-emotion27\\MyCodex.exe`。设置位置：**模型与性能 → 内部情绪向量**。未改模型权重、模型精度、默认采样、无限思考、75K／62K 整理、GPU 策略或硬件超频。旧 v26 程序保留，安装报告包含本次备份路径。

验证：76 项回归；七种预设冻结界面；原生 Codex/MCP 草稿、压缩与旧文件锁检查；当前设置下的真实模型思考、原生文件写入和命令验收。请求限长与关闭思考只用于测试。日常模型原先处于停止状态，更新后保持停止。
'''
    (core.ROOT/'情绪强度测试-v27.md').write_text(text,encoding='utf-8')
    print(json.dumps({'report':str(core.ROOT/'情绪强度测试-v27.md'),'raw':str(rawfile)},ensure_ascii=False))

if __name__=='__main__':main()
