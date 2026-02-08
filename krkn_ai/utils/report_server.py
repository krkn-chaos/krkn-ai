import os
import http.server
import socketserver
import threading
import webbrowser
import secrets
from urllib.parse import unquote, parse_qs, urlparse
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

class ReportHandler(http.server.SimpleHTTPRequestHandler):
    ALLOWED_EXTENSIONS = {
        '.html', '.css', '.js', '.json', '.csv',
        '.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico',
        '.woff', '.woff2', '.ttf'
    }
    
    # Strict allowlist for /reports/ directory (only known result files)
    ALLOWED_REPORT_FILES = {'all.csv', 'summary.csv'}
    
    """
    Custom handler to serve both the static dashboard and the results data.
    """
    def __init__(self, *args, dist_dir=None, results_dir=None, security_token=None, **kwargs):
        self.dist_dir = dist_dir
        self.results_dir = results_dir
        self.security_token = security_token
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
        # 1. Extract and validate security token from query string
        parsed = urlparse(path)
        query_params = parse_qs(parsed.query)
        
        # For data endpoints (/results.json, /reports/*), require security token
        if parsed.path.startswith('/results.json') or parsed.path.startswith('/reports/'):
            provided_token = query_params.get('token', [None])[0]
            if provided_token != self.security_token:
                logger.warning("Blocked request without valid security token: %s", parsed.path)
                return os.path.join(self.dist_dir, "404_not_found_by_security_policy")
        
        # 2. URL-decode to catch encoded traversal attempts (%2e%2e, %2f, etc.)
        path = unquote(parsed.path)
        
        # 3. Strip fragments (query already handled)
        path = path.split('#', 1)[0]
        
        # 4. Normalize Windows separators to Unix (\ -> /)
        path = path.replace('\\', '/')
        
        # 5. Collapse multiple slashes and resolve . and .. segments
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
        
        # 6. Default behavior for root
        if normalized_path == '/':
            return os.path.join(self.dist_dir, "index.html")
        
        # 7. Check Extension Allowlist
        _, ext = os.path.splitext(normalized_path)
        if ext.lower() not in self.ALLOWED_EXTENSIONS:
            logger.warning("Blocked request with unsafe extension: %s", normalized_path)
            return os.path.join(self.dist_dir, "404_not_found_by_security_policy")
        
        # 8. For /reports/, enforce strict filename allowlist
        if normalized_path.startswith('/reports/'):
            filename = os.path.basename(normalized_path)
            if filename not in self.ALLOWED_REPORT_FILES:
                logger.warning("Blocked request for non-allowlisted report file: %s", filename)
                return os.path.join(self.dist_dir, "404_not_found_by_security_policy")

        # 9. Clean path for safe joining
        safe_suffix = normalized_path.lstrip('/')
        
        # 10. Whitelist and safe-path check with realpath validation
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

    # Generate a random security token to prevent localhost abuse
    security_token = secrets.token_urlsafe(32)
    
    # Use a partial to inject directories and token into the handler
    handler = lambda *args, **kwargs: ReportHandler(
        *args, 
        dist_dir=dist_dir, 
        results_dir=results_dir,
        security_token=security_token,
        **kwargs
    )
    
    # Use a threaded socket server for concurrency
    ThreadedTCPServer.allow_reuse_address = True
    server_address = ("127.0.0.1", port)
    
    try:
        httpd = ThreadedTCPServer(server_address, handler)
        
        # Truncate token for logging (avoid exposing in CI logs/log aggregation)
        token_preview = security_token[:8] + "..." if len(security_token) > 8 else security_token
        
        # Log server start with truncated token
        logger.info("=" * 60)
        logger.info("Krkn-AI Dashboard Server Started")
        logger.info("=" * 60)
        logger.info("Server: http://127.0.0.1:%d", port)
        logger.info("Security Token: %s (truncated for security)", token_preview)
        logger.info("IMPORTANT: Token required for data endpoint access.")
        logger.info("=" * 60)
        
        # Print full URL to stdout ONLY in interactive sessions (not headless)
        if not headless:
            url = f"http://127.0.0.1:{port}/?token={security_token}"
            print("\n" + "=" * 60)
            print("🔗 Dashboard URL (copy to browser if not auto-opened):")
            print(f"   {url}")
            print("=" * 60 + "\n")
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        
        logger.info("Server is running. Press Ctrl+C to stop.")
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\\nShutting down server...")
        httpd.shutdown()
    except OSError as e:
        logger.error("Failed to start server: %s", e)
