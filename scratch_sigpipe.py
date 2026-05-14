import subprocess
import time
import sys

child_script = """
import time
import sys
for i in range(10):
    time.sleep(0.5)
    print("Log statement", i)
    sys.stdout.flush()
"""

with open("child.py", "w") as f:
    f.write(child_script)

p = subprocess.Popen(
    [sys.executable, "child.py"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(1)
print("Closing parent pipes")
p.stdout.close()
p.stderr.close()

p.wait()
print("Child exited with", p.returncode)
