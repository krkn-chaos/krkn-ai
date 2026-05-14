import sys
import threading
from krkn_ai.utils import run_shell

child_script = """
import time
import sys
import subprocess
subprocess.Popen(["sleep", "10"])
print("done")
"""
with open("child.py", "w") as f:
    f.write(child_script)

def test_leak():
    print(f"Threads before: {threading.active_count()}")
    try:
        run_shell(f"{sys.executable} child.py", timeout=5)
    except Exception as e:
        print(f"Exception: {e}")
    print(f"Threads after: {threading.active_count()}")
    
test_leak()
