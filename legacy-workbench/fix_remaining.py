from pathlib import Path
COD = Path(r'C:\Users\18213\Desktop\codexx1')
TOTAL = 16810714400 + 931146528

# Fix display_name in core.py (uses middle dot, not Chinese char)
p = COD / 'core.py'
t = p.read_text(encoding='utf-8')
old = "'display_name': 'Jack V2 27B \u00b7 Local'"
new = "'display_name': 'Huihui Qwen3.8-27B Uncensored'"
if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding='utf-8')
    print(f'  OK core.py display_name -> {new}')
else:
    print(f'  SKIP: not found')

# Fix remaining 13051180128 in download_parallel.py
p = COD / 'download_parallel.py'
t = p.read_text(encoding='utf-8')
n = t.count('13051180128')
t = t.replace('13051180128', str(TOTAL))
p.write_text(t, encoding='utf-8')
print(f'  OK download_parallel.py: replaced {n} remaining occurrences with {TOTAL}')
