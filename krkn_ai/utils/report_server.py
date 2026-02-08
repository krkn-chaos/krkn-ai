import os
import http.server
import socketserver
import threading
import webbrowser
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

class ReportHandler(http.server.SimpleHTTPRequestHandler):
    """
    Custom handler to serve both the static dashboard and the results data.
    """
    def __init__(self, *args, **kwargs):
        self.dist_dir = kwargs.pop('dist_dir', None)
        self.results_dir = kwargs.pop('results_dir', None)
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        # Default behavior for root and dashboard assets
        if path == '/':
            return os.path.join(self.dist_dir, "index.html")
        
        if path.startswith('/assets/'):
            return os.path.join(self.dist_dir, path.lstrip('/'))
        
        # Serve results.json and reports/* from the results directory
        if path == '/results.json' or path.startswith('/reports/'):
            return os.path.join(self.results_dir, path.lstrip('/'))
            
        return super().translate_path(path)

def start_report_server(results_dir: str, port: int = 8080, headless: bool = False):
    # Locate the built dashboard in the package
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(base_dir, "web", "dist")

    if not os.path.exists(dist_dir):
        logger.error("Dashboard not found! Please ensure it is built in '%s'", dist_dir)
        return

    # Check if results exist
    if not os.path.exists(os.path.join(results_dir, "results.json")):
        logger.warning("Warning: results.json not found in '%s'. Dashboard might be empty.", results_dir)

    def run_server():
        # Create a partial class with the directories closed over
        handler = lambda *args, **kwargs: ReportHandler(
            *args, 
            dist_dir=dist_dir, 
            results_dir=results_dir, 
            **kwargs
        )
        
        # Use a socket server that allows address reuse
        socketserver.TCPServer.allow_reuse_address = True
        try:
            with socketserver.TCPServer(("", port), handler) as httpd:
                logger.info("Krkn-AI Dashboard serving at http://localhost:%d", port)
                logger.info("Press Ctrl+C to stop.")
                httpd.serve_forever()
        except Exception as e:
            logger.error("Server failed: %s", e)

    # Start server in a background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Open the browser if not headless
    if not headless and os.getenv("KRKN_AI_HEADLESS") != "true":
        webbrowser.open(f"http://localhost:{port}")

    # Keep the main thread alive
    try:
        while True:
            server_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        logger.info("Shutting down report server.")
