"""Single remediation vocabulary for doctor and backend diagnostics.

CLI forms use placeholders and never contain credential values.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

_ENGINE = Path(__file__).resolve().parents[1] / "last30days.py"
ENGINE_CLI = f"{shlex.quote(sys.executable)} {shlex.quote(str(_ENGINE))}"
EDIT_CONFIG_CLI = '${EDITOR:-vi} "$HOME/.config/last30days/.env"'

_YTDLP_BREW_INSTALL = "brew install yt-dlp"
_YTDLP_BREW_REINSTALL = "brew reinstall yt-dlp"
_YTDLP_PIPX_REINSTALL = "pipx reinstall yt-dlp"

GENERIC_FIX_NL = f"run {ENGINE_CLI} doctor for current setup advice"


@dataclass(frozen=True)
class Prescription:
    """Remediation for one source/problem pair.

    ``fix_nl`` is the natural-language form; ``fix_cli`` is an exact command.
    ``alt_cli`` carries per-platform alternatives when needed.
    """

    source: str
    failure: str
    cause: str
    fix_nl: str
    fix_cli: str
    alt_cli: Tuple[str, ...] = ()


def _entry(source: str, failure: str, **kwargs) -> Tuple[Tuple[str, str], Prescription]:
    return (source, failure), Prescription(source=source, failure=failure, **kwargs)


REGISTRY: Dict[Tuple[str, str], Prescription] = dict((
    _entry(
        "x", "cookies_missing",
        cause="X browser cookies (AUTH_TOKEN/CT0) are not configured",
        fix_nl=(
            "add XAI_API_KEY or XQUIK_API_KEY to the curated config, or log "
            "into x.com and set LAST30DAYS_FROM_BROWSER to the browser "
            "whose cookies the engine may read"
        ),
        fix_cli=EDIT_CONFIG_CLI,
    ),
    _entry(
        "x", "cookies_expired",
        cause="X errored this run: cookies are configured but likely expired or revoked",
        fix_nl="log into x.com in the configured browser, then re-run",
        fix_cli=EDIT_CONFIG_CLI,
    ),
    _entry(
        "scrapecreators", "key_missing",
        cause="SCRAPECREATORS_API_KEY is not set",
        fix_nl=(
            "add a ScrapeCreators API key to the curated config to enable "
            "TikTok and the Reddit/YouTube fallback lanes"
        ),
        fix_cli=EDIT_CONFIG_CLI,
    ),
    _entry(
        "youtube", "ytdlp_missing",
        cause="yt-dlp is not installed on the Codex subprocess PATH",
        fix_nl="install yt-dlp to enable the free local YouTube lane",
        fix_cli=_YTDLP_BREW_INSTALL,
        alt_cli=("scoop install yt-dlp", "pip install -U yt-dlp"),
    ),
    _entry(
        "youtube", "ytdlp_stale",
        cause=(
            "yt-dlp is installed but stale: YouTube's caption format changes "
            "frequently and old binaries silently fail every transcript"
        ),
        fix_nl="update yt-dlp via your package manager",
        fix_cli="brew upgrade yt-dlp",
        alt_cli=("scoop update yt-dlp", "pip install -U yt-dlp"),
    ),
    _entry(
        "youtube", "ytdlp_broken",
        cause="yt-dlp resolves on PATH but its version command does not execute",
        fix_nl=(
            "reinstall yt-dlp so the resolved executable works"
        ),
        fix_cli=_YTDLP_BREW_REINSTALL,
        alt_cli=(_YTDLP_PIPX_REINSTALL,),
    ),
))


def lookup(source: str, failure: str) -> Optional[Prescription]:
    """Return the registered entry for (source, failure), or None."""
    return REGISTRY.get((source, failure))


def get(source: str, failure: str) -> Prescription:
    """Return the registered entry or a generic current-state fallback.

    Never raises: an unregistered problem still yields an actionable
    (if generic) prescription, so a report renderer cannot crash on an
    unregistered problem.
    """
    entry = lookup(source, failure)
    if entry is not None:
        return entry
    return Prescription(
        source=source,
        failure=failure,
        cause=f"{source}: {failure.replace('_', ' ')}",
        fix_nl=GENERIC_FIX_NL,
        fix_cli=f"{ENGINE_CLI} doctor --json",
    )
