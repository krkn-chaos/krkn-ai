import os
import shutil

# Resolve the script's directory to allow running from anywhere
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from krkn_ai.utils.report_server import start_report_server
from krkn_ai.utils.logger import init_logger

def setup_demo_results():
    results_dir = os.path.join(SCRIPT_DIR, "demo_results")
    if not os.path.exists(results_dir):
        os.makedirs(os.path.join(results_dir, "reports"), exist_ok=True)
        # Copy mock data from the web package
        source_results = os.path.join(SCRIPT_DIR, "krkn_ai/web/public/results.json")
        source_reports = os.path.join(SCRIPT_DIR, "krkn_ai/web/public/reports/all.csv")
        shutil.copy(source_results, results_dir)
        shutil.copy(source_reports, os.path.join(results_dir, "reports"))
    return results_dir

def main():
    init_logger(None, False)
    results_dir = setup_demo_results()
    results_name = os.path.basename(os.path.normpath(results_dir))
    print(f"Launching Krkn-AI Dashboard (results: {results_name or results_dir})...")
    print("Dashboard will be available at http://127.0.0.1:8080")
    try:
        start_report_server(results_dir, port=8080)
    except Exception as e:
        print(f"Failed to start server: {e}")

if __name__ == "__main__":
    main()
