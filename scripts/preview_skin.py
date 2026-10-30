"""Serve the CyberScan skin as static files, without importing any FRAME service.

The preview has no API routes, device libraries or scanner host. Connections made
by the page are denied by CSP; local assets and user-selected blob images remain.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'apps' / 'web' / 'dist'


class PreviewHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'none'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; worker-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def do_GET(self):
        # Every navigation on this server enters the safe UI, never the legacy
        # app that requests /api/state. No query can enable acquisition here.
        requested = urlsplit(self.path)
        if requested.path in ('/', '/index.html') and parse_qs(requested.query).get('workspace') != ['cyberscan']:
            self.send_response(302)
            self.send_header('Location', '/?workspace=cyberscan')
            self.end_headers()
            return
        if self.path.split('?', 1)[0] in ('/api', '/media', '/sw.js') or self.path.startswith(('/api/', '/media/')):
            self.send_error(404, 'Static UI preview only')
            return
        super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    if not (DIST / 'index.html').is_file():
        raise SystemExit('Build the client first with npm run build')
    handler = partial(PreviewHandler, directory=str(DIST))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    print(f'CyberScan X UI preview: http://127.0.0.1:{args.port}/?workspace=cyberscan', flush=True)
    print('Static files only. No scanner service, discovery, API or device access.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
