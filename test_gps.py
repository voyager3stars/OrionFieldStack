import subprocess
import select
import time
import json

proc = subprocess.Popen(
    ["gpspipe", "-w"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True
)

start_time = time.monotonic()
tpv_data = None

while time.monotonic() - start_time < 3.0:
    r, _, _ = select.select([proc.stdout], [], [], 0.1)
    if proc.stdout in r:
        line = proc.stdout.readline()
        print("Got line:", line.strip())
        if not line:
            break
        try:
            data = json.loads(line.strip())
            if data.get("class") == "TPV":
                tpv_data = data
                print("Found TPV!")
                break
        except ValueError:
            pass

proc.terminate()
proc.wait(timeout=0.2)
print("Result:", tpv_data)
