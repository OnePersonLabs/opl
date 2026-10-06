"""Local CLI registration and aggregate views for the user's human inboxes."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import os
import json
from pathlib import Path
import sqlite3
import uuid

from inbox import Conflict, Inbox, InboxError


def runtime_directory() -> Path:
    configured = os.environ.get("OPL_HUMAN_RUNTIME")
    if configured:
        path = Path(configured).expanduser().resolve()
    elif os.name == "nt":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OPL/human-inbox"
    else:
        path = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "opl/human-inbox"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise InboxError("the human inbox runtime directory must not be a symlink")
    return path


def session_order(session: dict) -> tuple:
    group = 0 if session["needs_you"] else (1 if session["with_agent"] else 2)
    return group, session["priority"] if group == 0 else 0, -datetime.fromisoformat(session["updated"]).timestamp(), session["id"]


class Catalog:
    """Browser requests resolve IDs from this catalog, never filesystem paths."""
    def __init__(self, directory: Path | None = None, *, inboxes: list[Inbox] | None = None):
        self.fixed = inboxes
        self.directory = directory if directory is not None else (None if inboxes is not None else runtime_directory())
        if self.fixed is not None:
            self.id = "foreground"
            self.fixed_ids = {}
            for inbox in self.fixed:
                with inbox.transaction() as db:
                    self.fixed_ids[inbox.workspace] = inbox._meta(db, "workspace_id")
            return
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / "catalog.sqlite3"
        if path.is_symlink():
            raise InboxError("the inbox catalog must not be a symlink")
        with closing(sqlite3.connect(path, timeout=5)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE)")
            db.execute("INSERT OR IGNORE INTO meta VALUES ('id',?)", (str(uuid.uuid4()),))
            db.commit()
            self.id = db.execute("SELECT value FROM meta WHERE key='id'").fetchone()[0]
        path.chmod(0o600)

    def register(self, inbox: Inbox) -> str:
        snapshot = inbox.snapshot()
        identifier = snapshot["workspace_id"]
        if self.fixed is not None:
            if all(entry.workspace != inbox.workspace for entry in self.fixed):
                self.fixed.append(inbox)
            self.fixed_ids[inbox.workspace] = identifier
            return identifier
        with closing(sqlite3.connect(self.directory / "catalog.sqlite3", timeout=5)) as db:
            existing = db.execute("SELECT path FROM workspaces WHERE id=?", (identifier,)).fetchone()
            if existing and Path(existing[0]) != inbox.workspace:
                raise Conflict("workspace ID already belongs to another registered path; inspect the copied inbox")
            db.execute("INSERT INTO workspaces VALUES (?,?) ON CONFLICT(path) DO UPDATE SET id=excluded.id", (identifier, str(inbox.workspace)))
            db.commit()
        return identifier

    def _registrations(self, identifier: str | None = None) -> list[tuple[str, str]]:
        if self.fixed is not None:
            return [(key, str(path)) for path, key in self.fixed_ids.items() if identifier is None or key == identifier]
        with closing(sqlite3.connect(self.directory / "catalog.sqlite3", timeout=5)) as db:
            return db.execute("SELECT id,path FROM workspaces" + (" WHERE id=?" if identifier is not None else "") + " ORDER BY id",
                              (identifier,) if identifier is not None else ()).fetchall()

    @staticmethod
    def _open(identifier: str, path: str) -> Inbox:
        inbox = Inbox(path)
        with inbox.transaction() as db:
            if inbox._meta(db, "workspace_id") != identifier:
                raise Conflict(f"registered workspace identity changed: {path}; register it again locally")
        return inbox

    def stores(self) -> list[Inbox]:
        return [self._open(identifier, path) for identifier, path in self._registrations()]

    def resolve(self, identifier: str | None = None) -> Inbox:
        registrations = self._registrations(identifier)
        if identifier is None:
            if len(registrations) != 1:
                raise Conflict("choose a workspace; more than one inbox is registered")
        if not registrations:
            raise InboxError("unknown registered workspace ID")
        return self._open(*registrations[0])

    def resolve_session(self, identifier: str | None) -> tuple[Inbox, str]:
        if identifier is None:
            snapshot = self.snapshot()
            sessions = snapshot["sessions"]
            if len(sessions) != 1 or snapshot["unavailable"]:
                raise Conflict("choose a session for this contribution")
            identifier = sessions[0]["id"]
        if not isinstance(identifier, str) or "/" not in identifier:
            raise InboxError("session must be a workspace ID followed by / and its thread ID")
        workspace, thread = identifier.split("/", 1)
        inbox = self.resolve(workspace)
        with inbox.transaction() as db:
            inbox.owner(db, thread)
        return inbox, thread

    def snapshot(self) -> dict:
        registrations = self._registrations()
        snapshots, unavailable = [], []
        for identifier, path in registrations:
            try:
                snapshots.append(self._open(identifier, path).snapshot())
            except (InboxError, OSError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as error:
                unavailable.append({"workspace_id": identifier, "workspace": path, "error": str(error)})
        sessions = sorted([session for snapshot in snapshots for session in snapshot["sessions"]], key=session_order)
        ranks = {session["id"]: rank for rank, session in enumerate(sessions)}
        items = [item for snapshot in snapshots for item in snapshot["items"]]
        items.sort(key=lambda item: (ranks[item["session"]], item["priority"], item["state"] != "active", item["number"]))
        pending = []
        for snapshot in snapshots:
            ownership = {item["number"]: item for item in snapshot["items"]}
            for receipt in snapshot["pending"]:
                item = ownership[receipt["item"]]
                pending.append({**receipt, "workspace_id": item["workspace_id"], "session": item["session"]})
        return {"workspace": snapshots[0]["workspace"] if len(registrations) == 1 and snapshots else f"{len(registrations)} workspaces",
                "workspace_id": snapshots[0]["workspace_id"] if len(registrations) == 1 and snapshots else self.id,
                "sessions": sessions, "items": items, "pending": pending,
                "unavailable": unavailable,
                "messages": sorted([message for snapshot in snapshots for message in snapshot["messages"]],
                                   key=lambda message: (message["created"], message["id"]), reverse=True),
                "event": sum(snapshot["event"] for snapshot in snapshots)}
