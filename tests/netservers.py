"""Local HTTP servers for the tests of outgoing requests (docs/adr/0050).

Each server counts what reaches it, so a test can prove that a refused request never made a
connection, and how many connections are still open once the client says it is done.
"""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# A route answers (status, headers, body); a streaming route writes by itself.
Route = Callable[["Handler"], tuple[int, dict[str, str], bytes] | None]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server: "Server"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def setup(self) -> None:
        super().setup()
        with self.server.lock:
            self.server.connections += 1
            self.server.open_connections += 1

    def finish(self) -> None:
        try:
            super().finish()
        except OSError:
            pass
        finally:
            with self.server.lock:
                self.server.open_connections -= 1

    def do_GET(self) -> None:
        with self.server.lock:
            self.server.requests.append(self.path)
        route = self.server.routes.get(self.path.split("?", 1)[0])
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        try:
            answer = route(self)
        except OSError:
            return  # the client went away
        if answer is None:
            return
        status, headers, body = answer
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        super().__init__((host, port), Handler)
        self.routes: dict[str, Route] = {}
        self.requests: list[str] = []
        self.connections = 0
        self.open_connections = 0
        self.bytes_sent = 0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def hits(self) -> int:
        return len(self.requests)

    def url(self, path: str = "/", host: str | None = None) -> str:
        return f"http://{host or self.server_address[0]}:{self.port}{path}"

    def serve(self, path: str, status: int, body: bytes, content_type: str = "text/html") -> None:
        self.routes[path] = lambda handler: (status, {"Content-Type": content_type}, body)

    def redirect(self, path: str, target: str, status: int = 302) -> None:
        self.routes[path] = lambda handler: (status, {"Location": target}, b"")

    def wait_idle(self, seconds: float = 3.0) -> bool:
        """True once no connection of this server is open any more."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.open_connections == 0:
                return True
            time.sleep(0.02)
        return self.open_connections == 0


@contextmanager
def serving(host: str = "127.0.0.1", port: int = 0) -> Iterator[Server]:
    server = Server(host, port)
    server.thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        server.thread.join(timeout=5)


def trickle(handler: Handler, *, headers_first: bool = False, pause: float = 0.05) -> None:
    """Answer one byte at a time, for ever: the body, or the header block itself."""
    wfile = handler.wfile
    if headers_first:
        wfile.write(b"HTTP/1.0 200 OK\r\n")
        wfile.flush()
        while True:  # a header line that never ends
            wfile.write(b"X")
            wfile.flush()
            handler.server.bytes_sent += 1
            time.sleep(pause)
    wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
    wfile.flush()
    while True:
        wfile.write(b" ")
        wfile.flush()
        handler.server.bytes_sent += 1
        time.sleep(pause)


def endless(handler: Handler, *, declared: int | None = None) -> None:
    """A body of many megabytes, until the client hangs up."""
    wfile = handler.wfile
    head = b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n"
    if declared is not None:
        head += f"Content-Length: {declared}\r\n".encode()
    wfile.write(head + b"\r\n")
    chunk = b"<!-- " + b"x" * 8000 + b" -->\n"
    for _ in range(5000):  # 40 MB at most
        wfile.write(chunk)
        handler.server.bytes_sent += len(chunk)


def open_sockets() -> int:
    """File descriptors of this process that are sockets."""
    import os

    count = 0
    for name in os.listdir("/proc/self/fd"):
        try:
            if os.readlink(f"/proc/self/fd/{name}").startswith("socket:"):
                count += 1
        except OSError:
            continue
    return count


def can_bind(host: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
    except OSError:
        return False
    return True


class AnyPort:
    """A port rule for the tests: local servers listen on whatever port the system gave."""

    def __contains__(self, port: object) -> bool:
        return True
