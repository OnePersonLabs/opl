"""Reconcile the dedicated Slop Buster repository and daily Windows task."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from slop_config import (_windows_codex_home, config_file, discover_source_homes,
                         is_wsl, load_config, DEFAULT_DATA_REPO)


TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", TASK_NS)


def _windows_path(path: str) -> str:
    if not is_wsl():
        return path
    return subprocess.run(["wslpath", "-w", path], capture_output=True, text=True, check=True).stdout.strip()


def task_name(data_repo: str) -> str:
    identity = _windows_path(str(Path(data_repo).resolve())).casefold()
    return "SlopBuster-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _element(parent: ET.Element, name: str, value: str | None = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, f"{{{TASK_NS}}}{name}", attrs)
    if value is not None:
        element.text = value
    return element


def task_xml(config: dict, config_path: Path, user_sid: str) -> str:
    """Build a logged-on-only task that opens a visible persistent console."""
    root = ET.Element(f"{{{TASK_NS}}}Task", {"version": "1.4"})
    registration = _element(root, "RegistrationInfo")
    _element(registration, "Description", "Slop Buster data repo: " + _windows_path(config["data_repo"]))
    triggers = _element(root, "Triggers")
    trigger = _element(triggers, "CalendarTrigger")
    _element(trigger, "StartBoundary", datetime.now().strftime("%Y-%m-%d") + "T" + config["schedule_time"] + ":00")
    _element(trigger, "Enabled", "true")
    schedule = _element(trigger, "ScheduleByDay")
    _element(schedule, "DaysInterval", "1")
    principals = _element(root, "Principals")
    principal = _element(principals, "Principal", id="Author")
    _element(principal, "UserId", user_sid)
    _element(principal, "LogonType", "InteractiveToken")
    _element(principal, "RunLevel", "LeastPrivilege")
    settings = _element(root, "Settings")
    _element(settings, "MultipleInstancesPolicy", "Parallel")
    _element(settings, "DisallowStartIfOnBatteries", "false")
    _element(settings, "StopIfGoingOnBatteries", "false")
    _element(settings, "StartWhenAvailable", "true")
    _element(settings, "ExecutionTimeLimit", "PT0S")
    _element(settings, "Enabled", "true")
    actions = _element(root, "Actions", Context="Author")
    action = _element(actions, "Exec")
    _element(action, "Command", "powershell.exe")
    launcher = _windows_path(str(Path(__file__).with_name("slop_daily.ps1").resolve()))
    selected = _windows_path(str(config_path.resolve()))
    _element(action, "Arguments", f'-NoProfile -NoExit -ExecutionPolicy Bypass -File "{launcher}" --scheduled --config "{selected}"')
    _element(action, "WorkingDirectory", _windows_path(config["data_repo"]))
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(root, encoding="unicode")


def _task_signature(xml: str) -> tuple[str | None, ...]:
    root = ET.fromstring(xml)
    def find(path: str) -> str | None:
        node = root.find(path, {"t": TASK_NS})
        return node.text if node is not None else None
    boundary = find("t:Triggers/t:CalendarTrigger/t:StartBoundary")
    return (
        find("t:RegistrationInfo/t:Description"),
        boundary[11:] if boundary else None,
        find("t:Principals/t:Principal/t:UserId"),
        find("t:Principals/t:Principal/t:LogonType"),
        find("t:Settings/t:MultipleInstancesPolicy"),
        find("t:Settings/t:DisallowStartIfOnBatteries"),
        find("t:Settings/t:StopIfGoingOnBatteries"),
        find("t:Settings/t:StartWhenAvailable"),
        find("t:Actions/t:Exec/t:Command"),
        find("t:Actions/t:Exec/t:Arguments"),
        find("t:Actions/t:Exec/t:WorkingDirectory"),
    )


def _current_sid() -> str:
    command = ["powershell.exe" if is_wsl() else "powershell.exe", "-NoProfile", "-Command",
               "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()


def _assert_chicago_clock() -> None:
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "(Get-TimeZone).Id"],
                            capture_output=True, text=True, check=True)
    if result.stdout.strip() != "Central Standard Time":
        raise ValueError("Windows timezone must be Central Standard Time for the 09:00 America/Chicago task")


def _scheduler_config_path(config: dict, requested: Path) -> Path:
    """Use the identical native config for a mirrored WSL installation."""
    if is_wsl():
        windows_home = _windows_codex_home()
        if windows_home:
            candidate = Path(windows_home) / "slop-buster.toml"
            if candidate.is_file() and load_config(str(candidate)) == config:
                return candidate
    return requested


def reconcile_task(config: dict, path: Path, *, dry_run: bool = False) -> str:
    if os.name != "nt" and not is_wsl():
        raise OSError("Windows Task Scheduler setup requires Windows or WSL")
    _assert_chicago_clock()
    name = task_name(config["data_repo"])
    desired = task_xml(config, _scheduler_config_path(config, path), _current_sid())
    schtasks = "schtasks.exe" if is_wsl() else "schtasks.exe"
    current = subprocess.run([schtasks, "/Query", "/TN", name, "/XML"], capture_output=True, text=True)
    if current.returncode and "cannot find" not in current.stderr.lower():
        raise RuntimeError(f"Cannot inspect scheduled task {name}: {current.stderr.strip() or current.stdout.strip()}")
    if current.returncode == 0:
        existing = _task_signature(current.stdout)
        target = _task_signature(desired)
        if existing[0] != target[0]:
            raise ValueError(f"Existing scheduled task {name} has a different owner marker; no changes made")
        if existing == target:
            return "unchanged"
    if dry_run:
        return "would update" if current.returncode == 0 else "would create"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", encoding="utf-16", delete=False) as stream:
        stream.write(desired)
        temp = Path(stream.name)
    try:
        xml_path = _windows_path(str(temp))
        created = subprocess.run([schtasks, "/Create", "/TN", name, "/XML", xml_path, "/F"],
                                 capture_output=True, text=True)
        if created.returncode:
            raise RuntimeError(f"Cannot register scheduled task {name}: {created.stderr.strip() or created.stdout.strip()}")
    finally:
        temp.unlink(missing_ok=True)
    return "updated" if current.returncode == 0 else "created"


def _write_initial_config(path: Path) -> None:
    homes = discover_source_homes()
    if not homes:
        raise ValueError("No Codex source home found; set source_homes in a config file")
    import json
    def quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)
    lines = [f"data_repo = {quote(DEFAULT_DATA_REPO)}", "source_homes = [" + ", ".join(quote(home) for home in homes) + "]",
             "deadline_seconds = 1800", 'schedule_time = "09:00"', 'timezone = "America/Chicago"', "",
             "[models.orchestrator]", 'name = "gpt-6-sol"', 'effort = "medium"', "",
             "[models.reader]", 'name = "gpt-5.6-luna"', 'effort = "medium"', "",
             "[models.synthesis]", 'name = "gpt-6-sol"', 'effort = "high"', ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def setup(config_path: str | None = None, *, dry_run: bool = False) -> dict:
    path = config_file(config_path)
    if not path.exists():
        if dry_run:
            return {"config": str(path), "status": "would create config; run setup to register task"}
        _write_initial_config(path)
    config = load_config(str(path))
    repo = Path(config["data_repo"])
    if not repo.exists():
        if not dry_run:
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    elif not (repo / ".git").exists():
        raise ValueError(f"Existing data_repo is not a Git repository: {repo}")
    if not dry_run:
        ignore = repo / ".gitignore"
        entries = {line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()} if ignore.exists() else set()
        additions = [entry for entry in (".runtime/", "index/", "feedback/") if entry not in entries]
        if additions:
            with ignore.open("a", encoding="utf-8") as stream:
                if ignore.exists() and ignore.stat().st_size:
                    stream.write("\n")
                stream.write("\n".join(additions) + "\n")
    return {"config": str(path), "data_repo": str(repo), "task": task_name(str(repo)),
            "task_status": reconcile_task(config, path, dry_run=dry_run)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    import json
    try:
        print(json.dumps(setup(args.config, dry_run=args.dry_run)))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, ET.ParseError) as error:
        print(f"Slop Buster setup failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
