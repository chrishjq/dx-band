# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Small local-network HTTP/SSE server for the browser musician display."""

from __future__ import annotations

import ipaddress
import json
import queue
import socket
import threading
from collections.abc import Callable
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dxband.analysis.chord_notation import valid_display_mode
from dxband.resource_paths import RESOURCE_ROOT, WEB_MUSICIAN_ROOT


class _LocalHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        owner: WebMusicianServer,
    ) -> None:
        super().__init__(server_address, handler)
        self.owner = owner


class _RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Browsers commonly reset persistent connections when the page is
            # refreshed, closed or moved between networks. This is a normal
            # client disconnect and should not produce a server traceback.
            self.close_connection = True

    @property
    def owner(self) -> WebMusicianServer:
        server = self.server
        if not isinstance(server, _LocalHttpServer):
            raise RuntimeError("网页乐手屏服务类型无效")
        return server.owner

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_bytes(b"ok", "text/plain; charset=utf-8")
            return
        if parsed.path == "/logo.png":
            self._send_bytes(self.owner.logo_bytes, "image/png")
            return
        if parsed.path == "/jianpurender.js":
            self._send_bytes(self.owner.jianpurender_bytes, "text/javascript; charset=utf-8")
            return
        if parsed.path == "/":
            self._send_bytes(self.owner.page_bytes, "text/html; charset=utf-8")
            return
        if parsed.path == "/events":
            self._stream_events()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/local-mode":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self._is_local_display(parsed.query) or not self._same_local_origin():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 128:
                raise ValueError("invalid body length")
            payload = json.loads(self.rfile.read(length))
            mode = payload.get("mode") if isinstance(payload, dict) else None
        except (ValueError, TypeError, UnicodeDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(mode, str) or not valid_display_mode(mode):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        callback = self.owner.on_local_chord_mode
        if callback is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        callback(mode)
        self._send_bytes(b"ok", "text/plain; charset=utf-8")

    def _is_local_display(self, query: str) -> bool:
        return (
            parse_qs(query).get("local", [""])[0] == "1"
            and ipaddress.ip_address(self.client_address[0]).is_loopback
        )

    def _same_local_origin(self) -> bool:
        expected = f"127.0.0.1:{self.owner.port}"
        origin = self.headers.get("Origin")
        return self.headers.get("Host") == expected and (
            origin is None or origin == f"http://{expected}"
        )

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self) -> None:
        self.close_connection = True
        local_display = self._is_local_display(urlparse(self.path).query)
        subscriber = self.owner.subscribe(local=local_display)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(self.owner.snapshot_event())
            self.wfile.flush()
            while self.owner.running:
                try:
                    event = subscriber.get(timeout=12)
                except queue.Empty:
                    event = b": keep-alive\n\n"
                self.wfile.write(event)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.owner.unsubscribe(subscriber)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class WebMusicianServer:
    """Serve the musician view; accept settings changes only from loopback."""

    def __init__(self, page_path: Path | None = None, *, language: str = "zh") -> None:
        self._page_path = page_path or WEB_MUSICIAN_ROOT / "index.html"
        self.page_bytes = self._page_path.read_bytes()
        self.jianpurender_bytes = (
            WEB_MUSICIAN_ROOT / "vendor" / "jianpurender" / "jianpurender.js"
        ).read_bytes()
        self.logo_bytes = (RESOURCE_ROOT / "dx_band_sidebar_logo.png").read_bytes()
        self._server: _LocalHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._subscribers: set[queue.Queue[bytes]] = set()
        self.on_local_chord_mode: Callable[[str], None] | None = None
        self._state: dict[str, object] = {
            "protocol": 1,
            "language": language if language in {"zh", "en"} else "zh",
            "song": None,
            "display": {
                "chord_mode": "degree",
                "offset_ms": 0,
            },
            "guide": {"remaining": 0, "total": 0},
            "transport": {"state": "empty", "position_ms": 0},
        }

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int | None:
        server = self._server
        return int(server.server_port) if server is not None else None

    @property
    def url(self) -> str | None:
        port = self.port
        if port is None:
            return None
        return f"http://{_preferred_lan_address()}:{port}/"

    @property
    def local_url(self) -> str | None:
        port = self.port
        if port is None:
            return None
        return f"http://127.0.0.1:{port}/?local=1"

    def start(self, preferred_port: int = 8765) -> str:
        if self._server is not None:
            url = self.url
            if url is None:
                raise RuntimeError("网页乐手屏服务地址不可用")
            return url
        server = _LocalHttpServer(("0.0.0.0", preferred_port), _RequestHandler, self)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="web-musician-server",
            daemon=True,
        )
        self._thread.start()
        url = self.url
        if url is None:
            self.stop()
            raise RuntimeError("网页乐手屏服务启动失败")
        return url

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
        with self._lock:
            self._subscribers.clear()

    def set_song(self, song: dict[str, object] | None) -> None:
        self._set_and_publish("song", song)

    def set_language(self, language: str) -> None:
        normalized = language if language in {"zh", "en"} else "zh"
        with self._lock:
            self._state["language"] = normalized
            snapshot = json.loads(json.dumps(self._state, ensure_ascii=False))
        self.publish("snapshot", snapshot)

    def set_display(self, *, chord_mode: str, offset_ms: int) -> None:
        self._set_and_publish(
            "display",
            {
                "chord_mode": chord_mode,
                "offset_ms": offset_ms,
            },
        )

    def set_transport(self, *, state: str, position_ms: int) -> None:
        self._set_and_publish(
            "transport",
            {"state": state, "position_ms": max(0, int(position_ms))},
        )

    def set_guide_countdown(self, remaining: int, total: int) -> None:
        normalized_total = max(0, int(total))
        normalized_remaining = min(max(0, int(remaining)), normalized_total)
        self._set_and_publish(
            "guide",
            {"remaining": normalized_remaining, "total": normalized_total},
        )

    def _set_and_publish(self, key: str, value: object) -> None:
        with self._lock:
            self._state[key] = value
        self.publish(key, value)

    def publish(self, event_name: str, value: object) -> None:
        event = _encode_event(event_name, value)
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                with suppress(queue.Empty):
                    subscriber.get_nowait()
                with suppress(queue.Full):
                    subscriber.put_nowait(event)

    def snapshot_event(self) -> bytes:
        with self._lock:
            snapshot = json.loads(json.dumps(self._state, ensure_ascii=False))
        return _encode_event("snapshot", snapshot)

    def subscribe(self, *, local: bool = False) -> queue.Queue[bytes]:
        subscriber: queue.Queue[bytes] = queue.Queue(maxsize=4)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[bytes]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)


def _encode_event(event_name: str, value: object) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {payload}\n\n".encode()


def _preferred_lan_address() -> str:
    """Resolve the address the OS would use on the current local network.

    Hostname lookup can return every adapter address, including VPN/tunnel
    interfaces such as Wintun ``172.16–31.*``. Prefer the UDP route probe:
    it reflects the outbound interface the OS would actually use, which is
    what phones on the same Wi-Fi can usually reach.
    """
    candidates: list[str] = []
    hostnames = (socket.gethostname(), f"{socket.gethostname().split('.')[0]}.local")
    for hostname in hostnames:
        with suppress(OSError):
            candidates.extend(socket.gethostbyname_ex(hostname)[2])

    probed: str | None = None
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 192.0.2.0/24 is TEST-NET-1; connect() does not send packets.
        probe.connect(("192.0.2.1", 9))
        address = str(probe.getsockname()[0])
        if address:
            probed = address
            candidates.append(address)
    except OSError:
        pass
    finally:
        probe.close()

    def rank(value: str) -> tuple[int, str]:
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            return (9, value)
        if parsed.is_loopback:
            return (8, value)
        # Outbound route wins over alphabetical ties among RFC1918 ranges.
        if probed is not None and value == probed:
            return (-1, value)
        if value.startswith("192.168.") or value.startswith("10."):
            return (0, value)
        first, second, *_rest = (int(part) for part in value.split("."))
        if first == 172 and 16 <= second <= 31:
            return (0, value)
        if parsed.is_link_local:
            return (3, value)
        return (2, value)

    usable = sorted(set(candidates), key=rank)
    return usable[0] if usable and rank(usable[0])[0] < 8 else "127.0.0.1"
