#!/usr/bin/env python3
"""Run one unattended command and queue one Codex continuation on completion."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid


SCHEMA_VERSION = 1
QUEUE_TIMEOUT_SECONDS = 120
TERMINATION_GRACE_SECONDS = 2
FINAL_EXIT_WAIT_SECONDS = 2
TASKKILL_TIMEOUT_SECONDS = 30


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def write_json_atomic(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def resolve_program(program: str) -> str | None:
    if os.path.dirname(program):
        candidate = Path(program).expanduser()
        return str(candidate.resolve()) if candidate.is_file() else None
    return shutil.which(program)


def subprocess_argv(argv: list[str]) -> list[str] | str:
    """Resolve a program and explicitly route Windows command files through cmd."""
    resolved = resolve_program(argv[0])
    if resolved is None:
        raise FileNotFoundError(f"executable not found: {argv[0]}")
    command = [resolved, *argv[1:]]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".bat", ".cmd"}:
        command_line = subprocess.list2cmdline(command)
        # /S strips the first and last quote, so preserve the quoted executable
        # by wrapping the complete command line in one additional quote pair.
        command_processor = os.environ.get("COMSPEC", "cmd.exe")
        return f'{subprocess.list2cmdline([command_processor])} /d /s /c "{command_line}"'
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a command detached and queue one Codex message at its terminal state."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    start = subparsers.add_parser("start", help="validate and start a detached worker")
    start.add_argument("--thread")
    start.add_argument("--timeout-seconds", required=True, type=float)
    start.add_argument("--cwd", default=os.getcwd())
    start.add_argument("--result-root")
    start.add_argument("command", nargs=argparse.REMAINDER)

    worker = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--thread", required=True)
    worker.add_argument("--timeout-seconds", required=True, type=float)
    worker.add_argument("--cwd", required=True)
    worker.add_argument("--result-dir", required=True)
    worker.add_argument("--codex-bin", required=True)
    worker.add_argument("command", nargs=argparse.REMAINDER)

    return parser.parse_args()


def normalized_command(value: list[str]) -> list[str]:
    command = value[1:] if value[:1] == ["--"] else value
    if not command:
        raise ValueError("a command is required after --")
    return command


def validate_timeout(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("--timeout-seconds must be a positive finite number")
    return value


def preflight_queue(codex_bin: str) -> None:
    try:
        result = subprocess.run(
            subprocess_argv([codex_bin, "queue", "--help"]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"codex queue is unavailable: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"codex queue is unavailable: {detail}")


def start_worker(args: argparse.Namespace) -> int:
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required")
    thread = args.thread or os.environ.get("CODEX_THREAD_ID")
    if not thread:
        raise ValueError("--thread or CODEX_THREAD_ID is required")
    timeout_seconds = validate_timeout(args.timeout_seconds)
    cwd = Path(args.cwd).expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError(f"--cwd is not a directory: {cwd}")
    command = normalized_command(args.command)
    codex_requested = os.environ.get("CODEX_BIN", "codex")
    codex_bin = resolve_program(codex_requested)
    if codex_bin is None:
        raise RuntimeError(f"codex queue is unavailable: executable not found: {codex_requested}")
    preflight_queue(codex_bin)

    if args.result_root:
        result_root = Path(args.result_root).expanduser().resolve()
        result_root.mkdir(parents=True, exist_ok=True)
    else:
        result_root = Path(tempfile.gettempdir()) / "opl-long-command-wakeup"
        result_root.mkdir(parents=True, exist_ok=True)
    result_dir = Path(
        tempfile.mkdtemp(
            prefix=f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-",
            dir=result_root,
        )
    ).resolve()
    write_json_atomic(
        result_dir / "status.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "state": "launching",
            "createdAt": utc_now(),
            "queue": {"state": "waiting"},
        },
    )

    worker_args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        "--thread",
        thread,
        "--timeout-seconds",
        str(timeout_seconds),
        "--cwd",
        str(cwd),
        "--result-dir",
        str(result_dir),
        "--codex-bin",
        codex_bin,
        "--",
        *command,
    ]
    popen_options: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": str(cwd),
    }
    if os.name == "nt":
        popen_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_options["start_new_session"] = True
    worker = subprocess.Popen(worker_args, **popen_options)
    print(
        json.dumps(
            {
                "pid": worker.pid,
                "resultDir": str(result_dir),
                "timeoutSeconds": timeout_seconds,
            }
        )
    )
    return 0


def terminate_process_tree(process: subprocess.Popen[bytes]) -> str | None:
    if process.poll() is not None:
        return None
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=TASKKILL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return "taskkill timed out while terminating the command tree"
        except OSError as error:
            return f"taskkill could not terminate the command tree: {error}"
        if result.returncode != 0 and process.poll() is None:
            return f"taskkill exited with code {result.returncode} while the command may still be running"
        return None
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except OSError as error:
        return f"SIGTERM could not terminate the command tree: {error}"
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
        return None
    except subprocess.TimeoutExpired:
        pass
    except OSError as error:
        return f"command wait failed after SIGTERM: {error}"
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return None
    except OSError as error:
        return f"SIGKILL could not terminate the command tree: {error}"
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
        return None
    except subprocess.TimeoutExpired:
        return "command did not exit after SIGKILL"
    except OSError as error:
        return f"command wait failed after SIGKILL: {error}"


def wait_for_final_exit(process: subprocess.Popen[bytes]) -> str | None:
    if process.poll() is not None:
        return None
    try:
        process.wait(timeout=FINAL_EXIT_WAIT_SECONDS)
        return None
    except subprocess.TimeoutExpired:
        return "command did not exit within the final cleanup wait"
    except OSError as error:
        return f"final command wait failed: {error}"


def output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def queue_message(codex_bin: str, thread: str, state: str, result_dir: Path) -> tuple[dict[str, object], str]:
    message = (
        f"Long-running command reached state={state}. "
        f"Inspect the saved artifacts once at {json.dumps(str(result_dir))} and continue the original task. "
        "Do not poll."
    )
    if len(message) > 2048:
        return ({"state": "failed", "error": "queue message would exceed 2048 characters"}, "")
    try:
        result = subprocess.run(
            subprocess_argv([codex_bin, "queue", "--thread", thread, "--message", message]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=QUEUE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = output_text(error.stdout)
        stderr = output_text(error.stderr)
        return ({"state": "failed", "error": "codex queue timed out"}, f"{stdout}{stderr}")
    except OSError as error:
        return ({"state": "failed", "error": str(error)}, "")
    output = f"{result.stdout}{result.stderr}"
    if result.returncode == 0:
        return ({"state": "submitted", "exitCode": 0}, output)
    return ({"state": "failed", "exitCode": result.returncode}, output)


def run_worker(args: argparse.Namespace) -> int:
    timeout_seconds = validate_timeout(args.timeout_seconds)
    command = normalized_command(args.command)
    cwd = Path(args.cwd).resolve(strict=True)
    result_dir = Path(args.result_dir).resolve(strict=True)
    status_path = result_dir / "status.json"
    created_at = utc_now()
    state = "launch_failed"
    exit_code: int | None = None
    signal_number: int | None = None
    timed_out = False
    error: str | None = None
    cleanup_error: str | None = None
    command_pid: int | None = None

    with (result_dir / "stdout.log").open("wb") as stdout, (result_dir / "stderr.log").open("wb") as stderr:
        try:
            command_argv = subprocess_argv(command)
            command_options: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": stdout,
                "stderr": stderr,
                "cwd": str(cwd),
                "close_fds": True,
            }
            if os.name == "nt":
                command_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                command_options["start_new_session"] = True
            process = subprocess.Popen(command_argv, **command_options)
            command_pid = process.pid
            write_json_atomic(
                status_path,
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "state": "running",
                    "createdAt": created_at,
                    "startedAt": utc_now(),
                    "commandPid": process.pid,
                    "queue": {"state": "waiting"},
                },
            )
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup_error = terminate_process_tree(process)
                final_wait_error = wait_for_final_exit(process)
                if cleanup_error is None:
                    cleanup_error = final_wait_error
            exit_code = process.returncode if process.returncode is not None and process.returncode >= 0 else None
            signal_number = -process.returncode if process.returncode is not None and process.returncode < 0 else None
            state = "timed_out" if timed_out else ("success" if process.returncode == 0 else "failed")
        except OSError as launch_error:
            error = str(launch_error)

    status: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "state": state,
        "createdAt": created_at,
        "finishedAt": utc_now(),
        "exitCode": exit_code,
        "signal": signal_number,
        "timedOut": timed_out,
        "queue": {"state": "pending-submission"},
    }
    if command_pid is not None:
        status["commandPid"] = command_pid
    if error is not None:
        status["error"] = error
    if timed_out:
        status["cleanup"] = ({"state": "root-exited"} if cleanup_error is None else {"state": "failed", "error": cleanup_error})
    queue_log_path = result_dir / "queue.log"
    queue_log_path.write_text("", encoding="utf-8")
    write_json_atomic(status_path, status)
    queue, queue_output = queue_message(args.codex_bin, args.thread, state, result_dir)
    queue_log_path.write_text(queue_output, encoding="utf-8")
    status["queue"] = queue
    write_json_atomic(status_path, status)
    return 0


def main() -> int:
    args = parse_args()
    try:
        if args.mode == "start":
            return start_worker(args)
        return run_worker(args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"run_and_wake: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
