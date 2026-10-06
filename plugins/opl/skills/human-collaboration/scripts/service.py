"""Start or reuse one ready local service at the requested fixed address."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

from catalog import Catalog
from inbox import Inbox, InboxError, atomic_write


def validate_address(host: str, port: int, allow_lan: bool) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(host)
    if not address.is_loopback and not allow_lan:
        raise InboxError("non-loopback binding requires --allow-lan; use a trusted LAN or VPN, not public HTTP")
    if not 0 <= port <= 65535:
        raise InboxError("port must be between 0 and 65535")
    return address


def connection_links(host: str, port: int, token: str, guid: str) -> dict:
    """Report reachable literal URLs; a loopback listener has no phone link."""
    address = ipaddress.ip_address(host)
    reachable = ("::1" if address.version == 6 else "127.0.0.1") if address.is_unspecified else host
    display = f"[{reachable}]" if address.version == 6 else reachable
    url = f"http://{display}:{port}/?guid={guid}#token={token}"
    lan = not address.is_loopback and not address.is_unspecified
    return {"url": url, "lan_ip": host if lan else None, "lan_url": url if lan else None,
            "access": "lan" if lan else ("local-only" if address.is_loopback else "all-interfaces")}


def receipt(server, host: str, catalog: Catalog) -> dict:
    return {**connection_links(host, server.server_address[1], server.token, server.guid),
            "catalog_id": catalog.id, "host": host, "port": server.server_address[1],
            "pid": os.getpid(), "launcher_pid": os.getppid(), "wake_root": server.wake,
            "note": "HTTP is not encrypted. Keep the pairing link private; use a trusted local network or private VPN."}


def ready(catalog: Catalog, host: str, port: int) -> dict | None:
    path = catalog.directory / "service.json"
    if not path.exists():
        return None
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("catalog_id") != catalog.id or stored.get("host") != host or stored.get("port") != port:
        return None
    probe_host = "::1" if host == "::" else ("127.0.0.1" if host == "0.0.0.0" else host)
    display = f"[{probe_host}]" if ":" in probe_host else probe_host
    link = urlsplit(stored["url"])
    token = parse_qs(link.fragment).get("token", [""])[0]
    guid = parse_qs(link.query).get("guid", [""])[0]
    if not token:
        return None
    # An older listener can still be alive after its helper is upgraded. Verify
    # that listener before allowing startup to replace the sole service receipt.
    query = "?guid=" + guid if guid else ""
    request = urllib.request.Request(f"http://{display}:{port}/api/service{query}", headers={"Authorization": "Bearer " + token})
    try:
        # Readiness and its bearer token belong to this local listener, never an
        # environment- or system-configured HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=1) as response:
            live = json.load(response)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None
    if live.get("catalog_id") != catalog.id:
        raise InboxError("the service at this address belongs to another catalog")
    if not guid:
        raise InboxError(f"a legacy service is still running at {host}:{port} without the per-start GUID check "
                         f"(recorded PID {stored.get('pid', 'unknown')}); stop that listener, then run connect again "
                         "to start the updated server in a visible terminal")
    # Existing listeners may have a receipt from an older helper. Derive current
    # link metadata from the authenticated bind without restarting that listener.
    return {**stored, **connection_links(host, port, token, guid), "reused": True}


def connect(inbox: Inbox, host: str = "127.0.0.1", port: int = 8766, *, allow_lan: bool = False,
            wake: bool = False, catalog: Catalog | None = None) -> dict:
    """The socket bind is the only startup arbitration. Never choose another port."""
    address = validate_address(host, port, allow_lan)
    if address.is_unspecified:
        raise InboxError("connect requires this device's reachable loopback, LAN, or VPN IP; use serve for a wildcard bind")
    if port == 0:
        raise InboxError("connect requires a fixed nonzero port; use serve for an ephemeral port")
    catalog = catalog or Catalog()
    catalog.register(inbox)
    stored_path = catalog.directory / "service.json"
    if stored_path.exists():
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        if stored.get("catalog_id") == catalog.id and (stored.get("host"), stored.get("port")) != (host, port):
            live = ready(catalog, stored["host"], stored["port"])
            if live:
                raise InboxError(f"the shared service is already running at {stored['host']}:{stored['port']}; connect to that address or stop it before changing the bind")
    existing = ready(catalog, host, port)
    if existing:
        if wake and not existing["wake_root"]:
            raise InboxError("the running service has wake notifications disabled; restart it with --wake-root")
        return existing
    arguments = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).with_name("human.py")),
                 "--workspace", str(inbox.workspace), "serve", "--host", host, "--port", str(port),
                 "--catalog", str(catalog.directory)]
    if allow_lan:
        arguments.append("--allow-lan")
    if wake:
        arguments.append("--wake-root")
    log = catalog.directory / "service.log"
    if log.is_symlink():
        raise InboxError("the service log must not be a symlink")
    log.touch(mode=0o600, exist_ok=True)
    log.chmod(0o600)
    if os.name == "nt":
        # An explicit console host avoids default-terminal delegation into a
        # shared Windows Terminal window. Its close event terminates the server.
        arguments.append("--console")
        conhost = Path(os.environ["SystemRoot"]) / "System32" / "conhost.exe"
        child = subprocess.Popen([str(conhost), *arguments], creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        arguments.append("--managed")
        with log.open("ab") as output:
            child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        existing = ready(catalog, host, port)
        if existing:
            if wake and not existing["wake_root"]:
                raise InboxError("the running service has wake notifications disabled; restart it with --wake-root")
            return {**existing, "reused": child.pid not in {existing["pid"], existing.get("launcher_pid")}}
        if child.poll() is not None:
            raise InboxError(f"service failed to start (exit {child.returncode}); inspect {log}")
        time.sleep(0.1)
    raise InboxError(f"service readiness was not confirmed; inspect {log} before starting it again")


def save_receipt(catalog: Catalog, value: dict) -> None:
    path = catalog.directory / "service.json"
    atomic_write(path, json.dumps(value))
    path.chmod(0o600)


def open_console() -> None:
    """Use this process's console even when the caller redirects its streams."""
    if os.name != "nt":
        raise InboxError("--console requires Windows")
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout


def configure_activity(catalog: Catalog, *, file_log: bool = True) -> logging.Logger:
    """Show request metadata, never pairing secrets, URLs, headers or bodies."""
    logger = logging.getLogger("opl.human")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.StreamHandler(sys.stderr))
    if file_log and catalog.directory is not None:
        path = catalog.directory / "service.log"
        if path.is_symlink():
            raise InboxError("the service log must not be a symlink")
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        logger.addHandler(logging.FileHandler(path, encoding="utf-8"))
    for handler in logger.handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    return logger
