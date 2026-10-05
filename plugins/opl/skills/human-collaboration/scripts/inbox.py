"""Durable human contributions. SQLite owns receipts; Markdown is a readable view.

The store never rewrites a published brief, including its human-owned # Reply.
Web drafts are separate, versioned records, so a phone cannot clobber an editor.
"""
from __future__ import annotations

import base64
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Iterator
import uuid

SCHEMA = 1
MAX_TEXT = 128 * 1024
MAX_SOURCE = 512 * 1024
DISPOSITIONS = {"adopted", "partial", "not_adopted", "explained", "follow_up"}


class InboxError(ValueError):
    """A user-actionable validation error."""


class Conflict(InboxError):
    """The caller must inspect newer state before retrying."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def text(value: Any, field: str, *, empty: bool = False, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise InboxError(f"{field} must be {'a string' if empty else 'nonempty text'}")
    if len(value.encode("utf-8")) > limit:
        raise InboxError(f"{field} exceeds {limit} bytes")
    return value


def number(value: Any, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InboxError(f"{field} must be an integer from {low} to {high}")
    return value


def item_number(value: str | int) -> int:
    match = re.fullmatch(r"H?0*([1-9][0-9]*)", str(value), flags=re.IGNORECASE)
    if not match:
        raise InboxError("item must be a stable ID such as H001")
    return int(match[1])


def label(value: int) -> str:
    return f"H{value:03d}"


def atomic_write(path: Path, value: str) -> None:
    """Replace generated material only. Never call this on human-owned briefs."""
    if path.is_symlink():
        raise InboxError(f"refusing to replace symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def discover(cwd: Path) -> Path | None:
    current = cwd.resolve()
    for directory in [current, *current.parents]:
        if (directory / ".human" / "state.sqlite3").is_file():
            return directory
    return None


class Inbox:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        self.root = self.workspace / ".human"
        self.db_path = self.root / "state.sqlite3"
        if not self.workspace.is_dir():
            raise InboxError("workspace is not a directory")
        if self.root.is_symlink() or self.db_path.is_symlink():
            raise InboxError("the inbox and database must not be symlinks")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if not self.db_path.is_file():
            raise InboxError("human inbox is not initialized; run init first")
        connection = sqlite3.connect(self.db_path, timeout=2, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
                raise InboxError("unsupported human inbox schema; keep the files and use the matching helper")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init(self, thread: str) -> dict:
        text(thread, "root thread", limit=200)
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.db_path.exists():
            with self.transaction() as db:
                owner = self._meta(db, "thread")
                if owner != thread:
                    raise Conflict(f"inbox belongs to {owner}; use bind with a reason for an explicit handoff")
            return self.snapshot()
        # Exclusive creation prevents two initializers replacing one another.
        with self.db_path.open("xb"):
            pass
        self.db_path.chmod(0o600)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript("""
                PRAGMA synchronous = FULL;
                BEGIN IMMEDIATE;
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT NOT NULL);
                CREATE TABLE versions (
                    item INTEGER NOT NULL REFERENCES items(id), revision INTEGER NOT NULL,
                    body TEXT NOT NULL, sources TEXT NOT NULL, metadata TEXT NOT NULL, published_mtime_ns TEXT,
                    PRIMARY KEY (item, revision));
                CREATE TABLE drafts (
                    item INTEGER NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    version INTEGER NOT NULL, updated TEXT NOT NULL,
                    PRIMARY KEY (item, revision),
                    FOREIGN KEY (item, revision) REFERENCES versions(item, revision));
                CREATE TABLE submissions (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    item INTEGER NOT NULL, revision INTEGER NOT NULL,
                    body TEXT NOT NULL, kind TEXT NOT NULL, channel TEXT NOT NULL,
                    state TEXT NOT NULL, claimed_by TEXT, created TEXT NOT NULL,
                    queue TEXT NOT NULL,
                    FOREIGN KEY (item, revision) REFERENCES versions(item, revision));
                CREATE TABLE outcomes (
                    submission TEXT PRIMARY KEY REFERENCES submissions(id),
                    doc TEXT NOT NULL);
                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, item INTEGER,
                    action TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE notices (thread TEXT NOT NULL, submission TEXT NOT NULL,
                    PRIMARY KEY (thread, submission));
                PRAGMA user_version = 1;
            """)
            db.executemany("INSERT INTO meta VALUES (?, ?)", [
                ("workspace_id", str(uuid.uuid4())), ("thread", thread), ("created", now())])
            db.commit()
        # Private local workflow state is not silently published to Git.
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
        self.refresh()
        return self.snapshot()

    @staticmethod
    def _meta(db: sqlite3.Connection, key: str) -> str:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if not row:
            raise InboxError(f"missing inbox metadata: {key}")
        return row[0]

    def owner(self, db: sqlite3.Connection, thread: str | None) -> None:
        if not thread or thread != self._meta(db, "thread"):
            raise Conflict("this operation belongs to the bound root thread; inspect ownership before binding")

    @staticmethod
    def _event(db: sqlite3.Connection, item: int | None, action: str, detail: Any) -> None:
        db.execute("INSERT INTO events(item,action,detail,created) VALUES (?,?,?,?)",
                   (item, action, json.dumps(detail, ensure_ascii=False), now()))

    @staticmethod
    def _item(db: sqlite3.Connection, item: str | int) -> dict:
        row = db.execute("SELECT doc FROM items WHERE id=?", (item_number(item),)).fetchone()
        if row is None:
            raise InboxError(f"unknown item: {item}")
        return json.loads(row[0])

    @staticmethod
    def _put(db: sqlite3.Connection, item: dict) -> None:
        item["updated"] = now()
        db.execute("UPDATE items SET doc=? WHERE id=?", (json.dumps(item, ensure_ascii=False), item["number"]))

    @staticmethod
    def _version(db: sqlite3.Connection, item: int, revision: int) -> dict:
        row = db.execute("SELECT * FROM versions WHERE item=? AND revision=?", (item, revision)).fetchone()
        if row is None:
            raise InboxError("unknown brief revision")
        value = dict(row)
        value["sources"] = json.loads(value["sources"])
        return value

    def brief_path(self, item: int, revision: int) -> Path:
        result = self.root / "items" / label(item) / f"brief-v{revision}.md"
        if not result.resolve().is_relative_to(self.root.resolve()):
            raise InboxError("brief path leaves the inbox")
        return result

    @staticmethod
    def _prefix(version: dict) -> str:
        return version["body"].rstrip() + "\n\n# Reply\n\n"

    def _file_reply(self, version: dict) -> tuple[str, str | None]:
        path = self.brief_path(version["item"], version["revision"])
        if not path.exists():
            return "", "published brief is missing; restore the file from backup before submitting"
        if path.stat().st_size > MAX_TEXT * 2:
            return "", "brief file exceeds the size limit"
        raw = path.read_text(encoding="utf-8")
        prefix = self._prefix(version)
        if not raw.startswith(prefix):
            return "", "published body changed outside # Reply; compare with the saved revision before submitting"
        return raw[len(prefix):], None

    def _drafts(self, db: sqlite3.Connection, version: dict) -> dict:
        row = db.execute("SELECT body,version,updated FROM drafts WHERE item=? AND revision=?",
                         (version["item"], version["revision"])).fetchone()
        web = dict(row) if row else {"body": "", "version": 0, "updated": None}
        reply, error = self._file_reply(version)
        previous = db.execute("SELECT body FROM submissions WHERE item=? AND revision=? AND channel='file' ORDER BY rowid DESC LIMIT 1",
                              (version["item"], version["revision"])).fetchone()
        file_pending = bool(reply.strip()) and (not previous or reply != previous[0])
        return {"web": web, "file": reply, "file_pending": file_pending, "file_error": error,
                "pending": bool(web["body"].strip()) or file_pending}

    def _revision_work(self, db: sqlite3.Connection, item: int) -> list[dict]:
        """Older briefs still own their drafts, even after a newer brief exists."""
        revisions = []
        for row in db.execute("SELECT * FROM versions WHERE item=? ORDER BY revision", (item,)).fetchall():
            drafts = self._drafts(db, dict(row))
            revisions.append({"revision": row["revision"], "has_draft": drafts["pending"],
                              "file_error": drafts["file_error"]})
        return revisions

    @staticmethod
    def _attention_state(state: str, revisions: list[dict]) -> str:
        """An editor can add work after closure, without using a queue command."""
        if state in {"resolved", "retired"} and any(
                revision["has_draft"] or revision["file_error"] for revision in revisions):
            return "ready"
        return state

    def _source_file(self, relative: str) -> Path:
        text(relative, "source path", limit=2000)
        if Path(relative).is_absolute():
            raise InboxError("source paths must be workspace-relative")
        resolved = (self.workspace / relative).resolve(strict=True)
        if not resolved.is_relative_to(self.workspace) or resolved.is_relative_to(self.root):
            raise InboxError("source path leaves the workspace or enters private inbox state")
        if not resolved.is_file() or resolved.stat().st_size > MAX_SOURCE:
            raise InboxError(f"source must be a regular file of at most {MAX_SOURCE} bytes: {relative}")
        return resolved

    def capture_sources(self, paths: Any) -> list[dict]:
        if not isinstance(paths, list) or len(paths) > 12:
            raise InboxError("sources must be a list of at most 12 workspace-relative paths")
        result = []
        for relative in paths:
            path = self._source_file(relative)
            content = path.read_bytes()
            suffix = path.suffix.lower()
            mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix, "text/plain")
            if mime == "text/plain":
                content.decode("utf-8")
            result.append({"path": relative, "sha256": digest(content), "mime": mime,
                           "content": base64.b64encode(content).decode("ascii")})
        return result

    def source_status(self, sources: list[dict]) -> list[dict]:
        status = []
        for source in sources:
            try:
                current = digest(self._source_file(source["path"]).read_bytes())
                status.append({"path": source["path"], "published": source["sha256"], "current": current,
                               "changed": current != source["sha256"]})
            except (OSError, InboxError) as error:
                status.append({"path": source["path"], "published": source["sha256"], "current": None,
                               "changed": True, "error": str(error)})
        return status

    def _spec(self, spec: dict) -> tuple[dict, str, list[dict]]:
        if not isinstance(spec, dict):
            raise InboxError("spec must be an object")
        value = {key: text(spec.get(key), key, limit=2000) for key in ("title", "summary", "why_now")}
        value["kind"] = text(spec.get("kind", "review"), "kind", limit=80)
        value["priority"] = number(spec.get("priority", 50), "priority", 0, 100)
        for key in ("blocking", "decision"):
            if not isinstance(spec.get(key, False), bool):
                raise InboxError(f"{key} must be true or false")
            value[key] = spec.get(key, False)
        value["state"] = spec.get("state", "ready")
        if value["state"] not in {"candidate", "ready"}:
            raise InboxError("new briefs must be candidate or ready")
        # Preparation belongs to the root; deferring or reopening is a separate
        # human queue action and must not implicitly prepare a candidate.
        value["prepared"] = value["state"] == "ready"
        body = text(spec.get("brief"), "brief").replace("\r\n", "\n").replace("\r", "\n")
        sources = self.capture_sources(spec.get("sources", []))
        return value, body, sources

    def publish(self, spec: dict, thread: str) -> dict:
        value, body, sources = self._spec(spec)
        with self.transaction() as db:
            self.owner(db, thread)
            identifier = db.execute("INSERT INTO items(doc) VALUES ('{}')").lastrowid
            value.update(number=identifier, id=label(identifier), revision=1, created=now())
            self._put(db, value)
            db.execute("INSERT INTO versions(item,revision,body,sources,metadata) VALUES (?,?,?,?,?)",
                       (identifier, 1, body, json.dumps(sources), json.dumps(value)))
            self._event(db, identifier, "published", {"revision": 1})
        self.refresh()
        return self.get(value["id"])

    def contribute(self, title: str, body: str, request_id: str) -> dict:
        """Create a human-initiated thread and its receipt in one transaction."""
        text(title, "title", limit=2000)
        text(body, "contribution")
        text(request_id, "request ID", limit=200)
        with self.transaction() as db:
            previous = db.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                receipt = dict(previous)
                item = self._item(db, receipt["item"])
                if not item.get("human_initiated") or item["title"] != title or receipt["body"] != body:
                    raise Conflict("request ID was already used for different content")
                return receipt
            identifier = db.execute("INSERT INTO items(doc) VALUES ('{}')").lastrowid
            value = {"number": identifier, "id": label(identifier), "revision": 1,
                     "title": title, "summary": "A contribution initiated by you, not an agent assignment.",
                     "why_now": "The root needs to assess this contribution and its downstream effects.",
                     "kind": "human contribution", "priority": 50, "blocking": False,
                     "decision": False, "human_initiated": True, "prepared": True,
                     "state": "with_agent", "created": now()}
            self._put(db, value)
            brief = "# Human-initiated contribution\n\n" + title + "\n\nNo agent-authored premise or source snapshot was supplied. Establish context before treating this as an architectural decision."
            db.execute("INSERT INTO versions(item,revision,body,sources,metadata) VALUES (?,?,?,?,?)",
                       (identifier, 1, brief, "[]", json.dumps(value)))
            receipt = {"id": str(uuid.uuid4()), "request_id": request_id, "item": identifier,
                       "revision": 1, "body": body, "kind": "feedback", "channel": "web",
                       "state": "submitted", "claimed_by": None, "created": now(),
                       "queue": json.dumps({"state": "not_requested"})}
            db.execute("INSERT INTO submissions VALUES (:id,:request_id,:item,:revision,:body,:kind,:channel,:state,:claimed_by,:created,:queue)", receipt)
            self._event(db, identifier, "human_initiated", {"submission": receipt["id"]})
        self.refresh()
        return receipt

    def revise(self, item: str, spec: dict, reason: str, thread: str) -> dict:
        text(reason, "reason")
        changes, body, sources = self._spec(spec)
        with self.transaction() as db:
            self.owner(db, thread)
            value = self._item(db, item)
            revisions = self._revision_work(db, value["number"])
            if value["state"] in {"active", "with_agent"} or any(
                    revision["has_draft"] or revision["file_error"] for revision in revisions):
                raise Conflict("human work is in flight; keep this revision stable and address it before revising")
            if self._pending(db, value["number"]):
                raise Conflict("unresolved submissions must be addressed before revising")
            value.update(changes)
            value["revision"] += 1
            self._put(db, value)
            db.execute("INSERT INTO versions(item,revision,body,sources,metadata) VALUES (?,?,?,?,?)",
                       (value["number"], value["revision"], body, json.dumps(sources), json.dumps(value)))
            self._event(db, value["number"], "revised", {"reason": reason, "revision": value["revision"]})
        self.refresh()
        return self.get(item)

    def bind(self, thread: str, reason: str) -> dict:
        text(thread, "thread", limit=200)
        text(reason, "handoff reason")
        with self.transaction() as db:
            previous = self._meta(db, "thread")
            db.execute("UPDATE meta SET value=? WHERE key='thread'", (thread,))
            self._event(db, None, "root_handoff", {"from": previous, "to": thread, "reason": reason})
        return {"thread": thread, "previous": previous, "note": "inspect already-claimed work before resuming effects"}

    @staticmethod
    def _pending(db: sqlite3.Connection, item: int | None = None) -> list[dict]:
        sql = "SELECT * FROM submissions WHERE state != 'resolved'"
        rows = db.execute(sql + (" AND item=?" if item else "") + " ORDER BY rowid", (item,) if item else ())
        return [dict(row) for row in rows]

    def move(self, item: str, action: str, reason: str = "", priority: int | None = None, thread: str | None = None) -> dict:
        with self.transaction() as db:
            value = self._item(db, item)
            revisions = self._revision_work(db, value["number"])
            value["state"] = self._attention_state(value["state"], revisions)
            if action in {"rank", "retire"}:
                self.owner(db, thread)
            if action != "start":
                text(reason, "reason")
            if action == "rank":
                value["priority"] = number(priority, "priority", 0, 100)
            elif action == "start":
                if not value["prepared"] or value["state"] not in {"ready", "deferred", "active"}:
                    raise Conflict("only a prepared, unanswered item can be started")
                others = [json.loads(row[0]) for row in db.execute("SELECT doc FROM items WHERE id != ?", (value["number"],))]
                if any(other["state"] == "active" for other in others):
                    raise Conflict("another item is active; put it Later before starting this one")
                value["state"] = "active"
            elif action in {"later", "ready", "retire"}:
                if self._pending(db, value["number"]):
                    raise Conflict("submitted work stays With agent until its response is recorded")
                if action == "retire" and (value["state"] == "active" or any(
                    revision["has_draft"] or revision["file_error"]
                    for revision in revisions)):
                    raise Conflict("cannot retire active work or a human draft")
                if value["state"] in {"resolved", "retired"} and action != "ready":
                    raise Conflict("item is already closed")
                if action == "ready" and not value["prepared"]:
                    self.owner(db, thread)
                    value["prepared"] = True
                value["state"] = {"later": "deferred", "ready": "ready", "retire": "retired"}[action]
            else:
                raise InboxError("unknown queue action")
            self._put(db, value)
            self._event(db, value["number"], action, {"reason": reason, "priority": priority})
        self.refresh()
        return self.get(item)

    def save_draft(self, item: str, revision: int, body: str, expected: int) -> dict:
        text(body, "draft", empty=True)
        number(expected, "expected draft version", 0, 2**53 - 1)
        with self.transaction() as db:
            value = self._item(db, item)
            self._version(db, value["number"], revision)
            row = db.execute("SELECT version FROM drafts WHERE item=? AND revision=?", (value["number"], revision)).fetchone()
            actual = row[0] if row else 0
            if actual != expected:
                raise Conflict("another device saved a newer draft; copy your local text before reconciling")
            stamp = now()
            if body.strip() and value["state"] in {"resolved", "retired"}:
                value["state"] = "ready"
                self._put(db, value)
            self._event(db, value["number"], "draft_saved", {"revision": revision, "version": actual + 1})
            db.execute("INSERT INTO drafts VALUES (?,?,?,?,?) ON CONFLICT(item,revision) DO UPDATE SET body=excluded.body,version=excluded.version,updated=excluded.updated",
                       (value["number"], revision, body, actual + 1, stamp))
        self.refresh()
        return {"body": body, "version": actual + 1, "updated": stamp}

    def submit(self, item: str, revision: int, body: str, request_id: str, *, kind: str = "feedback", channel: str = "web") -> dict:
        text(body, "reply")
        text(request_id, "request ID", limit=200)
        if kind not in {"feedback", "question"} or channel not in {"web", "file"}:
            raise InboxError("invalid submission kind or channel")
        with self.transaction() as db:
            value = self._item(db, item)
            previous = db.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                receipt = dict(previous)
                if (receipt["item"], receipt["revision"], receipt["body"], receipt["kind"], receipt["channel"]) != (value["number"], revision, body, kind, channel):
                    raise Conflict("request ID was already used for different content")
                return receipt
            # Old-revision feedback is retained, not relabeled as current evidence.
            self._version(db, value["number"], revision)
            if not value["prepared"]:
                raise Conflict("this candidate has not been prepared for review")
            receipt = {"id": str(uuid.uuid4()), "request_id": request_id, "item": value["number"],
                       "revision": revision, "body": body, "kind": kind, "channel": channel,
                       "state": "submitted", "claimed_by": None, "created": now(),
                       "queue": json.dumps({"state": "not_requested"})}
            db.execute("INSERT INTO submissions VALUES (:id,:request_id,:item,:revision,:body,:kind,:channel,:state,:claimed_by,:created,:queue)", receipt)
            if channel == "web":
                db.execute("UPDATE drafts SET body='',version=version+1,updated=? WHERE item=? AND revision=? AND body=?",
                           (now(), value["number"], revision, body))
            value["state"] = "with_agent"
            self._put(db, value)
            self._event(db, value["number"], "submitted", {"submission": receipt["id"], "revision": revision})
        self.refresh()
        return receipt

    def submit_file(self, item: str, revision: int | None = None, kind: str = "feedback") -> dict:
        with self.transaction() as db:
            value = self._item(db, item)
            revision = revision or value["revision"]
            version = self._version(db, value["number"], revision)
            reply, error = self._file_reply(version)
            if error:
                raise Conflict(error)
            key = f"file:{self._meta(db, 'workspace_id')}:{value['number']}:{revision}:{kind}:{digest(reply)}"
        return self.submit(item, revision, reply, key, kind=kind, channel="file")

    def claim(self, submission: str, thread: str) -> dict:
        with self.transaction() as db:
            self.owner(db, thread)
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission,)).fetchone()
            if not row:
                raise InboxError("unknown submission")
            value = dict(row)
            claimed_now = value["state"] == "submitted"
            if claimed_now:
                db.execute("UPDATE submissions SET state='claimed',claimed_by=? WHERE id=?", (thread, submission))
                self._event(db, value["item"], "claimed", {"submission": submission, "thread": thread})
                value.update(state="claimed", claimed_by=thread)
            value["claimed_now"] = claimed_now
            value["current_revision"] = self._item(db, value["item"])["revision"]
            value["sources"] = self.source_status(self._version(db, value["item"], value["revision"])["sources"])
            outcome = db.execute("SELECT doc FROM outcomes WHERE submission=?", (submission,)).fetchone()
            value["outcome"] = json.loads(outcome[0]) if outcome else None
        self.refresh()
        return value

    def outcome(self, submission: str, result: dict, thread: str) -> dict:
        body = text(result.get("text"), "outcome text")
        disposition = result.get("disposition")
        if disposition not in DISPOSITIONS:
            raise InboxError(f"disposition must be one of {sorted(DISPOSITIONS)}")
        references = result.get("references", [])
        if not isinstance(references, list) or len(references) > 30:
            raise InboxError("references must be a list of at most 30 evidence pointers")
        for pointer in references:
            text(pointer, "reference", limit=2000)
        review = text(result.get("source_review"), "source_review")
        with self.transaction() as db:
            self.owner(db, thread)
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission,)).fetchone()
            if not row:
                raise InboxError("unknown submission")
            receipt = dict(row)
            previous = db.execute("SELECT doc FROM outcomes WHERE submission=?", (submission,)).fetchone()
            if previous:
                saved = json.loads(previous[0])
                if (saved["text"], saved["disposition"], saved["references"], saved["source_review"]) != (body, disposition, references, review):
                    raise Conflict("an immutable outcome already exists for this submission")
                return saved
            if receipt["state"] != "claimed":
                raise Conflict("claim the submission and inspect its state before recording an outcome")
            value = self._item(db, receipt["item"])
            version = self._version(db, receipt["item"], receipt["revision"])
            result = {"submission": submission, "item": value["id"], "revision": receipt["revision"],
                      "current_revision": value["revision"], "text": body, "disposition": disposition,
                      "references": references, "source_review": review, "sources": self.source_status(version["sources"]),
                      "thread": thread, "created": now()}
            db.execute("INSERT INTO outcomes VALUES (?,?)", (submission, json.dumps(result, ensure_ascii=False)))
            db.execute("UPDATE submissions SET state='resolved' WHERE id=?", (submission,))
            value["state"] = "with_agent" if self._pending(db, value["number"]) else ("ready" if disposition in {"explained", "follow_up"} else "resolved")
            value["state"] = self._attention_state(value["state"], self._revision_work(db, value["number"]))
            self._put(db, value)
            self._event(db, value["number"], "outcome", {"submission": submission, "disposition": disposition})
        self.refresh()
        return result

    def get(self, item: str | int, revision: int | None = None) -> dict:
        with self.transaction() as db:
            value = self._item(db, item)
            revision = revision or value["revision"]
            version = self._version(db, value["number"], revision)
            metadata = json.loads(version["metadata"])
            for key in ("title", "summary", "why_now", "kind"):
                value[key] = metadata[key]
            value["viewed_revision"] = revision
            value["brief"] = version["body"]
            value["sources"] = [{k: v for k, v in source.items() if k != "content"} for source in version["sources"]]
            value["source_status"] = self.source_status(version["sources"])
            value["drafts"] = self._drafts(db, version)
            value["revisions"] = self._revision_work(db, value["number"])
            value["state"] = self._attention_state(value["state"], value["revisions"])
            value["published_mtime_ns"] = version["published_mtime_ns"]
            path = self.brief_path(value["number"], revision)
            value["observed_mtime_ns"] = str(path.stat().st_mtime_ns) if path.exists() else None
            value["brief_path"] = str(path.relative_to(self.workspace))
            value["submissions"] = [dict(row) for row in db.execute("SELECT * FROM submissions WHERE item=? ORDER BY rowid", (value["number"],))]
            value["outcomes"] = [json.loads(row[0]) for row in db.execute("SELECT o.doc FROM outcomes o JOIN submissions s ON s.id=o.submission WHERE s.item=? ORDER BY s.rowid", (value["number"],))]
            value["events"] = [dict(row) for row in db.execute("SELECT * FROM events WHERE item=? ORDER BY seq", (value["number"],))]
            return value

    def source(self, item: str, revision: int, index: int, live: bool = False) -> tuple[bytes, str]:
        with self.transaction() as db:
            value = self._item(db, item)
            sources = self._version(db, value["number"], revision)["sources"]
            number(index, "source index", 0, len(sources) - 1)
            source = sources[index]
            content = self._source_file(source["path"]).read_bytes() if live else base64.b64decode(source["content"])
            return content, source["mime"]

    def snapshot(self) -> dict:
        with self.transaction() as db:
            items = [json.loads(row[0]) for row in db.execute("SELECT doc FROM items")]
            for item in items:
                version = self._version(db, item["number"], item["revision"])
                drafts = self._drafts(db, version)
                revisions = self._revision_work(db, item["number"])
                item["has_draft"] = any(entry["has_draft"] for entry in revisions)
                item["draft_revisions"] = [entry["revision"] for entry in revisions if entry["has_draft"]]
                item["file_error"] = drafts["file_error"]
                item["state"] = self._attention_state(item["state"], revisions)
                item["published_mtime_ns"] = version["published_mtime_ns"]
                path = self.brief_path(item["number"], item["revision"])
                item["observed_mtime_ns"] = str(path.stat().st_mtime_ns) if path.exists() else None
                item["brief_path"] = str(path.relative_to(self.root))
            items.sort(key=lambda item: (not item["blocking"], item["state"] != "active", not item["has_draft"], item["priority"], item["number"]))
            return {"workspace_id": self._meta(db, "workspace_id"), "workspace": str(self.workspace),
                    "thread": self._meta(db, "thread"), "items": items, "pending": self._pending(db),
                    "event": db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]}

    def refresh(self) -> None:
        """Regenerate indexes and missing projections; never replace a reply file."""
        with self.transaction() as db:
            for row in db.execute("SELECT * FROM versions ORDER BY item,revision").fetchall():
                version = dict(row)
                path = self.brief_path(version["item"], version["revision"])
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if not path.exists():
                    if version["published_mtime_ns"] is not None:
                        raise InboxError(f"published brief is missing: {path}; restore it from backup before refresh (unsubmitted file edits are not recoverable from receipts)")
                    # A committed version can outlive a crash before its file is written.
                    try:
                        with path.open("x", encoding="utf-8", newline="\n") as output:
                            output.write(self._prefix(version))
                            output.flush()
                            os.fsync(output.fileno())
                    except FileExistsError:
                        pass  # An editor or another helper created it first; retain it.
                if version["published_mtime_ns"] is None:
                    db.execute("UPDATE versions SET published_mtime_ns=? WHERE item=? AND revision=?",
                               (str(path.stat().st_mtime_ns), version["item"], version["revision"]))
            for receipt in db.execute("SELECT * FROM submissions ORDER BY rowid").fetchall():
                directory = self.root / "items" / label(receipt["item"]) / "submissions"
                directory.mkdir(mode=0o700, exist_ok=True)
                atomic_write(directory / f"{receipt['id']}.md", f"# {label(receipt['item'])} -- human {receipt['kind']}\n\nSubmission: `{receipt['id']}`; reviewed revision: {receipt['revision']}.\n\n{receipt['body']}\n")
            for row in db.execute("SELECT doc FROM outcomes").fetchall():
                outcome = json.loads(row[0])
                directory = self.root / "items" / outcome["item"] / "outcomes"
                directory.mkdir(mode=0o700, exist_ok=True)
                atomic_write(directory / f"{outcome['submission']}.md", f"# {outcome['item']} -- {outcome['disposition']}\n\n{outcome['text']}\n\n## Source review\n\n{outcome['source_review']}\n\n## Evidence\n\n" + "\n".join(f"- {ref}" for ref in outcome["references"]) + "\n")
        # Render under the same serialization boundary as updates; stale indexes
        # are harmless and can always be reconstructed from the database.
        snapshot = self.snapshot()
        with self.transaction() as db:
            if snapshot["event"] != db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]:
                return  # Another writer will render its newer event; readers use SQLite.
            def card(item: dict) -> str:
                title = item["title"].replace("\n", " ").replace("[", "\\[").replace("]", "\\]")
                return (f"- **[{item['id']} -- {title}]({item['brief_path']})** -- {item['state']}"
                        f"{' -- BLOCKER' if item['blocking'] else ''}\n  {item['summary']}\n"
                        f"  Why now: {item['why_now']}\n"
                        f"  Published filesystem mtime_ns: `{item['published_mtime_ns']}`; observed: `{item['observed_mtime_ns']}`.\n")
            items = snapshot["items"]
            ready = [item for item in items if item["state"] in {"ready", "active"}]
            spotlight = [item for item in ready if item["blocking"] or item["state"] == "active" or item["has_draft"]]
            ordinary = [item for item in ready if item not in spotlight]
            top = spotlight + ordinary[:3]
            sections = [("Needs you", top), ("Later", ordinary[3:] + [item for item in items if item["state"] in {"candidate", "deferred"}]),
                        ("With agent", [item for item in items if item["state"] == "with_agent"]),
                        ("Closed", [item for item in items if item["state"] in {"resolved", "retired"}])]
            lines = ["# Human inbox\n", "Generated view. Edit a brief's # Reply, then submit explicitly. A save is not a submission.\n"]
            for heading, selected in sections:
                lines.extend([f"## {heading}\n", "\n".join(card(item) for item in selected) or "Nothing here.\n"])
            atomic_write(self.root / "INBOX.md", "\n".join(lines))
            atomic_write(self.root / "DECISIONS.md", "# Consequential decisions\n\nStable IDs, not rank numbers. Settled choices remain reviewable.\n\n" + "\n".join(card(item) for item in items if item["decision"]))

    def hook(self, payload: dict) -> dict:
        event = payload.get("hook_event_name")
        if event not in {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}:
            return {}
        with self.transaction() as db:
            thread = payload.get("session_id")
            if thread != self._meta(db, "thread"):
                return {}
            pending = self._pending(db)
            recovery = event in {"SessionStart", "UserPromptSubmit", "Stop"}
            unseen = [receipt for receipt in pending if recovery or not db.execute("SELECT 1 FROM notices WHERE thread=? AND submission=?", (thread, receipt["id"])).fetchone()]
            if not unseen and event != "SessionStart":
                return {}
            for receipt in unseen:
                db.execute("INSERT OR IGNORE INTO notices VALUES (?,?)", (thread, receipt["id"]))
            ids = ", ".join(f"{label(receipt['item'])}/{receipt['id']} ({receipt['state']})" for receipt in unseen[:5])
            message = (f"OPL human inbox: {len(pending)} submission(s) await disposition. "
                       f"Read {self.root / 'INBOX.md'} and use $opl:human-collaboration pending before related commitments or completion. "
                       f"{ids} Do not replay already-claimed effects; inspect their evidence. No human inbox action grants a permission exception.")
            if event == "Stop":
                return {"systemMessage": message}
            return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}
