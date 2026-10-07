from pathlib import Path
import re

COD = Path(r'C:\Users\18213\Desktop\codexx1')
HF = 'https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF/resolve/main'
MODEL = 'Huihui-Qwen3.8-27B-abliterated-Q4_K'
HASH = '6c2c13cef89238c3604d756b07b3ef5fafebbd61095feb8553ff449c95e4c1c6'
SIZE = 16810714400
VISION_HASH = '13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16'
VISION_SIZE = 931146528

def patch(fname, old, new, count=1):
    p = COD / fname
    text = p.read_text(encoding='utf-8')
    n = text.count(old)
    if n != count:
        print(f'  SKIP {fname}: expected {count} of {old[:60]!r}, found {n}')
        return
    text = text.replace(old, new)
    p.write_text(text, encoding='utf-8')
    print(f'  OK {fname}: replaced')

print('=== core.py ===')
patch('core.py', "MODEL = 'Jack-3.8-27B-V2-VL-16GB-VRAM'", f"MODEL = '{MODEL}'")
patch('core.py', "powered by Jack V2 on Qwen3.8-27B.", "powered by Huihui Qwen3.8-27B (uncensored).")
patch('core.py', "r'C:\\Users\\18213\\Desktop\\codexx'", "r'C:\\Users\\18213\\Desktop\\codexx1'")
patch('core.py', "'display_name': 'Jack V2 27B \u8def Local'", "'display_name': 'Huihui Qwen3.8-27B Uncensored'")
patch('core.py', "'comp_hash': 'jack-v2-local-40k'", "'comp_hash': 'huihui-q4k-local-40k'")

print('=== download_model.ps1 ===')
patch('download_model.ps1', r'$taskModel = "$taskRoot\models\Jack-3.8-27B-V2-VL-16GB-VRAM.gguf"', f'$taskModel = "$taskRoot\\models\\{MODEL}.gguf"')
patch('download_model.ps1', "'https://huggingface.co/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/Jack-3.8-27B-V2-VL-16GB-VRAM.gguf?download=true'", f"'{HF}/{MODEL}.gguf'")
patch('download_model.ps1', "'c20dab06e201b2591318526031982152a79dcda2169c4d3bbb3826b1a5597e95'", f"'{HASH}'")
patch('download_model.ps1', "'https://huggingface.co/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/mmproj-Qwen3.8-27B-BF16.gguf?download=true'", f"'https://hf-mirror.com/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/mmproj-Qwen3.8-27B-BF16.gguf?download=true'")

print('=== download_parallel.py ===')
patch('download_parallel.py', "REPO = 'https://huggingface.co/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/'", f"REPO = '{HF}/'")
old_files = "FILES = [('Jack-3.8-27B-V2-VL-16GB-VRAM.gguf', 12120033600,\n          'c20dab06e201b2591318526031982152a79dcda2169c4d3bbb3826b1a5597e95'),\n         ('mmproj-Qwen3.8-27B-BF16.gguf', 931146528,\n          '13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16')]"
new_files = f"FILES = [('{MODEL}.gguf', {SIZE},\n          '{HASH}'),\n         ('mmproj-Qwen3.8-27B-BF16.gguf', {VISION_SIZE},\n          '{VISION_HASH}')]"
patch('download_parallel.py', old_files, new_files)
total = SIZE + VISION_SIZE
patch('download_parallel.py', '13051180128', str(total))
patch('download_parallel.py', '13.05 GB', f'{total/1e9:.2f} GB')
patch('download_parallel.py', "'Jack model and vision verified'", "'Huihui Q4_K model and vision verified'")

print('=== \u542f\u52a8\u672c\u5730Codex.ps1 ===')
patch('\u542f\u52a8\u672c\u5730Codex.ps1', r"Push-Location -LiteralPath 'C:\Users\18213\Desktop\codexx'", r"Push-Location -LiteralPath 'C:\Users\18213\Desktop\codexx1'")
patch('\u542f\u52a8\u672c\u5730Codex.ps1', r"-C 'C:\Users\18213\Desktop\codexx'", r"-C 'C:\Users\18213\Desktop\codexx1'")

print('=== app.py ===')
patch('app.py', "'Jack V2 \u00b7 27B VL'", "'Huihui Qwen3.8-27B Uncensored'")
patch('app.py', "'Jack-3.8-27B-V2-VL-16GB-VRAM  \u00b7  Vulkan'", f"'{MODEL}  \u00b7  Vulkan'")
p = COD / 'app.py'
text = p.read_text(encoding='utf-8')
m = re.search(r'/\s*13\.05', text)
if m:
    text = text.replace('/ 13.05', f'/ {total/1e9:.2f}')
    p.write_text(text, encoding='utf-8')
    print(f'  OK app.py: progress total -> {total/1e9:.2f}')
patch('app.py', "# Hide Jack's state XML in the UI while preserving it in the engine's model history.", "# Hide model's state XML in the UI while preserving it in the engine's model history.")

print('All patches applied.')
