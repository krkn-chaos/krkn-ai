"""
Krkn-AI Dashboard Report Server

SECURITY DESIGN:
This server is designed EXCLUSIVELY for localhost usage (127.0.0.1).
It should NEVER be exposed to external networks or the internet.

Authentication: HttpOnly, SameSite=Strict cookies
- HttpOnly prevents JavaScript access (XSS protection)
- SameSite=Strict prevents CSRF attacks  
- Secure flag intentionally omitted for HTTP localhost compatibility

The server binds only to 127.0.0.1, ensuring it cannot be accessed
from external networks. If localhost-only restriction is ever removed,
HTTPS must be implemented and the Secure cookie flag must be added.
"""
import os
import http.server
import socketserver
import threading
import webbrowser
import secrets
from http.cookies import SimpleCookie
from urllib.parse import unquote, urlparse
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

    def do_GET(self):
        """Override GET to set auth cookie on first access.
        
        Security Note: This server is designed for localhost-only usage (127.0.0.1).
        The cookie uses HttpOnly and SameSite=Strict for security, but intentionally
        omits the Secure flag because:
        1. This server binds only to 127.0.0.1 (localhost)
        2. Localhost connections use HTTP, not HTTPS
        3. Adding Secure flag would break functionality on HTTP
        4. Localhost is inherently isolated from network attacks
        
        If this server is ever exposed beyond localhost (NOT RECOMMENDED), 
        implement HTTPS and add the Secure flag.
        """
        # Only set cookie and redirect on root navigation (not asset requests)
        if not self.validate_token():
            # Only redirect on root path to avoid extra round-trips for assets
            if self.path == '/' or self.path.startswith('/?'):
                # Use HTTP 302 redirect for root navigation
                self.send_response(302)  # Temporary redirect
                self.send_header('Location', '/')
                # HttpOnly: Prevents JavaScript access (XSS protection)
                # SameSite=Strict: Prevents CSRF attacks
                # Secure flag intentionally omitted for HTTP localhost (see docstring)
                self.send_header('Set-Cookie', f'krkn_token={self.security_token}; HttpOnly; SameSite=Strict; Path=/')
                self.end_headers()
                return
            else:
                # For non-root paths without cookie, return 401
                self.send_error(401, "Authentication required. Please visit the root page first.")
                return
        
        # Proceed with normal GET handling
        super().do_GET()
    
    def validate_token(self):
        """Validate security token from cookie."""
        cookie_header = self.headers.get('Cookie')
        if not cookie_header:
            return False
        
        cookies = SimpleCookie()
        cookies.load(cookie_header)
        
        token_cookie = cookies.get('krkn_token')
        if not token_cookie:
            return False
        
        return token_cookie.value == self.security_token
    
    def translate_path(self, path):
        # 1. Parse path
        parsed = urlparse(path)
        
        # 2. For data endpoints (/results.json, /reports/*), require valid cookie
        if parsed.path.startswith('/results.json') or parsed.path.startswith('/reports/'):
            if not self.validate_token():
                logger.warning("Blocked request without valid auth cookie: %s", parsed.path)
                return os.path.join(self.dist_dir, "404_not_found_by_security_policy")
        
        # 3. URL-decode to catch encoded traversal attempts (%2e%2e, %2f, etc.)
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
        
        # 7. Check Extension Allowlist (or serve index.html for SPA routes)
        _, ext = os.path.splitext(normalized_path)
        if ext and ext.lower() not in self.ALLOWED_EXTENSIONS:
            # Has extension but not in allowlist → block
            logger.warning("Blocked request with unsafe extension: %s", normalized_path)
            return os.path.join(self.dist_dir, "404_not_found_by_security_policy")
        elif not ext:
            # No extension → likely a client-side route (e.g., /dashboard, /settings)
            # Serve index.html and let the SPA handle routing
            # But still protect data endpoints
            if normalized_path.startswith('/reports/'):
                # This is a data endpoint, not a client route
                pass  # Continue to normal validation
            else:
                # Client-side route → serve index.html
                return os.path.join(self.dist_dir, "index.html")
        
        # 8. For /reports/, enforce strict filename allowlist
        if normalized_path.startswith('/reports/'):
            filename = os.path.basename(normalized_path)
            if filename not in self.ALLOWED_REPORT_FILES:
                logger.warning("Blocked request for non-allowlisted report file: %s", filename)
                return os.path.join(self.dist_dir, "404_not_found_by_security_policy")

        # 9. Clean path for safe joining
        safe_suffix = normalized_path.lstrip('/')
        
        # 10. Whitelist and safe-path check with realpath validation
        # Data endpoints (require authentication)
        if normalized_path == '/results.json' or normalized_path.startswith('/reports/'):
            if self.is_safe_path(self.results_dir, safe_suffix):
                return os.path.join(self.results_dir, safe_suffix)
        
        # Static files from dist_dir (after extension allowlist check)
        # This includes /assets/*, /vite.svg, /favicon.ico, etc.
        elif self.is_safe_path(self.dist_dir, safe_suffix):
            return os.path.join(self.dist_dir, safe_suffix)
            
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
    
    # Initialize httpd before try block for exception safety
    httpd = None
    try:
        httpd = ThreadedTCPServer(server_address, handler)
        
        # Log server start (no token display - it's in secure cookies now)
        logger.info("=" * 60)
        logger.info("Krkn-AI Dashboard Server Started")
        logger.info("=" * 60)
        logger.info("Server: http://127.0.0.1:%d", port)
        logger.info("Authentication: Secure HttpOnly cookie (auto-set on first access)")
        logger.info("=" * 60)
        
        # Open browser with clean URL (no token in query string)
        if not headless:
            url = f"http://127.0.0.1:{port}"
            print("\n" + "=" * 60)
            print("🔗 Dashboard URL:")
            print(f"   {url}")
            print("=" * 60 + "\n")
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        
        logger.info("Server is running. Press Ctrl+C to stop.")
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down server...")
        if httpd:
            httpd.shutdown()
    except OSError as e:
        logger.error("Failed to start server: %s", e)
        if httpd:
            httpd.shutdown()
