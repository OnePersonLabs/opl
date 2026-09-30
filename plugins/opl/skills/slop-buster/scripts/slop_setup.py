"""Initialize Slop Buster's local configuration and evidence repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from slop_config import config_file, discover_source_homes, load_config, DEFAULT_DATA_REPO


def _write_initial_config(path: Path) -> None:
    homes = discover_source_homes()
    if not homes:
        raise ValueError("No Codex source home found; set source_homes in a config file")

    def quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f"data_repo = {quote(DEFAULT_DATA_REPO)}",
        "source_homes = [" + ", ".join(quote(home) for home in homes) + "]",
        "deadline_seconds = 1800",
        "",
        "[models.orchestrator]",
        'name = "gpt-6-sol"',
        'effort = "medium"',
        "",
        "[models.reader]",
        'name = "gpt-5.6-luna"',
        'effort = "medium"',
        "",
        "[models.synthesis]",
        'name = "gpt-6-sol"',
        'effort = "high"',
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def setup(config_path: str | None = None, *, dry_run: bool = False) -> dict:
    path = config_file(config_path)
    if not path.exists():
        if dry_run:
            return {"config": str(path), "status": "would create config"}
        _write_initial_config(path)

    config = load_config(str(path))
    repo = Path(config["data_repo"])
    status = "ready"
    if not repo.exists():
        if dry_run:
            return {"config": str(path), "data_repo": str(repo), "status": "would initialize data repository"}
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
        status = "initialized data repository"
    elif not (repo / ".git").exists():
        raise ValueError(f"Existing data_repo is not a Git repository: {repo}")

    ignore = repo / ".gitignore"
    entries = {line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()} if ignore.exists() else set()
    additions = [entry for entry in (".runtime/", "index/", "feedback/") if entry not in entries]
    if additions and dry_run:
        status = "would update data repository ignore rules"
    elif additions:
        with ignore.open("a", encoding="utf-8") as stream:
            if ignore.exists() and ignore.stat().st_size:
                stream.write("\n")
            stream.write("\n".join(additions) + "\n")

    return {"config": str(path), "data_repo": str(repo), "status": status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(setup(args.config, dry_run=args.dry_run)))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Slop Buster setup failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
