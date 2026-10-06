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

SCHEMA = 3
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
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 1:
                self._migrate(connection)
                self._migrate_questions(connection)
            elif version == 2:
                self._migrate_questions(connection)
            elif version != SCHEMA:
                raise InboxError("unsupported human inbox schema; keep the files and use the matching helper")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init(self, thread: str, title: str | None = None) -> dict:
        text(thread, "root thread", limit=200)
        if title is not None:
            text(title, "session title", limit=2000)
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.db_path.exists():
            with self.transaction() as db:
                self._register_session(db, thread, title)
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
                CREATE TABLE sessions (thread TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT NOT NULL);
                CREATE TABLE versions (
                    item INTEGER NOT NULL REFERENCES items(id), revision INTEGER NOT NULL,
                    body TEXT NOT NULL, sources TEXT NOT NULL, metadata TEXT NOT NULL, published_mtime_ns TEXT,
                    PRIMARY KEY (item, revision));
                CREATE TABLE drafts (
                    item INTEGER NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    version INTEGER NOT NULL, updated TEXT NOT NULL, answers TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (item, revision),
                    FOREIGN KEY (item, revision) REFERENCES versions(item, revision));
                CREATE TABLE submissions (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    item INTEGER NOT NULL, revision INTEGER NOT NULL,
                    body TEXT NOT NULL, kind TEXT NOT NULL, channel TEXT NOT NULL,
                    state TEXT NOT NULL, claimed_by TEXT, created TEXT NOT NULL,
                    queue TEXT NOT NULL, answers TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (item, revision) REFERENCES versions(item, revision));
                CREATE TABLE outcomes (
                    submission TEXT PRIMARY KEY REFERENCES submissions(id),
                    doc TEXT NOT NULL);
                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, item INTEGER,
                    action TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE notices (thread TEXT NOT NULL, submission TEXT NOT NULL,
                    PRIMARY KEY (thread, submission));
                CREATE TABLE questions (item INTEGER NOT NULL, revision INTEGER NOT NULL,
                    qid TEXT NOT NULL, state TEXT NOT NULL, answer TEXT, reason TEXT, updated TEXT NOT NULL,
                    PRIMARY KEY(item,revision,qid), FOREIGN KEY(item,revision) REFERENCES versions(item,revision));
                PRAGMA user_version = 3;
            """)
            db.executemany("INSERT INTO meta VALUES (?, ?)", [
                ("workspace_id", str(uuid.uuid4())), ("thread", thread), ("created", now())])
            self._register_session(db, thread, title)
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

    def _migrate(self, db: sqlite3.Connection) -> None:
        """Keep all existing payloads and claims; assign their original root."""
        thread = self._meta(db, "thread")
        db.execute("CREATE TABLE sessions (thread TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL)")
        self._register_session(db, thread)
        for row in db.execute("SELECT id,doc FROM items").fetchall():
            value = json.loads(row["doc"])
            value["owner_thread"] = thread
            db.execute("UPDATE items SET doc=? WHERE id=?", (json.dumps(value, ensure_ascii=False), row["id"]))
        db.execute("PRAGMA user_version = 2")

    @staticmethod
    def _migrate_questions(db: sqlite3.Connection) -> None:
        db.execute("ALTER TABLE drafts ADD COLUMN answers TEXT NOT NULL DEFAULT '{}'")
        db.execute("ALTER TABLE submissions ADD COLUMN answers TEXT NOT NULL DEFAULT '{}'")
        db.execute("CREATE TABLE questions (item INTEGER NOT NULL, revision INTEGER NOT NULL, qid TEXT NOT NULL, state TEXT NOT NULL, answer TEXT, reason TEXT, updated TEXT NOT NULL, PRIMARY KEY(item,revision,qid), FOREIGN KEY(item,revision) REFERENCES versions(item,revision))")
        db.execute("PRAGMA user_version = 3")

    @staticmethod
    def _register_session(db: sqlite3.Connection, thread: str, title: str | None = None) -> None:
        stamp = now()
        db.execute("INSERT INTO sessions VALUES (?,?,?,?) ON CONFLICT(thread) DO UPDATE SET title=COALESCE(?,sessions.title),updated=excluded.updated",
                   (thread, title or thread, stamp, stamp, title))

    def owner(self, db: sqlite3.Connection, thread: str | None, item: dict | None = None) -> None:
        if not thread or not db.execute("SELECT 1 FROM sessions WHERE thread=?", (thread,)).fetchone():
            raise Conflict("invoke $opl:human-collaboration to enroll this root before using root-owned operations")
        if item is not None and item["owner_thread"] != thread:
            raise Conflict(f"item belongs to {item['owner_thread']}; inspect ownership before a targeted bind")

    def session(self, db: sqlite3.Connection, thread: str | None = None) -> str:
        if thread is None:
            rows = db.execute("SELECT thread FROM sessions").fetchall()
            if len(rows) != 1:
                raise Conflict("choose a session; this workspace has more than one root")
            return rows[0][0]
        self.owner(db, thread)
        return thread

    def enrich(self, db: sqlite3.Connection, value: dict) -> dict:
        thread = value["owner_thread"]
        value.update(workspace_id=self._meta(db, "workspace_id"), workspace=str(self.workspace),
                     session=f"{self._meta(db, 'workspace_id')}/{thread}",
                     session_title=db.execute("SELECT title FROM sessions WHERE thread=?", (thread,)).fetchone()[0])
        return value

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
        body = version["body"].rstrip()
        questions = json.loads(version["metadata"]).get("questions", [])
        if questions:
            body += "\n\n## Questions\n\n" + "\n\n".join(
                f"### {question['prompt']}\n\nQuestion ID: `{question['id']}`\n\n" +
                "\n".join(f"{index + 1}. {option}{' (Recommended)' if index == 0 else ''}" for index, option in enumerate(question["options"])) +
                "\n\nYou can also write a free-text answer in Reply."
                for question in questions)
        return body + "\n\n# Reply\n\n"

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
        row = db.execute("SELECT body,version,updated,answers FROM drafts WHERE item=? AND revision=?",
                         (version["item"], version["revision"])).fetchone()
        web = dict(row) if row else {"body": "", "version": 0, "updated": None, "answers": "{}"}
        web["answers"] = json.loads(web["answers"])
        reply, error = self._file_reply(version)
        previous = db.execute("SELECT body FROM submissions WHERE item=? AND revision=? AND channel='file' ORDER BY rowid DESC LIMIT 1",
                              (version["item"], version["revision"])).fetchone()
        file_pending = bool(reply.strip()) and (not previous or reply != previous[0])
        return {"web": web, "file": reply, "file_pending": file_pending, "file_error": error,
                "pending": bool(web["body"].strip()) or bool(web["answers"]) or file_pending}

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
        value["questions"] = self._question_definitions(spec.get("questions", []))
        body = text(spec.get("brief"), "brief").replace("\r\n", "\n").replace("\r", "\n")
        sources = self.capture_sources(spec.get("sources", []))
        return value, body, sources

    @staticmethod
    def _question_definitions(value: Any) -> list[dict]:
        if not isinstance(value, list):
            raise InboxError("questions must be a list")
        result, identifiers = [], set()
        for question in value:
            if not isinstance(question, dict):
                raise InboxError("each question must be an object")
            identifier = text(question.get("id"), "question ID", limit=200)
            if identifier in identifiers:
                raise InboxError("question IDs must be unique within a brief revision")
            identifiers.add(identifier)
            options = question.get("options")
            if not isinstance(options, list) or len(options) != 3:
                raise InboxError("each question must have three options; the first is recommended")
            result.append({"id": identifier, "prompt": text(question.get("prompt"), "question prompt"),
                           "options": [text(option, "question option") for option in options]})
        text(json.dumps(result, ensure_ascii=False), "questions", empty=True)
        return result

    @staticmethod
    def _insert_questions(db: sqlite3.Connection, item: dict) -> None:
        db.executemany("INSERT INTO questions(item,revision,qid,state,updated) VALUES (?,?,?,'open',?)",
                       [(item["number"], item["revision"], question["id"], now()) for question in item.get("questions", [])])

    def _questions(self, db: sqlite3.Connection, item: int, revision: int) -> list[dict]:
        definitions = json.loads(self._version(db, item, revision)["metadata"]).get("questions", [])
        result = []
        for definition in definitions:
            row = db.execute("SELECT state,answer,reason FROM questions WHERE item=? AND revision=? AND qid=?", (item, revision, definition["id"])).fetchone()
            if row is None:
                raise InboxError("question state is missing; retain this inbox for inspection")
            question = {**definition, "state": row["state"]}
            if row["answer"] is not None:
                question["answer"] = json.loads(row["answer"])
            if row["reason"] is not None:
                question["reason"] = row["reason"]
            result.append(question)
        return result

    def _answers(self, db: sqlite3.Connection, item: int, revision: int, answers: Any) -> dict:
        if answers is None:
            return {}
        if not isinstance(answers, dict):
            raise InboxError("answers must be an object keyed by question ID")
        known = {question["id"] for question in self._questions(db, item, revision)}
        result = {}
        for identifier, answer in answers.items():
            if identifier not in known:
                raise InboxError(f"unknown question ID for this brief revision: {identifier}")
            if not isinstance(answer, dict):
                raise InboxError("each answer must contain one option or free-text reply")
            if set(answer) == {"option"}:
                result[identifier] = {"option": number(answer["option"], "answer option", 0, 2)}
            elif set(answer) == {"text"}:
                result[identifier] = {"text": text(answer["text"], "answer text")}
            else:
                raise InboxError("each answer must contain one option or free-text reply")
        text(json.dumps(result, ensure_ascii=False), "answers", empty=True)
        return result

    @staticmethod
    def _receipt(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["answers"] = json.loads(result["answers"])
        return result

    @staticmethod
    def _answer_text(questions: list[dict], answers: dict) -> str:
        return "\n\n".join(f"{question['prompt']}\n" +
                            (question["options"][answers[question["id"]]["option"]] if "option" in answers[question["id"]] else answers[question["id"]]["text"])
                            for question in questions if question["id"] in answers)

    def _question_attention(self, db: sqlite3.Connection, value: dict, revisions: list[dict]) -> str:
        state = self._attention_state(value["state"], revisions)
        if self._pending(db, value["number"]):
            return "with_agent"
        if value.get("human_follow_up"):
            # A free-text question is separate from structured question states.
            # Keep the human's active/deferred focus and explicit retirement.
            return "ready" if state in {"resolved", "answer_assumed"} else state
        questions = self._questions(db, value["number"], value["revision"])
        work_in_progress = any(entry["has_draft"] or entry["file_error"] for entry in revisions)
        if questions and value["prepared"] and state not in {"retired", "candidate"}:
            if state == "resolved" and any(question["state"] == "open" for question in questions):
                return "ready"
            if all(question["state"] != "open" for question in questions) and any(
                    question["state"] == "answer_assumed" for question in questions) and not work_in_progress:
                return "answer_assumed"
            if state == "answer_assumed" and work_in_progress:
                return "ready"
        return state

    def assume(self, item: str, questions: list[str], reason: str, thread: str, revision: int | None = None) -> dict:
        text(reason, "assumption reason")
        if not questions or len(set(questions)) != len(questions):
            raise InboxError("choose one or more distinct question IDs")
        with self.transaction() as db:
            value = self._item(db, item)
            self.owner(db, thread, value)
            revision = value["revision"] if revision is None else revision
            if revision != value["revision"]:
                raise Conflict("inspect the current brief revision before assuming its recommendation")
            if value["blocking"]:
                raise Conflict("blocking questions require a human answer; a recommendation cannot be assumed")
            if not value["prepared"] or value["state"] in {"retired", "resolved"}:
                raise Conflict("only a prepared, open contribution can use a recommendation assumption")
            if self._pending(db, value["number"]):
                raise Conflict("address unresolved human submissions before assuming a recommendation")
            states = {question["id"]: question for question in self._questions(db, value["number"], revision)}
            for identifier in questions:
                question = states.get(identifier)
                if question is None:
                    raise InboxError(f"unknown question ID for this brief revision: {identifier}")
                if question["state"] == "answered":
                    raise Conflict("a human answer already exists; inspect it instead of assuming a recommendation")
                if question["state"] == "answer_assumed":
                    if question.get("reason") != reason:
                        raise Conflict("this recommendation was already assumed with another reason; inspect its history")
                    continue
                stamp = now()
                db.execute("UPDATE questions SET state='answer_assumed',answer=?,reason=?,updated=? WHERE item=? AND revision=? AND qid=?",
                           (json.dumps({"option": 0}), reason, stamp, value["number"], revision, identifier))
                self._event(db, value["number"], "answer_assumed", {"revision": revision, "question": identifier, "reason": reason, "thread": thread})
            value["state"] = self._question_attention(db, value, self._revision_work(db, value["number"]))
            self._put(db, value)
        self.refresh()
        return self.get(item)

    def publish(self, spec: dict, thread: str) -> dict:
        value, body, sources = self._spec(spec)
        with self.transaction() as db:
            self.owner(db, thread)
            identifier = db.execute("INSERT INTO items(doc) VALUES ('{}')").lastrowid
            value.update(number=identifier, id=label(identifier), revision=1, created=now(), owner_thread=thread)
            self._put(db, value)
            db.execute("INSERT INTO versions(item,revision,body,sources,metadata) VALUES (?,?,?,?,?)",
                       (identifier, 1, body, json.dumps(sources), json.dumps(value)))
            self._insert_questions(db, value)
            self._event(db, identifier, "published", {"revision": 1})
        self.refresh()
        return self.get(value["id"])

    def contribute(self, title: str, body: str, request_id: str, thread: str | None = None) -> dict:
        """Create a human-initiated thread and its receipt in one transaction."""
        text(title, "title", limit=2000)
        text(body, "contribution")
        text(request_id, "request ID", limit=200)
        with self.transaction() as db:
            thread = self.session(db, thread)
            previous = db.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                receipt = self._receipt(previous)
                item = self._item(db, receipt["item"])
                if not item.get("human_initiated") or item["title"] != title or receipt["body"] != body or item["owner_thread"] != thread:
                    raise Conflict("request ID was already used for different content")
                return receipt
            identifier = db.execute("INSERT INTO items(doc) VALUES ('{}')").lastrowid
            value = {"number": identifier, "id": label(identifier), "revision": 1,
                     "title": title, "summary": "A contribution initiated by you, not an agent assignment.",
                     "why_now": "The root needs to assess this contribution and its downstream effects.",
                     "kind": "human contribution", "priority": 50, "blocking": False,
                     "decision": False, "human_initiated": True, "prepared": True,
                     "state": "with_agent", "created": now(), "owner_thread": thread}
            self._put(db, value)
            brief = "# Human-initiated contribution\n\n" + title + "\n\nNo agent-authored premise or source snapshot was supplied. Establish context before treating this as an architectural decision."
            db.execute("INSERT INTO versions(item,revision,body,sources,metadata) VALUES (?,?,?,?,?)",
                       (identifier, 1, brief, "[]", json.dumps(value)))
            receipt = {"id": str(uuid.uuid4()), "request_id": request_id, "item": identifier,
                       "revision": 1, "body": body, "kind": "feedback", "channel": "web",
                       "state": "submitted", "claimed_by": None, "created": now(),
                       "queue": json.dumps({"state": "not_requested"}), "answers": {}}
            db.execute("INSERT INTO submissions(id,request_id,item,revision,body,kind,channel,state,claimed_by,created,queue) VALUES (:id,:request_id,:item,:revision,:body,:kind,:channel,:state,:claimed_by,:created,:queue)", receipt)
            self._event(db, identifier, "human_initiated", {"submission": receipt["id"]})
        self.refresh()
        return receipt

    def revise(self, item: str, spec: dict, reason: str, thread: str) -> dict:
        text(reason, "reason")
        changes, body, sources = self._spec(spec)
        with self.transaction() as db:
            value = self._item(db, item)
            self.owner(db, thread, value)
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
            self._insert_questions(db, value)
            self._event(db, value["number"], "revised", {"reason": reason, "revision": value["revision"]})
        self.refresh()
        return self.get(item)

    def bind(self, thread: str, reason: str, previous: str | None = None) -> dict:
        text(thread, "thread", limit=200)
        text(reason, "handoff reason")
        with self.transaction() as db:
            # Handoff transfers work; enrollment belongs to the explicit init workflow.
            self.owner(db, thread)
            previous = self.session(db, previous)
            for row in db.execute("SELECT doc FROM items").fetchall():
                value = json.loads(row[0])
                if value["owner_thread"] == previous:
                    value["owner_thread"] = thread
                    self._put(db, value)
            if previous != thread:
                db.execute("DELETE FROM sessions WHERE thread=?", (previous,))
            if self._meta(db, "thread") == previous:
                db.execute("UPDATE meta SET value=? WHERE key='thread'", (thread,))
            self._event(db, None, "root_handoff", {"from": previous, "to": thread, "reason": reason})
        return {"thread": thread, "previous": previous, "note": "inspect already-claimed work before resuming effects"}

    @staticmethod
    def _pending(db: sqlite3.Connection, item: int | None = None, thread: str | None = None) -> list[dict]:
        sql = "SELECT * FROM submissions WHERE state != 'resolved'"
        rows = db.execute(sql + (" AND item=?" if item else "") + " ORDER BY rowid", (item,) if item else ())
        result = [Inbox._receipt(row) for row in rows]
        if thread is not None:
            owned = {row[0] for row in db.execute("SELECT id FROM items WHERE json_extract(doc,'$.owner_thread')=?", (thread,))}
            result = [row for row in result if row["item"] in owned]
        return result

    def move(self, item: str, action: str, reason: str = "", priority: int | None = None, thread: str | None = None) -> dict:
        with self.transaction() as db:
            value = self._item(db, item)
            if thread is not None:
                self.owner(db, thread, value)
            revisions = self._revision_work(db, value["number"])
            value["state"] = self._attention_state(value["state"], revisions)
            if action in {"rank", "retire"}:
                self.owner(db, thread, value)
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
                    self.owner(db, thread, value)
                    value["prepared"] = True
                value["state"] = {"later": "deferred", "ready": "ready", "retire": "retired"}[action]
            else:
                raise InboxError("unknown queue action")
            self._put(db, value)
            self._event(db, value["number"], action, {"reason": reason, "priority": priority})
        self.refresh()
        return self.get(item)

    def save_draft(self, item: str, revision: int, body: str, expected: int, answers: dict | None = None) -> dict:
        body = "" if body is None else body
        text(body, "draft", empty=True)
        number(expected, "expected draft version", 0, 2**53 - 1)
        with self.transaction() as db:
            value = self._item(db, item)
            self._version(db, value["number"], revision)
            answers = self._answers(db, value["number"], revision, answers)
            row = db.execute("SELECT version FROM drafts WHERE item=? AND revision=?", (value["number"], revision)).fetchone()
            actual = row[0] if row else 0
            if actual != expected:
                raise Conflict("another device saved a newer draft; copy your local text before reconciling")
            stamp = now()
            if (body.strip() or answers) and value["state"] in {"resolved", "retired", "answer_assumed"}:
                value["state"] = "ready"
                self._put(db, value)
            self._event(db, value["number"], "draft_saved", {"revision": revision, "version": actual + 1})
            db.execute("INSERT INTO drafts(item,revision,body,version,updated,answers) VALUES (?,?,?,?,?,?) ON CONFLICT(item,revision) DO UPDATE SET body=excluded.body,version=excluded.version,updated=excluded.updated,answers=excluded.answers",
                       (value["number"], revision, body, actual + 1, stamp, json.dumps(answers, sort_keys=True)))
        self.refresh()
        return {"body": body, "version": actual + 1, "updated": stamp, "answers": answers}

    def submit(self, item: str, revision: int, body: str, request_id: str, *, kind: str = "feedback", channel: str = "web", answers: dict | None = None) -> dict:
        body = "" if body is None else body
        text(body, "reply", empty=True)
        text(request_id, "request ID", limit=200)
        if kind not in {"feedback", "question"} or channel not in {"web", "file"}:
            raise InboxError("invalid submission kind or channel")
        with self.transaction() as db:
            value = self._item(db, item)
            answers = self._answers(db, value["number"], revision, answers)
            if not body.strip() and not answers:
                raise InboxError("send a nonempty reply or at least one question answer")
            previous = db.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                receipt = self._receipt(previous)
                if (receipt["item"], receipt["revision"], receipt["body"], receipt["kind"], receipt["channel"], receipt["answers"]) != (value["number"], revision, body, kind, channel, answers):
                    raise Conflict("request ID was already used for different content")
                return receipt
            # Old-revision feedback is retained, not relabeled as current evidence.
            self._version(db, value["number"], revision)
            if not value["prepared"]:
                raise Conflict("this candidate has not been prepared for review")
            receipt = {"id": str(uuid.uuid4()), "request_id": request_id, "item": value["number"],
                       "revision": revision, "body": body, "kind": kind, "channel": channel,
                       "state": "submitted", "claimed_by": None, "created": now(),
                       "queue": json.dumps({"state": "not_requested"}), "answers": answers}
            encoded_answers = json.dumps(answers, sort_keys=True)
            db.execute("INSERT INTO submissions(id,request_id,item,revision,body,kind,channel,state,claimed_by,created,queue,answers) VALUES (:id,:request_id,:item,:revision,:body,:kind,:channel,:state,:claimed_by,:created,:queue,:answers)",
                       {**receipt, "answers": encoded_answers})
            for identifier, answer in answers.items():
                db.execute("UPDATE questions SET state='answered',answer=?,reason=NULL,updated=? WHERE item=? AND revision=? AND qid=?",
                           (json.dumps(answer), now(), value["number"], revision, identifier))
            if channel == "web":
                db.execute("UPDATE drafts SET body='',answers='{}',version=version+1,updated=? WHERE item=? AND revision=? AND body=? AND answers=?",
                           (now(), value["number"], revision, body, encoded_answers))
            value["state"] = "with_agent"
            value["human_follow_up"] = False
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
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission,)).fetchone()
            if not row:
                raise InboxError("unknown submission")
            value = self._receipt(row)
            self.owner(db, thread, self._item(db, value["item"]))
            claimed_now = value["state"] == "submitted"
            if claimed_now:
                db.execute("UPDATE submissions SET state='claimed',claimed_by=? WHERE id=?", (thread, submission))
                self._event(db, value["item"], "claimed", {"submission": submission, "thread": thread})
                value.update(state="claimed", claimed_by=thread)
            value["claimed_now"] = claimed_now
            value["current_revision"] = self._item(db, value["item"])["revision"]
            version = self._version(db, value["item"], value["revision"])
            value["sources"] = self.source_status(version["sources"])
            value["questions"] = json.loads(version["metadata"]).get("questions", [])
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
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission,)).fetchone()
            if not row:
                raise InboxError("unknown submission")
            receipt = dict(row)
            self.owner(db, thread, self._item(db, receipt["item"]))
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
            value["human_follow_up"] = disposition in {"explained", "follow_up"}
            value["state"] = "with_agent" if self._pending(db, value["number"]) else ("ready" if disposition in {"explained", "follow_up"} else "resolved")
            value["state"] = self._question_attention(db, value, self._revision_work(db, value["number"]))
            self._put(db, value)
            self._event(db, value["number"], "outcome", {"submission": submission, "disposition": disposition})
        self.refresh()
        return result

    def get(self, item: str | int, revision: int | None = None) -> dict:
        with self.transaction() as db:
            value = self._item(db, item)
            self.enrich(db, value)
            revision = revision or value["revision"]
            version = self._version(db, value["number"], revision)
            metadata = json.loads(version["metadata"])
            for key in ("title", "summary", "why_now", "kind"):
                value[key] = metadata[key]
            value["viewed_revision"] = revision
            value["brief"] = version["body"]
            value["questions"] = self._questions(db, value["number"], revision)
            value["sources"] = [{k: v for k, v in source.items() if k != "content"} for source in version["sources"]]
            value["source_status"] = self.source_status(version["sources"])
            value["drafts"] = self._drafts(db, version)
            value["revisions"] = self._revision_work(db, value["number"])
            value["state"] = self._question_attention(db, value, value["revisions"])
            value["published_mtime_ns"] = version["published_mtime_ns"]
            path = self.brief_path(value["number"], revision)
            value["observed_mtime_ns"] = str(path.stat().st_mtime_ns) if path.exists() else None
            value["brief_path"] = str(path.relative_to(self.workspace))
            value["submissions"] = []
            for row in db.execute("SELECT * FROM submissions WHERE item=? ORDER BY rowid", (value["number"],)):
                receipt = self._receipt(row)
                receipt["questions"] = json.loads(self._version(db, value["number"], receipt["revision"])["metadata"]).get("questions", [])
                value["submissions"].append(receipt)
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

    def snapshot(self, thread: str | None = None) -> dict:
        with self.transaction() as db:
            items = [json.loads(row[0]) for row in db.execute("SELECT doc FROM items")]
            if thread is not None:
                items = [item for item in items if item["owner_thread"] == thread]
            for item in items:
                self.enrich(db, item)
                version = self._version(db, item["number"], item["revision"])
                drafts = self._drafts(db, version)
                revisions = self._revision_work(db, item["number"])
                item["has_draft"] = any(entry["has_draft"] for entry in revisions)
                item["draft_revisions"] = [entry["revision"] for entry in revisions if entry["has_draft"]]
                item["file_error"] = drafts["file_error"]
                item["questions"] = self._questions(db, item["number"], item["revision"])
                item["state"] = self._question_attention(db, item, revisions)
                item["published_mtime_ns"] = version["published_mtime_ns"]
                path = self.brief_path(item["number"], item["revision"])
                item["observed_mtime_ns"] = str(path.stat().st_mtime_ns) if path.exists() else None
                item["brief_path"] = str(path.relative_to(self.root))
            items.sort(key=lambda item: (not item["blocking"], item["state"] != "active", not item["has_draft"], item["priority"], item["number"]))
            sessions = []
            for row in db.execute("SELECT * FROM sessions"):
                if thread is not None and row["thread"] != thread:
                    continue
                owned = [item for item in items if item["owner_thread"] == row["thread"]]
                needs = [item for item in owned if item["state"] in {"ready", "active"}]
                pending = self._pending(db, thread=row["thread"])
                sessions.append({"id": f"{self._meta(db, 'workspace_id')}/{row['thread']}",
                                 "thread": row["thread"], "title": row["title"],
                                 "workspace_id": self._meta(db, "workspace_id"), "workspace": str(self.workspace),
                                 "needs_you": len(needs), "with_agent": len({receipt['item'] for receipt in pending}),
                                 "later": sum(item["state"] in {"deferred", "candidate"} for item in owned),
                                 "assumed": sum(item["state"] == "answer_assumed" for item in owned),
                                 "updated": max([row["updated"], *[item["updated"] for item in owned]]),
                                 "priority": min((item["priority"] for item in needs), default=100)})
            messages = self._messages(db, items)
            return {"workspace_id": self._meta(db, "workspace_id"), "workspace": str(self.workspace),
                    "thread": thread or self._meta(db, "thread"), "items": items, "sessions": sessions, "pending": self._pending(db, thread=thread),
                    "messages": messages,
                    "event": db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]}

    def _messages(self, db: sqlite3.Connection, items: list[dict]) -> list[dict]:
        """Conversation activity comes from durable messages, never draft stamps."""
        messages = []
        for item in items:
            context = {key: item[key] for key in ("workspace_id", "workspace", "session", "session_title")}
            context["item"] = item["id"]
            for row in db.execute("SELECT revision,metadata FROM versions WHERE item=?", (item["number"],)):
                metadata = json.loads(row["metadata"])
                event = db.execute("SELECT created FROM events WHERE item=? AND action IN ('published','revised','human_initiated') AND json_extract(detail,'$.revision')=? ORDER BY seq LIMIT 1", (item["number"], row["revision"])).fetchone()
                if not metadata.get("human_initiated"):
                    messages.append({**context, "id": f"{item['workspace_id']}:brief:{item['number']}:{row['revision']}",
                                     "revision": row["revision"], "title": metadata["title"], "role": "agent",
                                     "text": metadata["summary"][:600], "kind": "brief",
                                     "created": event[0] if event else metadata["created"]})
            for row in db.execute("SELECT * FROM submissions WHERE item=?", (item["number"],)):
                metadata = json.loads(self._version(db, item["number"], row["revision"])["metadata"])
                reply = "\n\n".join(part for part in (row["body"], self._answer_text(metadata.get("questions", []), json.loads(row["answers"]))) if part)
                messages.append({**context, "id": f"{item['workspace_id']}:submission:{row['id']}",
                                 "revision": row["revision"], "title": metadata["title"], "role": "you",
                                 "text": reply[:600], "kind": row["kind"], "created": row["created"]})
                outcome = db.execute("SELECT doc FROM outcomes WHERE submission=?", (row["id"],)).fetchone()
                if outcome:
                    value = json.loads(outcome[0])
                    messages.append({**context, "id": f"{item['workspace_id']}:outcome:{row['id']}",
                                     "revision": row["revision"], "title": metadata["title"], "role": "agent",
                                     "text": value["text"][:600], "kind": value["disposition"], "created": value["created"]})
            for row in db.execute("SELECT seq,detail,created FROM events WHERE item=? AND action='answer_assumed'", (item["number"],)):
                detail = json.loads(row["detail"])
                metadata = json.loads(self._version(db, item["number"], detail["revision"])["metadata"])
                question = next(question for question in metadata["questions"] if question["id"] == detail["question"])
                messages.append({**context, "id": f"{item['workspace_id']}:assumption:{row['seq']}",
                                 "revision": detail["revision"], "title": metadata["title"], "role": "agent",
                                 "text": f"Assumed recommended option for {question['prompt']}: {question['options'][0]}. {detail['reason']}"[:600],
                                 "kind": "answer_assumed", "created": row["created"]})
        messages.sort(key=lambda message: (message["created"], message["id"]), reverse=True)
        return messages

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
                definitions = json.loads(self._version(db, receipt["item"], receipt["revision"])["metadata"]).get("questions", [])
                reply = "\n\n".join(part for part in (receipt["body"], self._answer_text(definitions, json.loads(receipt["answers"]))) if part)
                atomic_write(directory / f"{receipt['id']}.md", f"# {label(receipt['item'])} -- human {receipt['kind']}\n\nSubmission: `{receipt['id']}`; reviewed revision: {receipt['revision']}.\n\n{reply}\n")
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
                        ("Recommendation assumed", [item for item in items if item["state"] == "answer_assumed"]),
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
            if not db.execute("SELECT 1 FROM sessions WHERE thread=?", (thread,)).fetchone():
                return {}
            pending = self._pending(db, thread=thread)
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
