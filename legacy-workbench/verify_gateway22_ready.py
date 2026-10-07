import time
import core
from verify_hip_runtime import health

deadline=time.monotonic()+15
while time.monotonic()<deadline:
    try:
        if health().get('adapter_version')==core.ADAPTER_VERSION:break
    except OSError:pass
    time.sleep(.25)
else:raise RuntimeError('Updated local interface did not become ready')
