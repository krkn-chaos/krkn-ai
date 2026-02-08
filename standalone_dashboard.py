import os
import shutil

# Resolve the script's directory to allow running from anywhere
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from krkn_ai.utils.report_server import start_report_server
from krkn_ai.utils.logger import init_logger

def setup_demo_results():
    """Set up demo results directory with validation and error handling."""
    results_dir = os.path.join(SCRIPT_DIR, "demo_results")
    if not os.path.exists(results_dir):
        os.makedirs(os.path.join(results_dir, "reports"), exist_ok=True)
        
        # Validate source directory exists
        source_dir = os.path.join(SCRIPT_DIR, "krkn_ai", "web", "public")
        if not os.path.exists(source_dir):
            print(f"Warning: Demo assets not found at {source_dir}")
            print("Creating empty demo_results directory...")
            print("You can manually add results.json and reports/ to this directory.")
            return results_dir
        
        # Copy files with validation and error handling
        files_to_copy = [
            ("results.json", results_dir),
            ("reports/all.csv", os.path.join(results_dir, "reports"))
        ]
        
        try:
            for file_path, dest_dir in files_to_copy:
                source_file = os.path.join(source_dir, file_path)
                if os.path.exists(source_file):
                    shutil.copy(source_file, dest_dir)
                    print(f"✓ Copied {file_path}")
                else:
                    print(f"Warning: {file_path} not found, skipping...")
        except Exception as e:
            print(f"Error copying demo files: {e}")
            print("Demo directory created but may be incomplete.")
    
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
