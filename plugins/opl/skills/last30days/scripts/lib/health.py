"""Typed source health for dependencies and retrieval sources.

The status vocabulary distinguishes absent, broken, timed-out, and degraded
dependencies so diagnostics can prescribe the corresponding repair.

It complements ``preflight.py`` (which gates doomed *queries*); this gates
doomed *sources/tools*.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Health states, best to worst.
OK = "ok"
DEGRADED = "degraded"        # ran, but returned less than expected
MISSING = "missing"          # tool/binary/credential absent
BROKEN = "broken"            # present but its version command will not execute
TIMEOUT = "timeout"          # exceeded the probe deadline
ERROR = "error"              # ran and failed for another reason


# ---------------------------------------------------------------------------
# Dependency probes used by doctor.
#
# ``probe_dependency`` checks external binaries such as yt-dlp and node for the
# vendored X client. It answers three
# questions the bare shutil.which gate cannot:
#   - Is the binary genuinely runnable?
#   - If not, WHICH fix applies (install vs reinstall vs a PATH edit), keyed to
#     the package manager that owns the binary on this machine?
#   - Is an on-disk binary merely off the current process PATH?
#
# Semantics follow the engine gate: availability means PATH-resolvable in THIS
# process, not present-on-disk. Probes are one short-timeout version exec each
# and memoized per process, so doctor and runtime checks can reuse them.
# ---------------------------------------------------------------------------

# Per-probe budget in seconds: a healthy --version exec is near-instant, so a
# slow probe is itself a diagnostic (for example, a hung executable).
PROBE_TIMEOUT = 5.0

# Cheap side-effect-free version invocation per dependency (default --version).
_VERSION_ARGS: Dict[str, List[str]] = {}

# Package managers each dependency may be owned by, in preference order, and
# the (install, reinstall) prescription for each. "reinstall" wording matters:
# a BROKEN binary is present, so telling the user to "install" it reads as a
# no-op when the resolved executable is broken.
_MANAGER_PRESCRIPTIONS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "yt-dlp": {
        "brew": ("brew install yt-dlp", "brew reinstall yt-dlp"),
        "pipx": ("pipx install yt-dlp", "pipx reinstall yt-dlp"),
    },
    "node": {
        "brew": ("brew install node", "brew reinstall node"),
        "nvm": ("nvm install --lts", "reinstall node via nvm: nvm install --lts && nvm use --lts"),
    },
}

# Last-resort prescriptions when no known package manager is detected.
_FALLBACK_PRESCRIPTIONS: Dict[str, Tuple[str, str]] = {
    "yt-dlp": (
        "install yt-dlp (https://github.com/yt-dlp/yt-dlp#installation) and ensure it is on PATH",
        "reinstall yt-dlp (https://github.com/yt-dlp/yt-dlp#installation); the current binary won't run",
    ),
    "node": (
        "install Node.js 22+ (https://nodejs.org) and ensure `node` is on PATH",
        "reinstall Node.js 22+ (https://nodejs.org); the current binary won't run",
    ),
}


@dataclass
class DependencyProbe:
    """Uniform probe result for one external dependency.

    ``status`` is one of the module-level constants (OK/MISSING/BROKEN/TIMEOUT).
    ``detail`` says what was observed (version string, exec error, off-PATH
    location). ``prescription`` is the copy-pasteable fix, empty when OK.
    ``owner_pkg_manager`` names the manager the prescription targets
    ("brew", "pipx", "apt", "nvm", "npx"), or "" for PATH fixes / fallbacks.
    """

    name: str
    status: str
    detail: str = ""
    prescription: str = ""
    owner_pkg_manager: str = ""
    # True for the on-disk-but-off-PATH case: MISSING (the engine gate would
    # not pass) but the fix is a PATH edit, not an install.
    off_path: bool = False

# Safe under the GIL (dict get/set are atomic) and each dependency name is
# probed from a single builder today; worst case is one redundant probe.
_dependency_probe_cache: Dict[str, DependencyProbe] = {}


def _nvm_present() -> bool:
    return bool(os.environ.get("NVM_DIR")) or (Path.home() / ".nvm").is_dir()


def _manager_available(manager: str) -> bool:
    if manager == "nvm":
        return _nvm_present()
    if manager == "apt":
        return shutil.which("apt-get") is not None
    return shutil.which(manager) is not None


def _prescription(name: str, kind: str) -> Tuple[str, str]:
    """Return ``(prescription, owner_pkg_manager)`` for install/reinstall.

    ``kind`` is "install" (MISSING) or "reinstall" (BROKEN). The first
    detected manager wins, with a generic actionable fallback.
    """
    idx = 0 if kind == "install" else 1
    for manager, prescriptions in _MANAGER_PRESCRIPTIONS.get(name, {}).items():
        if _manager_available(manager):
            return prescriptions[idx], manager
    fallback = _FALLBACK_PRESCRIPTIONS.get(name)
    if fallback:
        return fallback[idx], ""
    verb = "install" if kind == "install" else "reinstall"
    return f"{verb} {name} and ensure it is on PATH", ""


def _off_path_candidate_dirs() -> List[Path]:
    """Common executable directories that the current PATH may omit."""
    return [Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]


def _off_path_binary(name: str) -> Optional[Path]:
    """Return an executable for ``name`` in a known dir that PATH misses."""
    names = [name, f"{name}.exe"] if os.name == "nt" else [name]
    for directory in _off_path_candidate_dirs():
        for candidate_name in names:
            candidate = directory / candidate_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def _path_hint(directory: Path) -> str:
    """Render a bin dir with $HOME substituted for copy-pasteable PATH edits."""
    raw = str(directory)
    if os.name == "nt":
        return raw
    home = str(Path.home())
    if raw == home:
        return "$HOME"
    if raw.startswith(home + os.sep):
        return "$HOME/" + raw[len(home) + 1:].replace(os.sep, "/")
    return raw


def probe_dependency(name: str, timeout: float = PROBE_TIMEOUT) -> DependencyProbe:
    """Probe one external dependency: OK | MISSING | BROKEN | TIMEOUT.

    - MISSING: not resolvable on this process's PATH. If the binary exists in
      a known install dir, the prescription is a PATH edit, not an install --
      installing again would not fix anything.
    - BROKEN: shutil.which resolves it but a cheap version exec fails
      (OSError/exec-format, or any non-zero exit). Prescription says
      *reinstall* -- an unexecutable command must never read as available.
    - TIMEOUT: the version exec exceeded the per-probe budget.
    - OK: version exec exited 0; ``detail`` carries the version line.

    Results are memoized for the current process.
    """
    cached = _dependency_probe_cache.get(name)
    if cached is not None:
        return cached
    probe = _probe_dependency_uncached(name, timeout)
    _dependency_probe_cache[name] = probe
    return probe


def _probe_dependency_uncached(name: str, timeout: float) -> DependencyProbe:
    resolved = shutil.which(name)
    if resolved is None:
        off_path = _off_path_binary(name)
        if off_path is not None:
            hint = _path_hint(off_path.parent)
            return DependencyProbe(
                name=name,
                status=MISSING,
                detail=f"{name} is installed at {off_path} but that directory is not on this process's PATH",
                prescription=f'add {hint} to PATH (e.g. export PATH="{hint}:$PATH") so {name} resolves',
                owner_pkg_manager="",
                off_path=True,
            )
        prescription, manager = _prescription(name, "install")
        return DependencyProbe(
            name=name,
            status=MISSING,
            detail=f"{name} not found on PATH",
            prescription=prescription,
            owner_pkg_manager=manager,
        )

    command = [name] + _VERSION_ARGS.get(name, ["--version"])
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError) as exc:
        prescription, manager = _prescription(name, "reinstall")
        return DependencyProbe(
            name=name,
            status=BROKEN,
            detail=f"{name} resolves to {resolved} but won't execute: {exc}",
            prescription=prescription,
            owner_pkg_manager=manager,
        )
    except subprocess.TimeoutExpired:
        prescription, manager = _prescription(name, "reinstall")
        return DependencyProbe(
            name=name,
            status=TIMEOUT,
            detail=f"{name} version probe timed out after {timeout:g}s",
            prescription=f"re-run doctor; if the timeout persists: {prescription}",
            owner_pkg_manager=manager,
        )

    if proc.returncode == 0:
        lines = (proc.stdout or proc.stderr or "").strip().splitlines()
        version = lines[0].strip() if lines else ""
        return DependencyProbe(name=name, status=OK, detail=version)

    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    why = lines[0].strip() if lines else f"exit {proc.returncode}"
    prescription, manager = _prescription(name, "reinstall")
    return DependencyProbe(
        name=name,
        status=BROKEN,
        detail=f"{name} resolves to {resolved} but the version probe failed: {why}",
        prescription=prescription,
        owner_pkg_manager=manager,
    )
