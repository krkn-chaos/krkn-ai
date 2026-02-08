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

    def is_safe_path(self, base_dir, path):
        """Check if path is resolved within base_dir to prevent traversal."""
        # Normalize and resolve absolute path
        abs_base = os.path.abspath(base_dir)
        target_path = os.path.normpath(os.path.join(abs_base, path.lstrip('/')))
        return target_path.startswith(abs_base)

    def translate_path(self, path):
        # Default behavior for root
        if path == '/':
            return os.path.join(self.dist_dir, "index.html")
        
        # Clean path for safe joining
        safe_suffix = path.lstrip('/')
        
        # Whitelist and safe-path check
        if path.startswith('/assets/'):
            if self.is_safe_path(self.dist_dir, safe_suffix):
                return os.path.join(self.dist_dir, safe_suffix)
        
        elif path == '/results.json' or path.startswith('/reports/'):
            if self.is_safe_path(self.results_dir, safe_suffix):
                return os.path.join(self.results_dir, safe_suffix)
            
        # Block everything else (including traversal attempts that were normalized by the browser/client)
        # We return a non-existent path inside dist_dir to force a 404 Not Found
        logger.warning("Blocked unauthorized or unsafe path access: %s", path)
        return os.path.join(self.dist_dir, "404_not_found_by_security_policy")

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

    # Use a partial to inject directories into the handler
    handler = lambda *args, **kwargs: ReportHandler(
        *args, 
        dist_dir=dist_dir, 
        results_dir=results_dir, 
        **kwargs
    )
    
    # Use a socket server that allows address reuse and binds to localhost only
    socketserver.TCPServer.allow_reuse_address = True
    server_address = ("127.0.0.1", port)
    
    try:
        with socketserver.TCPServer(server_address, handler) as httpd:
            logger.info("Krkn-AI Dashboard serving at http://127.0.0.1:%d", port)
            logger.info("Press Ctrl+C to stop.")
            
            # Start httpd in a background thread
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()

            # Open the browser if not headless
            if not headless and os.getenv("KRKN_AI_HEADLESS") != "true":
                webbrowser.open(f"http://127.0.0.1:{port}")

            # Wait for keyboard interrupt
            try:
                while server_thread.is_alive():
                    server_thread.join(timeout=0.5)
            except KeyboardInterrupt:
                logger.info("Interrupt received, shutting down report server...")
                httpd.shutdown()
                server_thread.join()
                logger.info("Server shutdown complete.")
    except Exception as e:
        logger.error("Failed to start or run server: %s", e)
