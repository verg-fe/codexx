from pathlib import Path
import subprocess

subprocess.Popen([str(Path('D:/LocalCodex/app/MyCodex-runtime52/MyCodex.exe')),
                  '--no-auto-model','--resume-after-update'])
