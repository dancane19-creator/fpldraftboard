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

Then open http://localhost:8777. The same server can also listen on your home
network (`lan=True`), which is how the phone page in mobile.py reaches it.
"""

from __future__ import annotations

import http.server
import json
import socket
import socketserver
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from functools import partial
from typing import Callable

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
    """Serves a few pages and proxies a handful of read-only endpoints.

    `pages` maps a path to HTML, `blobs` maps a path to (bytes, content-type),
    and `routes` maps a path to a zero-argument callable returning JSON bytes.
    Anything under /api/ not in `routes` is a proxy to the Draft API.
    """

    def __init__(self, *args, html: str = "", league: int = 0,
                 pages: dict[str, str] | None = None,
                 blobs: dict[str, tuple[bytes, str]] | None = None,
                 routes: dict[str, Callable[[], bytes]] | None = None,
                 **kwargs):
        self.html = html
        self.league = league
        self.pages = pages or {}
        self.blobs = blobs or {}
        self.routes = routes or {}
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
        elif path in self.pages:
            self._send(200, self.pages[path].encode("utf-8"),
                       "text/html; charset=utf-8")
        elif path in self.blobs:
            body, ctype = self.blobs[path]
            self._send(200, body, ctype)
        elif path in self.routes:
            try:
                self._send(200, self.routes[path](), "application/json")
            except Exception as exc:        # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)}).encode(),
                           "application/json")
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


def lan_ip() -> str | None:
    """The address other devices on your Wi-Fi can reach this PC at.

    Opens a UDP socket toward a public address and reads back which local
    interface the OS would use. Nothing is actually sent.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip if not ip.startswith("127.") else None
    except OSError:
        return None


def serve(html: str, league: int, port: int = 8777,
          open_browser: bool = True, lan: bool = False,
          pages: dict[str, str] | None = None,
          blobs: dict[str, tuple[bytes, str]] | None = None,
          routes: dict[str, Callable[[], bytes]] | None = None,
          open_path: str = "/", banner: str = "Live draft dashboard") -> None:
    handler = partial(Handler, html=html, league=league, pages=pages,
                      blobs=blobs, routes=routes)
    host = "0.0.0.0" if lan else "127.0.0.1"
    for attempt in range(12):
        try:
            httpd = Server((host, port + attempt), handler)
            break
        except OSError:
            continue                       # port busy, try the next one
    else:
        print(f"  Could not bind any port from {port} to {port + 11}.")
        return

    bound = httpd.server_address[1]
    url = f"http://localhost:{bound}"
    print(f"\n  {banner}: {url}{open_path}")
    ip = lan_ip() if lan else None
    phone_url = f"http://{ip}:{bound}/m" if ip else f"{url}/m"
    # Pages only learn the phone address once a port is bound, so any page
    # carrying this token is filled in here.
    if pages:
        for k, v in list(pages.items()):
            pages[k] = v.replace("__PHONE_URL__", phone_url)
    if lan:
        if ip:
            print(f"  On your phone (same Wi-Fi):  {phone_url}")
            print(f"  QR code to scan:             {url}/qr")
        else:
            print("  Could not work out this PC's Wi-Fi address. Try `ipconfig`"
                  " and use the IPv4 address with port", bound)
        print("  If Windows asks whether Python may use the network, allow it"
              " on private networks.")
    print(f"  Watching league {league}. Polls every few seconds.")
    print("  Leave this window open. Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url + open_path)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        httpd.server_close()
