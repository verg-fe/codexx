"""Start the repaired workbench; loading a saved thread does not start a turn."""
from pathlib import Path
import subprocess

APP = Path('D:/LocalCodex/app/MyCodex-tool-recovery51/MyCodex.exe')
subprocess.Popen([str(APP), '--no-auto-model', '--resume-after-update'])
