import subprocess
import sys
import time
from core import ROOT, MODEL_FILE, VISION_FILE

while not (MODEL_FILE.exists() and VISION_FILE.exists()):
    time.sleep(15)
    print('Waiting for verified model and vision files...', flush=True)
result = subprocess.run([sys.executable, '-u', 'verify_local.py'])
sys.exit(result.returncode)
