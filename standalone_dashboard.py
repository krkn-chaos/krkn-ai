import os
import sys
import shutil

# Add the project root to sys.path so we can import krkn_ai
sys.path.append(os.getcwd())

from krkn_ai.utils.report_server import start_report_server
from krkn_ai.utils.logger import init_logger

def setup_demo_results():
    results_dir = os.path.join(os.getcwd(), "demo_results")
    if not os.path.exists(results_dir):
        os.makedirs(os.path.join(results_dir, "reports"), exist_ok=True)
        # Copy mock data from the web package
        shutil.copy("krkn_ai/web/public/results.json", results_dir)
        shutil.copy("krkn_ai/web/public/reports/all.csv", os.path.join(results_dir, "reports"))
    return results_dir

def main():
    init_logger(None, False)
    results_dir = setup_demo_results()
    print(f"Launching Krkn-AI Dashboard from {results_dir}...")
    print("Dashboard will be available at http://127.0.0.1:8080")
    try:
        start_report_server(results_dir, port=8080)
    except Exception as e:
        print(f"Failed to start server: {e}")

if __name__ == "__main__":
    main()
