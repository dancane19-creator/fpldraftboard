"""Serve the dashboard from localhost, with a proxy to the Draft API.

Why a server at all, when the board was a single file that worked offline?

Because a page opened from `file://` has a null origin, and a browser will not
let it fetch draft.premierleague.com unless that API sends permissive CORS
headers. It may or may not. Rather than depend on that, this serves the page
from http://localhost and forwards /api/* to the real API from Python, where
CORS does not exist. The page then polls its own origin, which is always
allowed.

Everything else follows from that. Once the page can poll, the draft tracks
itself: no typing names, no marking picks. It reads your league's own record
every few seconds and updates.

    py draft.py serve --league 721 --entry 2438

Then open http://localhost:8777. The dashboard is generated fresh on each page
load, so projections stay current with whatever `fetch` last cached.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from functools import partial

DRAFT_BASE = "https://draft.premierleague.com/api"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
}


class _Cache:
    """Small TTL cache so ten browser tabs don't become ten API calls a second."""

    def __init__(self, ttl: float = 2.0):
        self.ttl = ttl
        self._d: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._d.get(key)
        if hit and (time.time() - hit[0]) < self.ttl:
            return hit[1]
        return None

    def put(self, key: str, val: bytes):
        with self._lock:
            self._d[key] = (time.time(), val)


CACHE = _Cache()


class Handler(http.server.BaseHTTPRequestHandler):
    """Serves one page and proxies a handful of read-only endpoints."""

    def __init__(self, *args, html: str = "", league: int = 0, **kwargs):
        self.html = html
        self.league = league
        super().__init__(*args, **kwargs)

    # Quieten the default per-request logging; polling would flood the console.
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass          # browser navigated away mid-response

    def _proxy(self, path: str):
        cached = CACHE.get(path)
        if cached is not None:
            self._send(200, cached, "application/json")
            return
        url = f"{DRAFT_BASE}/{path}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
            CACHE.put(path, body)
            self._send(200, body, "application/json")
        except urllib.error.HTTPError as exc:
            self._send(exc.code, json.dumps(
                {"error": f"upstream {exc.code}", "url": url}).encode(),
                "application/json")
        except Exception as exc:
            # Network blips are expected during a long draft; the page retries.
            self._send(502, json.dumps(
                {"error": str(exc), "url": url}).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, self.html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/choices":
            self._proxy(f"draft/{self.league}/choices")
        elif path == "/api/league":
            self._proxy(f"league/{self.league}/details")
        elif path == "/api/game":
            self._proxy("game")
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        elif path == "/api/ping":
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(html: str, league: int, port: int = 8777,
          open_browser: bool = True) -> None:
    handler = partial(Handler, html=html, league=league)
    for attempt in range(12):
        try:
            httpd = Server(("127.0.0.1", port + attempt), handler)
            break
        except OSError:
            continue                       # port busy, try the next one
    else:
        print(f"  Could not bind any port from {port} to {port + 11}.")
        return

    url = f"http://localhost:{httpd.server_address[1]}"
    print(f"\n  Live draft dashboard: {url}")
    print(f"  Watching league {league}. Polls every few seconds.")
    print("  Leave this window open for the whole draft. Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        httpd.server_close()
