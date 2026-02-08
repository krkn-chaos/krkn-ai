import os
import http.server
import socketserver
import threading
import webbrowser
from urllib.parse import unquote
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

class ReportHandler(http.server.SimpleHTTPRequestHandler):
    ALLOWED_EXTENSIONS = {
        '.html', '.css', '.js', '.json', '.csv',
        '.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico',
        '.woff', '.woff2', '.ttf'
    }
    """
    Custom handler to serve both the static dashboard and the results data.
    """
    def __init__(self, *args, dist_dir=None, results_dir=None, **kwargs):
        self.dist_dir = dist_dir
        self.results_dir = results_dir
        super().__init__(*args, **kwargs)

    def is_safe_path(self, base_dir, path):
        """Check if path is resolved within base_dir using realpath to prevent symlink traversal."""
        # Resolve real paths to handle symlinks
        abs_base = os.path.realpath(os.path.abspath(base_dir))
        target_path = os.path.realpath(os.path.abspath(os.path.join(abs_base, path.lstrip('/'))))
        
        # commonpath returns the common sub-path which must be exactly abs_base
        try:
            return os.path.commonpath([abs_base, target_path]) == abs_base
        except ValueError:
            return False

    def translate_path(self, path):
        # 1. URL-decode to catch encoded traversal attempts (%2e%2e, %2f, etc.)
        path = unquote(path)
        
        # 2. Strip query strings and fragments
        path = path.split('?', 1)[0].split('#', 1)[0]
        
        # 3. Normalize Windows separators to Unix (\ -> /)
        path = path.replace('\\', '/')
        
        # 4. Collapse multiple slashes and resolve . and .. segments
        # This handles //, /./, /../ patterns
        parts = []
        for part in path.split('/'):
            if part == '' or part == '.':
                continue
            elif part == '..':
                # Reject any path with .. components outright
                logger.warning("Blocked path with .. traversal attempt: %s", path)
                return os.path.join(self.dist_dir, "404_not_found_by_security_policy")
            else:
                parts.append(part)
        
        # Reconstruct normalized path
        normalized_path = '/' + '/'.join(parts) if parts else '/'
        
        # 5. Default behavior for root
        if normalized_path == '/':
            return os.path.join(self.dist_dir, "index.html")
        
        # 6. Check Extension Allowlist
        _, ext = os.path.splitext(normalized_path)
        if ext.lower() not in self.ALLOWED_EXTENSIONS:
            logger.warning("Blocked request with unsafe extension: %s", normalized_path)
            return os.path.join(self.dist_dir, "404_not_found_by_security_policy")

        # 7. Clean path for safe joining
        safe_suffix = normalized_path.lstrip('/')
        
        # 8. Whitelist and safe-path check with realpath validation
        if normalized_path.startswith('/assets/'):
            if self.is_safe_path(self.dist_dir, safe_suffix):
                return os.path.join(self.dist_dir, safe_suffix)
        
        elif normalized_path == '/results.json' or normalized_path.startswith('/reports/'):
            if self.is_safe_path(self.results_dir, safe_suffix):
                return os.path.join(self.results_dir, safe_suffix)
            
        # Block everything else
        logger.warning("Blocked unauthorized or unsafe path access: %s", normalized_path)
        return os.path.join(self.dist_dir, "404_not_found_by_security_policy")

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True

def start_report_server(results_dir: str, port: int = 8080, headless: bool = False):
    # Locate the built dashboard in the package
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(base_dir, "web", "dist")

    if not os.path.exists(dist_dir):
        logger.error("Dashboard not found! Please ensure it is built in 'web/dist'")
        return

    # Check if results exist
    if not os.path.exists(os.path.join(results_dir, "results.json")):
        results_name = os.path.basename(os.path.normpath(results_dir))
        logger.warning("Warning: results.json not found in '%s'. Dashboard might be empty.", results_name or results_dir)

    # Use a partial to inject directories into the handler
    handler = lambda *args, **kwargs: ReportHandler(
        *args, 
        dist_dir=dist_dir, 
        results_dir=results_dir, 
        **kwargs
    )
    
    # Use a threaded socket server for concurrency
    ThreadedTCPServer.allow_reuse_address = True
    server_address = ("127.0.0.1", port)
    
    try:
        with ThreadedTCPServer(server_address, handler) as httpd:
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
