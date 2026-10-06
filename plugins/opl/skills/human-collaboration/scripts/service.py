"""Start or reuse one ready local service at the requested fixed address."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
from pathlib import Path
import signal
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


def _refresh_state_path(catalog: Catalog) -> Path:
    if catalog.directory is None:
        raise InboxError("refresh lifecycle requires a persistent service catalog")
    return catalog.directory / "refresh-state.json"


def _read_refresh_state(path: Path) -> dict | None:
    if path.is_symlink():
        raise InboxError("the refresh lifecycle record must not be a symlink")
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("version") != 1 or
            not isinstance(value.get("workspace"), str) or
            not isinstance(value.get("was_running"), bool)):
        raise InboxError("the refresh lifecycle record is invalid; inspect it before continuing")
    if value["was_running"] and (
            not isinstance(value.get("host"), str) or
            not isinstance(value.get("port"), int) or
            not isinstance(value.get("allow_lan"), bool) or
            not isinstance(value.get("wake_root"), bool)):
        raise InboxError("the refresh lifecycle record is incomplete; inspect it before continuing")
    return value


def _write_refresh_state(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value))
    path.chmod(0o600)


def _same_workspace(left: str, right: Path) -> bool:
    return Path(left).resolve() == right.resolve()


def _process_is_alive(pid: int) -> bool:
    """Distinguish an exited listener from a live but unresponsive process."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        process = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not process:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: no process has this ID
                return False
            if error == 5:  # ERROR_ACCESS_DENIED: process exists but cannot be queried
                return True
            raise OSError(error, "could not check the recorded service process")
        try:
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(process)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _send_console_ctrl_c(pid: int) -> None:
    """Send Ctrl+C to this service's console so its normal cleanup runs."""
    if os.name != "nt":
        raise InboxError("console control shutdown is available only on Windows")
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        raise InboxError(f"could not attach to the human-collaboration console for process {pid}")
    try:
        # The helper shares this console briefly. Ignore Ctrl+C in the helper
        # for its remaining lifetime while delivering it to the server process.
        if not kernel32.SetConsoleCtrlHandler(None, True):
            raise InboxError("could not protect the refresh helper from the console stop signal")
        if not kernel32.GenerateConsoleCtrlEvent(0, 0):  # CTRL_C_EVENT to this console
            raise InboxError("could not send Ctrl+C to the human-collaboration console")
    finally:
        kernel32.FreeConsole()


def _stop_listener(service: dict, catalog: Catalog) -> None:
    """Stop only the authenticated catalog service recorded at this address."""
    if os.name == "nt":
        pid = service.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise InboxError("the Windows service receipt has no valid process ID")
        _send_console_ctrl_c(pid)
    else:
        pid = service.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise InboxError("the service receipt has no valid process ID")
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (ready(catalog, service["host"], service["port"]) is None and
                not _process_is_alive(service["pid"])):
            return
        time.sleep(0.1)
    raise InboxError("the service did not stop after a graceful shutdown request; refresh was not prepared")


def pause_for_refresh(catalog: Catalog, workspace: Path) -> dict:
    """Remember whether the current workspace's service was live, then stop it."""
    path = _refresh_state_path(catalog)
    state = _read_refresh_state(path)
    if state is not None:
        if not _same_workspace(state.get("workspace", ""), workspace):
            raise InboxError("another workspace owns the pending refresh lifecycle record")
        if not state.get("was_running"):
            return {"was_running": False, "stopped": False, "reason": "service was not running before refresh"}
        service = ready(catalog, state["host"], state["port"])
        if service is not None:
            _stop_listener(service, catalog)
        else:
            stored_path = catalog.directory / "service.json"
            if stored_path.is_symlink():
                raise InboxError("the service receipt must not be a symlink")
            stored = json.loads(stored_path.read_text(encoding="utf-8")) if stored_path.is_file() else {}
            if (stored.get("host"), stored.get("port")) != (state["host"], state["port"]):
                raise InboxError("cannot confirm the previously running service has stopped")
            pid = stored.get("pid")
            if not isinstance(pid, int) or _process_is_alive(pid):
                raise InboxError("the service is not responding but its recorded process is still running; refusing to refresh")
        return {"was_running": True, "stopped": True, "host": state["host"], "port": state["port"]}

    receipt_path = catalog.directory / "service.json"
    if receipt_path.is_symlink():
        raise InboxError("the service receipt must not be a symlink")
    stored = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
    service = None
    if isinstance(stored, dict) and stored.get("catalog_id") == catalog.id:
        host, port = stored.get("host"), stored.get("port")
        if not isinstance(host, str) or not isinstance(port, int):
            raise InboxError("the service receipt is incomplete; refusing to infer that no service is running")
        service = ready(catalog, host, port)
        if service is None:
            pid = stored.get("pid")
            if not isinstance(pid, int) or _process_is_alive(pid):
                raise InboxError("the service is not responding but its recorded process is still running; refusing to refresh")
    elif isinstance(stored, dict):
        raise InboxError("the service receipt belongs to a different catalog; refusing to infer that no service is running")
    elif stored is not None:
        raise InboxError("the service receipt is invalid; refusing to infer that no service is running")

    if service is None:
        _write_refresh_state(path, {"version": 1, "workspace": str(workspace.resolve()), "was_running": False})
        return {"was_running": False, "stopped": False, "reason": "service was not running before refresh"}

    address = validate_address(service["host"], service["port"], allow_lan=True)
    if address.is_unspecified:
        raise InboxError("the running service uses a wildcard bind and cannot be resumed by the refresh command")
    catalog.first_available_store()
    state = {"version": 1, "workspace": str(workspace.resolve()), "was_running": True,
             "host": service["host"], "port": service["port"],
             "allow_lan": not address.is_loopback, "wake_root": bool(service.get("wake_root"))}
    _write_refresh_state(path, state)
    _stop_listener(service, catalog)
    return {"was_running": True, "stopped": True, "host": state["host"], "port": state["port"]}


def resume_after_refresh(inbox: Inbox, catalog: Catalog) -> dict:
    """Restart only when pause_for_refresh recorded a live service."""
    path = _refresh_state_path(catalog)
    state = _read_refresh_state(path)
    if state is None:
        return {"was_running": False, "restarted": False, "reason": "no pending refresh lifecycle record"}
    if not _same_workspace(state.get("workspace", ""), inbox.workspace):
        raise InboxError("the pending refresh lifecycle record belongs to another workspace")
    if not state.get("was_running"):
        path.unlink()
        return {"was_running": False, "restarted": False, "reason": "service was not running before refresh"}

    resume_inbox = catalog.first_available_store()
    service = connect(resume_inbox, state["host"], state["port"], allow_lan=state["allow_lan"],
                      wake=state["wake_root"], catalog=catalog)
    path.unlink()
    return {"was_running": True, "restarted": not service.get("reused", False),
            "host": service["host"], "port": service["port"], "wake_root": service["wake_root"],
            "url": service["url"], "lan_ip": service["lan_ip"], "lan_url": service["lan_url"],
            "access": service["access"]}


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
