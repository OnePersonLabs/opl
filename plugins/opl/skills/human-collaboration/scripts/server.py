"""Small authenticated, local-first reader/reply service. No model runs here."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from inbox import Conflict, Inbox, InboxError, MAX_TEXT, label, now, text
from catalog import Catalog

WEB = Path(__file__).resolve().parent.parent / "web"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}


def notify(inbox: Inbox, submission: str, *, retry: bool = False, thread: str | None = None) -> dict:
    """At-most-one automatic attempt. Acceptance is not delivery or integration."""
    with inbox.transaction() as db:
        row = db.execute("SELECT * FROM submissions WHERE id=?", (submission,)).fetchone()
        if not row:
            raise InboxError("unknown submission")
        receipt = dict(row)
        item = inbox._item(db, receipt["item"])
        if thread is not None:
            inbox.owner(db, thread, item)
        previous = json.loads(receipt["queue"])
        if receipt["state"] == "resolved" or (previous["state"] != "not_requested" and not retry):
            return previous
        thread = item["owner_thread"]
        attempt = {"state": "attempting", "at": now(), "thread": thread}
        db.execute("UPDATE submissions SET queue=? WHERE id=?", (json.dumps(attempt), submission))
    message = (f"Human contribution {label(receipt['item'])}/{submission} is saved in "
               f"{json.dumps(str(inbox.root))}. Use $opl:human-collaboration to inspect and claim it. "
               "Preserve its reviewed revision. Reconcile already-claimed effects; do not replay them.")
    try:
        # Reuse OPL's existing Windows/POSIX executable resolution, not a new
        # guessed shell protocol. No human reply text enters the command line.
        helper = Path(__file__).resolve().parents[2] / "long-command-wakeup" / "scripts"
        sys.path.insert(0, str(helper)) if str(helper) not in sys.path else None
        from run_and_wake import subprocess_argv
        result = subprocess.run(subprocess_argv([os.environ.get("CODEX_BIN", "codex"), "queue", "--thread", thread, "--message", message]),
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=15, check=False)
        status = {"state": "accepted" if result.returncode == 0 else "failed", "at": now(),
                  "thread": thread, "exit_code": result.returncode,
                  "detail": (result.stderr or result.stdout)[-2000:]}
    except subprocess.TimeoutExpired:
        status = {"state": "unknown", "at": now(), "thread": thread,
                  "detail": "queue timed out; delivery may have occurred. Inspect before an explicit retry."}
    except (OSError, ImportError) as error:
        status = {"state": "failed", "at": now(), "thread": thread, "detail": str(error)}
    with inbox.transaction() as db:
        db.execute("UPDATE submissions SET queue=? WHERE id=?", (json.dumps(status), submission))
        inbox._event(db, receipt["item"], "notification", {"submission": submission, **status})
    return status


class HumanServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def __init__(self, inbox: Inbox, host: str, port: int, *, token: str | None = None, wake: bool = False, catalog: Catalog | None = None):
        address = ipaddress.ip_address(host)
        if address.version == 6:
            self.address_family = socket.AF_INET6
        self.inbox = inbox
        self.catalog = catalog or Catalog(inboxes=[inbox])
        self.token = token or secrets.token_urlsafe(32)
        if len(self.token) < 32:
            raise InboxError("authentication tokens must contain at least 32 characters")
        self.wake = wake
        self.notifier = ThreadPoolExecutor(max_workers=1, thread_name_prefix="human-inbox-wake")
        super().__init__((host, port), HumanHandler)

    def server_bind(self) -> None:
        if os.name == "nt":
            # Windows SO_REUSEADDR can share an active listener's address.
            # Exclusive ownership is a socket bind property, not a startup lock.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def server_close(self) -> None:
        super().server_close()
        self.notifier.shutdown(wait=True, cancel_futures=True)


class HumanHandler(BaseHTTPRequestHandler):
    server: HumanServer
    server_version = "OPLHuman/1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, format: str, *args: object) -> None:
        # Never log credentials, request bodies, source paths, or URL queries.
        return

    def respond(self, status: int, body: bytes, mime: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # The committed submission remains durable after disconnection.

    def json(self, status: int, value: object) -> None:
        self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def authenticate(self) -> None:
        host = self.headers.get("Host", "")
        parsed = urlsplit("http://" + host)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise InboxError("invalid Host header")
        if parsed.port != self.server.server_address[1]:
            raise InboxError("unexpected Host port")
        if parsed.hostname != "localhost":
            try:
                ipaddress.ip_address(parsed.hostname or "")
            except ValueError as error:
                raise InboxError("use a literal device IP or localhost") from error
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            raise PermissionError("cross-origin requests are not allowed")
        if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token):
            raise PermissionError("pair this browser using the server's link or token")

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/favicon.ico":
            self.respond(204, b"", "image/x-icon")
            return
        if parsed.path in STATIC:
            name, mime = STATIC[parsed.path]
            self.respond(200, (WEB / name).read_bytes(), mime)
            return
        try:
            self.authenticate()
            query = parse_qs(parsed.query)
            if parsed.path == "/api/inbox":
                self.json(200, self.server.catalog.snapshot())
            elif parsed.path == "/api/service":
                self.json(200, {"catalog_id": self.server.catalog.id, "wake_root": self.server.wake})
            elif parsed.path == "/api/item":
                item = query.get("id", [""])[0]
                rev = int(query["revision"][0]) if "revision" in query else None
                inbox = self.server.catalog.resolve(query.get("workspace", [None])[0])
                self.json(200, inbox.get(item, rev))
            elif parsed.path == "/api/source":
                item = query.get("id", [""])[0]
                rev = int(query.get("revision", ["0"])[0])
                index = int(query.get("index", ["-1"])[0])
                inbox = self.server.catalog.resolve(query.get("workspace", [None])[0])
                content, mime = inbox.source(item, rev, index, live=query.get("live") == ["1"])
                # SVG is only embedded as an image by the client. This response
                # cannot execute scripts when navigated directly either (CSP).
                self.respond(200, content, mime)
            else:
                self.json(404, {"error": "unknown route"})
        except PermissionError as error:
            self.json(401, {"error": str(error)})
        except Conflict as error:
            self.json(409, {"error": str(error)})
        except (InboxError, ValueError, UnicodeError, OSError, sqlite3.Error) as error:
            self.json(400, {"error": str(error)})

    def do_POST(self) -> None:
        try:
            self.authenticate()
            if self.headers.get("Transfer-Encoding"):
                raise InboxError("chunked bodies are not accepted")
            if self.headers.get_content_type() != "application/json":
                raise InboxError("send application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_TEXT * 2:
                raise InboxError("invalid request size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise InboxError("incomplete request body")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise InboxError("request must be an object")
            path = urlsplit(self.path).path
            if path == "/api/contribute":
                inbox, thread = self.server.catalog.resolve_session(data.get("session"))
            else:
                inbox = self.server.catalog.resolve(data.get("workspace"))
            if path == "/api/draft":
                result = inbox.save_draft(data.get("id", ""), data.get("revision"), data.get("body"), data.get("expected"), data.get("answers"))
            elif path in {"/api/submit", "/api/contribute"}:
                if path == "/api/contribute":
                    result = inbox.contribute(data.get("title"), data.get("body"), data.get("request_id"), thread)
                else:
                    result = inbox.submit(data.get("id", ""), data.get("revision"), data.get("body"), data.get("request_id"), kind=data.get("kind", "feedback"), answers=data.get("answers"))
                item = inbox.get(result["item"])
                result.update({key: item[key] for key in ("workspace_id", "session", "session_title")})
                self.json(200, result)
                if self.server.wake:
                    self.server.notifier.submit(notify, inbox, result["id"])
                return
            elif path == "/api/action":
                if data.get("action") not in {"start", "later", "ready"}:
                    raise InboxError("the phone interface cannot perform root-owned operations")
                result = inbox.move(data.get("id", ""), data["action"], data.get("reason", ""))
            else:
                self.json(404, {"error": "unknown route"})
                return
            self.json(200, result)
        except PermissionError as error:
            self.json(401, {"error": str(error)})
        except Conflict as error:
            self.json(409, {"error": str(error)})
        except (InboxError, ValueError, TypeError, UnicodeError, OSError, sqlite3.Error) as error:
            self.json(400, {"error": str(error)})
