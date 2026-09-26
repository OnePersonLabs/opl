"""Current-state diagnostics for Last 30 Days."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from . import backends, env, health, pipeline, prescriptions, skill_meta

CACHE_SCHEMA = "last30days-doctor-cache"
CACHE_FILENAME = "doctor-cache.json"
DEFAULT_CACHE_TTL_SECONDS = 900

DOCTOR_PROBE_COMMANDS = (
    {"command": ["yt-dlp", "--version"], "condition": "when yt-dlp resolves on PATH"},
    {"command": ["node", "--version"], "condition": "when browser-cookie X credentials are configured"},
)

TIER_READY = "ready"
TIER_DEGRADED = "degraded"
TIER_OPTIONAL = "optional"
TIER_ERROR = "error"

GLYPHS = {
    TIER_READY: "✓",
    TIER_DEGRADED: "!",
    TIER_OPTIONAL: "○",
    TIER_ERROR: "✗",
}

SOURCE_ORDER = (
    "reddit",
    "x",
    "youtube",
    "web",
    "hackernews",
    "polymarket",
    "github",
    "tiktok",
)

KEY_PRESENCE_VARS = (
    "SCRAPECREATORS_API_KEY",
    "XAI_API_KEY",
    "XQUIK_API_KEY",
    "BRAVE_API_KEY",
    "EXA_API_KEY",
    "SERPER_API_KEY",
    "PARALLEL_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GITHUB_TOKEN",
)


def _record(
    tier: str,
    status: str,
    *,
    active_backend: str | None = None,
    backends_list: list[dict[str, Any]] | None = None,
    detail: str = "",
    prescription: str = "",
    requires: str = "",
) -> dict[str, Any]:
    return {
        "tier": tier,
        "status": status,
        "active_backend": active_backend,
        "backends": backends_list or [],
        "detail": detail,
        "prescription": prescription,
        "requires": requires,
    }


def _chain_record(source: str, config: dict[str, Any]) -> dict[str, Any]:
    resolution = backends.resolve(source, config)
    findings = [
        {
            "name": finding.name,
            "status": finding.status,
            "detail": finding.detail,
            "prescription": finding.prescription,
            "requires": finding.requires,
        }
        for finding in resolution.findings
    ]
    active = next(
        (finding for finding in resolution.findings if finding.name == resolution.active_backend),
        None,
    )
    if resolution.mode == backends.MODE_CONDITIONAL:
        first = resolution.findings[0] if resolution.findings else None
        return _record(
            TIER_READY,
            health.OK,
            backends_list=findings,
            detail=resolution.conditional,
            requires=first.requires if first else "",
        )
    if resolution.tier == backends.TIER_OK:
        return _record(
            TIER_READY,
            health.OK,
            active_backend=resolution.active_backend,
            backends_list=findings,
            detail=resolution.summary,
            requires=active.requires if active else "",
        )
    if resolution.tier == backends.TIER_WARN:
        return _record(
            TIER_DEGRADED,
            health.DEGRADED,
            active_backend=resolution.active_backend,
            backends_list=findings,
            detail=resolution.summary,
            prescription=resolution.prescription,
            requires=active.requires if active else "",
        )

    configured_failure = next(
        (
            finding
            for finding in resolution.findings
            if finding.status in {health.BROKEN, health.TIMEOUT, health.ERROR}
        ),
        None,
    )
    if configured_failure:
        return _record(
            TIER_ERROR,
            configured_failure.status,
            backends_list=findings,
            detail=configured_failure.detail,
            prescription=configured_failure.prescription or resolution.prescription,
            requires=configured_failure.requires,
        )
    first = resolution.findings[0] if resolution.findings else None
    return _record(
        TIER_OPTIONAL,
        "unconfigured",
        backends_list=findings,
        detail=resolution.summary,
        prescription=resolution.prescription,
        requires=first.requires if first else "",
    )


def _free_source(detail: str, requires: str = "none") -> dict[str, Any]:
    return _record(TIER_READY, health.OK, detail=detail, requires=requires)


def _key_source(
    config: dict[str, Any],
    key: str,
    *,
    requires: str,
    prescription: str,
) -> dict[str, Any]:
    if not config.get(key):
        return _record(
            TIER_OPTIONAL,
            "unconfigured",
            prescription=prescription,
            requires=requires,
        )
    return _record(TIER_READY, health.OK, requires=requires)



def _source_builders(config: dict[str, Any]) -> dict[str, Callable[[], dict[str, Any]]]:
    scrape_fix = prescriptions.get("scrapecreators", "key_missing")
    scrape_prescription = f"{scrape_fix.fix_nl} (cli: {scrape_fix.fix_cli})"
    return {
        "reddit": lambda: _chain_record("reddit", config),
        "x": lambda: _chain_record("x", config),
        "youtube": lambda: _chain_record("youtube", config),
        "web": lambda: _chain_record("web", config),
        "hackernews": lambda: _free_source("public Algolia API"),
        "polymarket": lambda: _free_source("public Polymarket API"),
        "github": lambda: _free_source(
            "authenticated via token/gh"
            if config.get("GITHUB_TOKEN") or shutil.which("gh")
            else "public REST API with lower rate limits"
        ),
        "tiktok": lambda: _key_source(
            config,
            "SCRAPECREATORS_API_KEY",
            requires="SCRAPECREATORS_API_KEY",
            prescription=scrape_prescription,
        ),
    }


def _build_sources(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    builders = _source_builders(config)
    sources: dict[str, dict[str, Any]] = {}
    for source in SOURCE_ORDER:
        try:
            sources[source] = builders[source]()
        except Exception as exc:
            sources[source] = _record(
                TIER_ERROR,
                health.ERROR,
                detail=f"{type(exc).__name__}: {exc}",
                prescription=f"re-run doctor after repairing the {source} probe",
            )
    return sources


def _runtime_block() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "python_executable": str(Path(sys.executable).resolve()),
        "engine": str((Path(__file__).resolve().parents[1] / "last30days.py")),
        "plugin_version": skill_meta.read_plugin_version(__file__) or "unknown",
    }


def _config_block(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": config.get("_CONFIG_SOURCE"),
        "directory": str(env.CONFIG_DIR) if env.CONFIG_DIR else None,
        "global_env": str(env.CONFIG_FILE) if env.CONFIG_FILE else None,
        "doctor_cache": str(cache_path()) if cache_path() else None,
        "ignored_project_config": config.get("_IGNORED_PROJECT_CONFIG"),
    }


def build_report(config: dict[str, Any]) -> dict[str, Any]:
    diagnostics = pipeline.diagnose(config, None, safe=True)
    permissions = diagnostics["permission_preflight"]
    doctor_cache = cache_path()
    permissions["local_reads"]["doctor_cache"] = {
        "path": str(doctor_cache) if doctor_cache else None,
        "status": "not_read",
    }
    if doctor_cache:
        permissions["local_writes"].append(
            {"kind": "doctor_cache", "path": str(doctor_cache)}
        )
    permissions["doctor_probe_commands"] = list(DOCTOR_PROBE_COMMANDS)
    return {
        "runtime": _runtime_block(),
        "config": _config_block(config),
        "credentials_present": {
            key: bool(config.get(key)) for key in KEY_PRESENCE_VARS
        },
        "permissions": permissions,
        "sources": _build_sources(config),
    }


def cache_path() -> Path | None:
    return env.CONFIG_DIR / CACHE_FILENAME if env.CONFIG_DIR else None


def _cache_ttl(config: dict[str, Any]) -> int:
    raw = os.environ.get("LAST30DAYS_DOCTOR_TTL")
    if raw is None:
        raw = config.get("LAST30DAYS_DOCTOR_TTL")
    try:
        return max(0, int(raw)) if raw not in (None, "") else DEFAULT_CACHE_TTL_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL_SECONDS


def _fingerprint(config: dict[str, Any]) -> str:
    signals = {
        "credentials_present": {
            key: bool(config.get(key)) for key in KEY_PRESENCE_VARS
        },
        "x_browser_cookies": bool(config.get("AUTH_TOKEN") and config.get("CT0")),
        "x_backend": str(config.get(env.X_BACKEND_PIN_VAR) or ""),
        "reddit_backend": str(config.get(env.REDDIT_BACKEND_PIN_VAR) or ""),
        "include_sources": str(config.get("LAST30DAYS_INCLUDE_SOURCES") or ""),
        "exclude_sources": str(config.get("LAST30DAYS_EXCLUDE_SOURCES") or ""),
    }
    raw = json.dumps(signals, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_cache(config: dict[str, Any]) -> dict[str, Any] | None:
    path = cache_path()
    if not path or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != CACHE_SCHEMA:
        return None
    if payload.get("fingerprint") != _fingerprint(config):
        return None
    generated_at = payload.get("generated_at")
    if not env.is_timestamp_fresh(generated_at, _cache_ttl(config)):
        return None
    report = payload.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("sources"), dict):
        return None
    report["generated_at"] = generated_at
    report["from_cache"] = True
    cache_read = (report.get("permissions") or {}).get("local_reads", {}).get("doctor_cache")
    if isinstance(cache_read, dict):
        cache_read["status"] = "read"
    return report


def _write_cache(config: dict[str, Any], report: dict[str, Any]) -> None:
    path = cache_path()
    if not path:
        return
    payload = {
        "schema": CACHE_SCHEMA,
        "fingerprint": _fingerprint(config),
        "generated_at": report["generated_at"],
        "report": report,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        os.chmod(path, 0o600)
    except OSError as exc:
        sys.stderr.write(f"[last30days] doctor cache write failed: {exc}\n")


def render_text(report: dict[str, Any]) -> str:
    runtime = report["runtime"]
    config = report["config"]
    lines = [
        "Last 30 Days doctor",
        f"runtime: Python {runtime['python']} · plugin {runtime['plugin_version']}",
        f"config: {config['source']} · {config['global_env'] or 'disabled'}",
        f"cache: {config['doctor_cache'] or 'disabled'} · {'cached' if report.get('from_cache') else 'live'}",
        "",
    ]
    for tier in (TIER_READY, TIER_DEGRADED, TIER_OPTIONAL, TIER_ERROR):
        records = [
            (name, record)
            for name, record in report["sources"].items()
            if record["tier"] == tier
        ]
        lines.append(f"{tier.title()}:")
        if not records:
            lines.append("  (none)")
        for name, record in records:
            detail = record.get("detail") or record.get("status")
            line = f"  {GLYPHS[tier]} {name}: {detail}"
            if record.get("prescription"):
                line += f"; fix: {record['prescription']}"
            lines.append(line)
        lines.append("")
    lines.append(f"generated: {report['generated_at']}")
    return "\n".join(lines) + "\n"


def run(config: dict[str, Any], *, emit_json: bool = False, cached: bool = False) -> int:
    report = _read_cache(config) if cached else None
    if report is None:
        report = build_report(config)
        report["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report["from_cache"] = False
        _write_cache(config, report)
    if emit_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report), end="")
    return 0
