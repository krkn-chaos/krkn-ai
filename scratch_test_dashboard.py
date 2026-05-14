import sys
from krkn_ai.dashboard.manager import DashboardManager
import time
import subprocess
import urllib.request

p = DashboardManager.start(".", 8501, background=True)
if not p:
    print("Dashboard failed to start!")
    sys.exit(1)

print("Dashboard started with PID:", p.pid)
time.sleep(3)  # Wait for it to initialize

try:
    print("Testing HTTP request to Streamlit to trigger logging...")
    urllib.request.urlopen("http://localhost:8501")
except Exception as e:
    print("Request failed:", e)

time.sleep(2)  # Give it time to crash if SIGPIPE

if p.poll() is None:
    print("Success: Dashboard process is still alive!")
    p.terminate()
else:
    print("Failure: Dashboard process crashed with code", p.returncode)
