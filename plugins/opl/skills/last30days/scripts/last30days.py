#!/usr/bin/env python3
# ruff: noqa: E402
"""last30days CLI."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import sys
from pathlib import Path

MIN_PYTHON = (3, 12)


def ensure_supported_python(version_info: tuple[int, int, int] | object | None = None) -> None:
    if version_info is None:
        version_info = sys.version_info
    major, minor, micro = tuple(version_info[:3])
    if (major, minor) >= MIN_PYTHON:
        return
    req = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    sys.stderr.write(
        f"last30days requires Python {req}+.\n"
        f"Detected Python {major}.{minor}.{micro}.\n"
        f"Install with:\n"
        f"  Mac:     brew install python@{req}\n"
        f"  Windows: winget install Python.Python.{req}\n"
        f"  Linux:   sudo apt install python{req}  (or pyenv install {req})\n"
        f"Then rerun the requested command with python{req}.\n"
    )
    raise SystemExit(1)


ensure_supported_python()

if os.name == "nt":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from lib import dates, env, permission_preflight, pipeline, process_registry, render, schema, ui

atexit.register(process_registry.cleanup_children)


def parse_search_flag(raw: str, flag_name: str = "--search") -> list[str]:
    sources = []
    for source in raw.split(","):
        source = source.strip().lower()
        if not source:
            continue
        normalized = pipeline.SEARCH_ALIAS.get(source, source)
        if normalized not in pipeline.MOCK_AVAILABLE_SOURCES:
            raise SystemExit(f"Unknown search source in {flag_name}: {source}")
        if normalized not in sources:
            sources.append(normalized)
    if not sources:
        raise SystemExit(f"{flag_name} requires at least one source.")
    return sources

def parse_as_of_date_arg(value: str) -> str:
    try:
        parsed = dates.parse_as_of_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed

def resolve_requested_sources(args_search: str | None, config: dict) -> list[str] | None:
    """Resolve the requested source set: explicit --search wins, then the
    LAST30DAYS_DEFAULT_SEARCH config key (env var or .env file), then None
    (per-query default behavior). The config fallback lets users pin a fixed
    source set without patching SKILL.md.
    """
    if args_search:
        return parse_search_flag(args_search)
    default_search = (config.get("LAST30DAYS_DEFAULT_SEARCH") or "").strip()
    if default_search:
        return parse_search_flag(default_search, flag_name="LAST30DAYS_DEFAULT_SEARCH")
    return None


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "last30days"


def save_output(
    report: schema.Report,
    emit: str,
    save_dir: str,
    suffix: str = "",
) -> Path:
    from datetime import datetime
    path = Path(save_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    slug = slugify(report.topic)
    extension = "json" if emit == "json" else "md"
    suffix_part = f"-{suffix}" if suffix else ""
    base = path / f"{slug}-raw{suffix_part}.{extension}"
    date_str = datetime.now().strftime('%Y-%m-%d')
    candidates = [base]
    candidates.append(path / f"{slug}-raw{suffix_part}-{date_str}.{extension}")
    for i in range(1, 100):
        candidates.append(path / f"{slug}-raw{suffix_part}-{date_str}-{i}.{extension}")
    content = emit_output(report, emit) if emit == "json" else render.render_full(report)
    encoded = content.encode("utf-8")
    for candidate in candidates:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(encoded)
        return candidate
    # Fallback: all 101 candidates existed (extremely unlikely).
    raise RuntimeError(
        f"save_output: could not find a unique filename after 101 attempts in {path}"
    )


def save_rendered_output(rendered_content: str, output_file: str) -> Path:
    out_path = Path(output_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered_content, encoding="utf-8")
    return out_path


def emit_output(
    report: schema.Report,
    emit: str,
    save_path: str | None = None,
) -> str:
    if emit == "json":
        return json.dumps(schema.to_dict(report), indent=2, sort_keys=True)
    if emit in {"compact", "md"}:
        return render.render_compact(report, save_path=save_path)
    if emit == "context":
        return render.render_context(report)
    raise SystemExit(f"Unsupported emit mode: {emit}")


def emit_comparison_output(
    entity_reports: list[tuple[str, schema.Report]],
    emit: str,
    save_path: str | None = None,
) -> str:
    if emit == "json":
        payload = {
            "comparison": True,
            "entities": [label for label, _ in entity_reports],
            "reports": [
                {"entity": label, "report": schema.to_dict(report)}
                for label, report in entity_reports
            ],
        }
        return json.dumps(payload, indent=2, sort_keys=True)
    if emit in {"compact", "md"}:
        return render.render_comparison_multi(entity_reports, save_path=save_path)
    if emit == "context":
        return render.render_comparison_multi_context(entity_reports)
    raise SystemExit(f"Unsupported emit mode: {emit}")


def compute_save_path_display(save_dir: str, topic: str, suffix: str, emit: str) -> str:
    """Compute the user-friendly save path string that will be shown in the footer.

    Uses ~ when the saved file is under the user's home directory; otherwise
    returns the absolute path.
    """
    from pathlib import Path as _Path
    path = _Path(save_dir).expanduser().resolve()
    slug = slugify(topic)
    extension = "json" if emit == "json" else "md"
    suffix_part = f"-{suffix}" if suffix else ""
    raw = path / f"{slug}-raw{suffix_part}.{extension}"
    try:
        home = _Path.home().resolve()
        relative = raw.relative_to(home)
        return f"~/{relative.as_posix()}"
    except ValueError:
        return raw.as_posix()


def compute_output_path_display(output_file: str) -> str:
    """Compute the user-friendly explicit output path shown in render footers."""
    raw = Path(output_file).expanduser().resolve()
    try:
        home = Path.home().resolve()
        relative = raw.relative_to(home)
        return f"~/{relative.as_posix()}"
    except ValueError:
        return raw.as_posix()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Research a topic across live social, market, and grounded web sources.",
        allow_abbrev=False,
    )
    parser.add_argument("topic", nargs="*", help="Research topic")
    parser.add_argument("--emit", default="compact", choices=["compact", "json", "context", "md"])
    parser.add_argument("--search", help="Comma-separated source list")
    parser.add_argument("--quick", action="store_true", help="Lower-latency retrieval profile")
    parser.add_argument("--deep", action="store_true", help="Higher-recall retrieval profile")
    parser.add_argument("--debug", action="store_true", help="Enable HTTP debug logging")
    parser.add_argument("--mock", action="store_true", help="Use mock retrieval fixtures")
    parser.add_argument("--preflight", action="store_true",
                        help="Print a safe human-readable permission preflight")
    parser.add_argument("--preflight-report-on-save-dir", help=argparse.SUPPRESS)
    parser.add_argument("--no-browser-cookies", action="store_true",
                        help="Disable browser-cookie extraction even when LAST30DAYS_FROM_BROWSER is configured")
    parser.add_argument("--save-dir", help="Optional directory for saving the rendered output")
    parser.add_argument("--output", help="Optional exact file path for saving the rendered output")
    parser.add_argument("--x-handle", help="X handle for targeted supplemental search")
    parser.add_argument("--x-related", help="Comma-separated related X handles (searched with lower weight)")
    parser.add_argument("--web-backend", default="auto",
                        choices=["auto", "brave", "exa", "serper", "parallel", "none"],
                        help="Web search backend (default: auto, tries Brave then Exa then Serper then Parallel)")
    parser.add_argument("--plan", help="JSON query plan (skips internal LLM planner). Can be a JSON string or a file path.")
    parser.add_argument("--save-suffix", help="Suffix for the saved output filename (for example, 'comparison')")
    parser.add_argument("--subreddits", help="Comma-separated broad/category subreddit names to search (e.g., SaaS,Entrepreneur)")
    parser.add_argument("--dedicated-subreddits", help="Comma-separated entity-home subreddit names (e.g., Kanye,WestSubEver). Pulled in full (top+hot+new) and exempt from the relevance floor since the whole sub is the topic.")
    parser.add_argument("--tiktok-hashtags", help="Comma-separated TikTok hashtags without # (e.g., tella,screenrecording)")
    parser.add_argument("--tiktok-creators", help="Comma-separated TikTok creator handles (e.g., TellaHQ,taborplace)")
    parser.add_argument(
        "--days",
        "--lookback-days",
        dest="lookback_days",
        type=int,
        default=30,
        help="Number of days to look back for research (default: 30)",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of_date",
        type=parse_as_of_date_arg,
        help=(
            "End date for the lookback window in YYYY-MM-DD format. "
            "When set, --days looks back from this date instead of today."
            ),
    )
    parser.add_argument("--auto-resolve", action="store_true",
                        help="Use the engine's web discovery to resolve subreddits and handles")
    parser.add_argument("--github-user", help="GitHub username for person-mode search (e.g., steipete)")
    parser.add_argument("--github-repo", help="Comma-separated owner/repo values for project-mode search (for example, psf/requests,pallets/flask)")
    parser.add_argument(
        "--competitors",
        nargs="?",
        const=2,
        type=int,
        default=None,
        metavar="N",
        help="Auto-discover N competitor entities and fan out last30days across all of them as a comparison (default N=2 -> 3-way: original + 2 peers; range 1..6). Use --competitors-list to override discovery.",
    )
    parser.add_argument(
        "--competitors-list",
        dest="competitors_list",
        help="Comma-separated competitor entities to skip discovery (for example, 'Alpha,Beta,Gamma'). Implies --competitors.",
    )
    parser.add_argument(
        "--polymarket-keywords",
        dest="polymarket_keywords",
        help=(
            "Comma-separated keywords that Polymarket market titles must match "
            "to be included. Use for ambiguous single-token topics like 'Warriors' "
            "(nba,gsw,golden-state) to filter out Glasgow Warriors rugby, Honor "
            "of Kings Rogue Warriors, etc. When omitted, Polymarket returns all "
            "matching markets -- so expect cross-entity noise on generic topics."
        ),
    )
    parser.add_argument(
        "--competitors-plan",
        dest="competitors_plan",
        help=(
            "JSON mapping of per-entity targeting for competitor and comparison "
            "sub-runs. Schema: {entity_name: {x_handle?, x_related?, subreddits?, "
            "github_user?, github_repos?, context?}}. Accepts inline JSON or a file "
            "path. Implies --competitors. Preferred over --competitors-list when the "
            "caller has already resolved per-entity handles and communities."
        ),
    )
    return parser


def parse_competitors_plan(raw: str | None) -> dict[str, dict]:
    """Parse a --competitors-plan argument into a {entity_name_lower: plan_entry} dict.

    Accepts inline JSON or a file path (matches --plan). Returns {} on None/empty.
    Validation: top-level must be a dict; each value must be a dict. Unknown fields
    in entry values log a warning but do not abort. Invalid JSON or non-dict shape
    raises SystemExit(2) with a clear stderr message.
    """
    if not raw:
        return {}
    plan_str = raw
    if os.path.isfile(plan_str):
        try:
            with open(plan_str, encoding="utf-8") as f:
                plan_str = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write(f"[CompetitorsPlan] Cannot read plan file: {exc}\n")
            raise SystemExit(2)
    try:
        parsed = json.loads(plan_str)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[CompetitorsPlan] Invalid JSON: {exc}\n")
        raise SystemExit(2)
    if not isinstance(parsed, dict):
        sys.stderr.write(
            f"[CompetitorsPlan] Top-level must be a dict of "
            f"{{entity: {{targeting}}}}, got {type(parsed).__name__}\n"
        )
        raise SystemExit(2)
    known_fields = {
        "x_handle", "x_related", "subreddits",
        "github_user", "github_repos", "context",
    }
    normalized: dict[str, dict] = {}
    for entity, entry in parsed.items():
        if not isinstance(entry, dict):
            sys.stderr.write(
                f"[CompetitorsPlan] Entry for {entity!r} must be a dict, "
                f"got {type(entry).__name__}; skipping.\n"
            )
            continue
        unknown = set(entry.keys()) - known_fields
        if unknown:
            sys.stderr.write(
                f"[CompetitorsPlan] Unknown fields in {entity!r}: "
                f"{sorted(unknown)}; ignoring.\n"
            )
        normalized[entity.strip().lower()] = {
            k: v for k, v in entry.items() if k in known_fields
        }
    return normalized


def subrun_kwargs_for(
    entity: str,
    plan_entry: dict,
    *,
    resolved: dict,
) -> dict:
    """Build an explicit per-entity kwargs dict for pipeline.run().

    Plan values win over auto_resolve values. Returns keys for all per-entity
    targeting flags so callers never fall through to closure defaults.

    This helper is the single source of truth for sub-run kwargs -- main-topic
    flags can only leak if a caller bypasses it.
    """
    def _choose(plan_key: str, resolved_key: str | None = None):
        if plan_key in plan_entry and plan_entry[plan_key]:
            return plan_entry[plan_key]
        if resolved_key is not None and resolved.get(resolved_key):
            return resolved[resolved_key]
        return None

    x_handle = _choose("x_handle", "x_handle")
    if isinstance(x_handle, str):
        x_handle = x_handle.lstrip("@") or None

    subreddits = _choose("subreddits", "subreddits")
    if isinstance(subreddits, list):
        subreddits = [s.strip().removeprefix("r/") for s in subreddits if s.strip()] or None

    x_related = plan_entry.get("x_related")
    if isinstance(x_related, list):
        x_related = [h.strip().lstrip("@") for h in x_related if h.strip()] or None
    else:
        x_related = None

    github_user = _choose("github_user", "github_user")
    if isinstance(github_user, str):
        github_user = github_user.lstrip("@").lower() or None

    github_repos = _choose("github_repos", "github_repos")
    if isinstance(github_repos, list):
        github_repos = [r.strip() for r in github_repos if r.strip() and "/" in r.strip()] or None

    context = plan_entry.get("context") or resolved.get("context") or ""

    return {
        "x_handle": x_handle,
        "x_related": x_related,
        "subreddits": subreddits,
        "github_user": github_user,
        "github_repos": github_repos,
        "_context": context,
    }


COMPETITORS_MIN = 1
COMPETITORS_MAX = 6
COMPETITORS_DEFAULT = 2


def resolve_competitors_args(args: argparse.Namespace) -> tuple[bool, int, list[str]]:
    """Normalize --competitors / --competitors-list into (enabled, count, explicit_list).

    - (False, 0, []) when neither flag is set.
    - An explicit list always wins; count is derived from list length.
    - A numeric count outside [1, 6] is clamped with a stderr warning.
    - count <= 0 (explicit) raises SystemExit(2).
    """
    explicit_list: list[str] = []
    list_flag_provided = args.competitors_list is not None
    if list_flag_provided:
        explicit_list = [
            entity.strip()
            for entity in args.competitors_list.split(",")
            if entity.strip()
        ]
        if not explicit_list:
            sys.stderr.write("[Competitors] --competitors-list is empty.\n")
            raise SystemExit(2)

    competitors_flag = args.competitors
    list_present = bool(explicit_list)
    flag_present = competitors_flag is not None

    if not list_present and not flag_present:
        return False, 0, []

    if list_present:
        count = len(explicit_list)
        if flag_present and competitors_flag != count:
            sys.stderr.write(
                f"[Competitors] --competitors={competitors_flag} ignored; using "
                f"{count} entries from --competitors-list.\n"
            )
        if count > COMPETITORS_MAX:
            sys.stderr.write(
                f"[Competitors] --competitors-list has {count} entries, clamping to {COMPETITORS_MAX}.\n"
            )
            explicit_list = explicit_list[:COMPETITORS_MAX]
            count = COMPETITORS_MAX
        return True, count, explicit_list

    # flag_present, no explicit list
    count = competitors_flag
    if count < COMPETITORS_MIN:
        sys.stderr.write(
            f"[Competitors] --competitors must be >= {COMPETITORS_MIN} (got {count}).\n"
        )
        raise SystemExit(2)
    if count > COMPETITORS_MAX:
        sys.stderr.write(
            f"[Competitors] --competitors={count} exceeds max {COMPETITORS_MAX}; clamping.\n"
        )
        count = COMPETITORS_MAX
    return True, count, []


def _show_runtime_ui(
    report: schema.Report,
    progress: ui.ProgressDisplay,
) -> None:
    counts = {source: len(items) for source, items in report.items_by_source.items()}
    display_sources = list(
        dict.fromkeys(
            [
                *report.query_plan.source_weights.keys(),
                *report.items_by_source.keys(),
                *report.errors_by_source.keys(),
            ]
        )
    )
    progress.end_processing()
    progress.show_complete(
        source_counts=counts,
        display_sources=display_sources,
    )


def _render_save_and_print(
    args: argparse.Namespace,
    report: schema.Report,
    entity_reports: list[tuple[str, schema.Report]] | None,
) -> int:
    footer_save_path = None
    if args.output:
        footer_save_path = compute_output_path_display(args.output)
    elif args.save_dir:
        footer_save_path = compute_save_path_display(
            args.save_dir, report.topic, args.save_suffix or "", args.emit
        )

    if entity_reports:
        rendered = emit_comparison_output(
            entity_reports,
            args.emit,
            save_path=footer_save_path,
        )
    else:
        rendered = emit_output(
            report,
            args.emit,
            save_path=footer_save_path,
        )
    if args.output:
        output_path = save_rendered_output(rendered, args.output)
        sys.stderr.write(f"[last30days] Saved output to {output_path}\n")
        sys.stderr.flush()
    if args.save_dir:
        save_path = save_output(
            report,
            args.emit,
            args.save_dir,
            suffix=args.save_suffix or "",
        )
        sys.stderr.write(f"[last30days] Saved output to {save_path}\n")
        comparison_peer_paths: list[Path] = []
        if entity_reports and len(entity_reports) > 1:
            for label, entity_report in entity_reports[1:]:
                peer_path = save_output(
                    entity_report, args.emit, args.save_dir,
                    suffix=args.save_suffix or "",
                )
                comparison_peer_paths.append(peer_path)
                sys.stderr.write(f"[last30days] Saved output to {peer_path}\n")
            peers_display = ", ".join(str(path) for path in comparison_peer_paths)
            sys.stderr.write(
                f"[last30days] Comparison artifact set: main={save_path}; "
                f"peers={peers_display}\n"
            )
        sys.stderr.flush()
    print(rendered)
    return 0


def _propagate_config_to_environ(config: dict[str, object]) -> None:
    """Push relevant env keys to os.environ so provider modules can read them.

    The env.get_config() function reads from a .env file, but providers.py
    reads from os.environ directly. Without this, OPENAI_BASE_URL and
    XAI_BASE_URL overrides are silently ignored. This is a no-op for
    keys that are already set in process env.
    """
    for key in ("OPENAI_BASE_URL", "XAI_BASE_URL"):
        val = config.get(key)
        if val and not os.environ.get(key):
            os.environ[key] = val


# Doctor passthrough flags are subcommand-only rather than global parser flags.
# `--cached` serves the stored doctor report within its TTL and falls through
# to a live run otherwise.
DOCTOR_PASSTHROUGH_FLAGS = {
    "--json",
    "--cached",
}


def _validate_extra_argv(parser: argparse.ArgumentParser, topic: str, extra_argv: list[str]) -> None:
    if not extra_argv:
        return
    if topic.lower() == "doctor":
        unsupported = [arg for arg in extra_argv if arg not in DOCTOR_PASSTHROUGH_FLAGS]
        if unsupported:
            parser.error(
                "unsupported doctor argument(s): "
                + ", ".join(unsupported)
                + f"; supported doctor passthrough flags are {', '.join(sorted(DOCTOR_PASSTHROUGH_FLAGS))}"
            )
        return
    parser.error("unsupported Python CLI argument(s): " + ", ".join(extra_argv))


def _config_policy_for_args(args: argparse.Namespace, topic: str) -> env.ConfigLoadPolicy:
    if args.no_browser_cookies:
        browser_mode = "off"
    elif args.preflight or topic.lower() == "doctor":
        # Diagnostics are plan-only and must never read cookie values.
        browser_mode = "plan_only"
    else:
        browser_mode = "read"
    return env.ConfigLoadPolicy(
        browser_cookies=browser_mode,
        inspect_ignored_project_config=args.preflight or topic.lower() == "doctor",
    )


def main() -> int:
    parser = build_parser()
    # Doctor has sub-flags that are validated after topic dispatch.
    args, extra_argv = parser.parse_known_args()
    if args.debug:
        os.environ["LAST30DAYS_DEBUG"] = "1"

    topic = " ".join(args.topic).strip()
    _validate_extra_argv(parser, topic, extra_argv)
    config = env.get_config(policy=_config_policy_for_args(args, topic))
    _propagate_config_to_environ(config)

    # An explicit empty value disables saving instead of falling through.
    if args.save_dir is None:
        env_val = os.environ.get("LAST30DAYS_MEMORY_DIR")
        args.save_dir = env_val if env_val is not None else config.get("LAST30DAYS_MEMORY_DIR")

    # Surface SSH-routing config as an env var so library modules (e.g.
    # youtube_yt) can read it without taking a config dependency. This
    # routes yt-dlp through `ssh <host>` to bypass YouTube's bot-wall on
    # datacenter IPs (see lib/youtube_yt.py for details).
    if config.get("LAST30DAYS_YOUTUBE_SSH_HOST") and "LAST30DAYS_YOUTUBE_SSH_HOST" not in os.environ:
        os.environ["LAST30DAYS_YOUTUBE_SSH_HOST"] = config["LAST30DAYS_YOUTUBE_SSH_HOST"]

    if args.preflight:
        requested_sources = resolve_requested_sources(args.search, config)
        diag = pipeline.diagnose(config, requested_sources, safe=True)
        if args.save_dir or args.preflight_report_on_save_dir:
            preflight = permission_preflight.build(
                config,
                diag,
                planned_save_dir=args.save_dir,
                report_on_save_dir=args.preflight_report_on_save_dir,
            )
        else:
            preflight = diag["permission_preflight"]
        if args.emit == "json":
            print(json.dumps(preflight, indent=2, sort_keys=True))
        else:
            print(permission_preflight.render_text(preflight), end="")
        return 0

    # Exact topic-word dispatch keeps multi-word research topics containing
    # "doctor" on the normal research path.
    if topic.lower() == "doctor":
        from lib import doctor
        return doctor.run(
            config,
            emit_json=(args.emit == "json" or "--json" in extra_argv),
            cached="--cached" in extra_argv,
        )

    requested_sources = resolve_requested_sources(args.search, config)
    if not topic:
        parser.print_usage(sys.stderr)
        return 2
    from lib import preflight
    refuse_msg = preflight.check_low_signal_demographic_query(topic)
    if refuse_msg:
        sys.stderr.write(refuse_msg)
        return 2

    progress = ui.ProgressDisplay(topic, show_banner=True)
    progress.start_processing()

    depth = "deep" if args.deep else "quick" if args.quick else "default"
    try:
        x_related = [h.strip() for h in args.x_related.split(",") if h.strip()] if args.x_related else None
        subreddits = [s.strip().removeprefix("r/") for s in args.subreddits.split(",") if s.strip()] if args.subreddits else None
        dedicated_subreddits = [s.strip().removeprefix("r/") for s in args.dedicated_subreddits.split(",") if s.strip()] if args.dedicated_subreddits else None
        tiktok_hashtags = [h.strip().lstrip("#") for h in args.tiktok_hashtags.split(",") if h.strip()] if args.tiktok_hashtags else None
        tiktok_creators = [c.strip().lstrip("@") for c in args.tiktok_creators.split(",") if c.strip()] if args.tiktok_creators else None
        # Parse external plan if provided via --plan flag
        external_plan = None
        if args.plan:
            import json as _json
            plan_str = args.plan
            if os.path.isfile(plan_str):
                try:
                    with open(plan_str, encoding="utf-8") as f:
                        plan_str = f.read()
                except (OSError, UnicodeDecodeError) as exc:
                    sys.stderr.write(f"[Planner] Cannot read --plan file: {exc}\n")
                    raise SystemExit(2)
            try:
                external_plan = _json.loads(plan_str)
            except _json.JSONDecodeError as exc:
                sys.stderr.write(f"[Planner] Invalid --plan JSON: {exc}\n")
                # Fail fast instead of silently dropping to the internal planner
                # and burning a paid run the user did not ask for. Mirrors the
                # --plan file-read branch above and parse_competitors_plan.
                raise SystemExit(2)

        # Optional engine-side identity resolution.
        repos_from_auto_resolve = False
        if args.auto_resolve and not external_plan:
            from lib import resolve
            resolution = resolve.auto_resolve(topic, config)
            if resolution.get("subreddits") and not subreddits:
                subreddits = resolution["subreddits"]
                sys.stderr.write(f"[AutoResolve] Subreddits: {', '.join(subreddits)}\n")
            if resolution.get("x_handle") and not args.x_handle:
                args.x_handle = resolution["x_handle"]
                sys.stderr.write(f"[AutoResolve] X handle: @{args.x_handle}\n")
            if resolution.get("github_user") and not args.github_user:
                args.github_user = resolution["github_user"]
                sys.stderr.write(f"[AutoResolve] GitHub user: @{args.github_user}\n")
            if resolution.get("github_repos") and not args.github_repo:
                args.github_repo = ",".join(resolution["github_repos"])
                # auto_resolve already canonicalized via canonicalize_github_repos(cap=5);
                # mark so we don't re-canonicalize below and clobber its relevance order.
                repos_from_auto_resolve = True
                sys.stderr.write(f"[AutoResolve] GitHub repos: {args.github_repo}\n")
            if resolution.get("context"):
                # Inject context into external_plan metadata for the planner to use
                if not external_plan:
                    external_plan = None  # planner will use its own, but with context
                # Store context for the planner prompt injection
                config["_auto_resolve_context"] = resolution["context"]
                sys.stderr.write(f"[AutoResolve] Context: {resolution['context'][:80]}...\n")

        github_user = args.github_user.lstrip("@").lower() if args.github_user else None
        github_repos = [r.strip() for r in args.github_repo.split(",") if r.strip() and "/" in r.strip()] if args.github_repo else None

        # Only canonicalize when repos came from a user-supplied --github-repo flag.
        # When repos_from_auto_resolve is True, auto_resolve already ran
        # canonicalize_github_repos(cap=5) and ranked by relevance; re-running here
        # with cap=None can re-sort by topic-slug match and lose that ordering.
        if github_repos and not repos_from_auto_resolve:
            from lib import resolve as resolve_lib
            original_github_repos = github_repos[:]
            github_repos = resolve_lib.canonicalize_github_repos(topic, github_repos, cap=None)
            if github_repos != original_github_repos:
                sys.stderr.write(
                    "[GitHub] Canonicalized repos: "
                    f"{','.join(original_github_repos)} -> {','.join(github_repos)}\n"
                )

        comp_enabled, comp_count, comp_explicit = resolve_competitors_args(args)
        comp_plan = parse_competitors_plan(args.competitors_plan)

        # Polymarket disambiguation: if user passed --polymarket-keywords,
        # store on config so the polymarket adapter can filter matches.
        if args.polymarket_keywords:
            keywords = [
                k.strip().lower()
                for k in args.polymarket_keywords.split(",")
                if k.strip()
            ]
            if keywords:
                config["_polymarket_keywords"] = keywords

        # vs-mode: if the topic string contains " vs " / " versus " and the
        # planner can split it into >=2 entities, route through the same
        # N-pass fanout path as --competitors. The first entity becomes the
        # main topic; remaining entities become the competitor list. User's
        # outer --x-handle / --subreddits apply to the first entity unless
        # --competitors-plan covers it.
        from lib import planner as _planner
        vs_entities = _planner._comparison_entities(topic)
        if len(vs_entities) >= 2 and not comp_enabled:
            topic = vs_entities[0]
            comp_enabled = True
            comp_count = len(vs_entities) - 1
            comp_explicit = vs_entities[1:]
            sys.stderr.write(
                f"[Competitors] vs-mode: routing to N-pass fanout: "
                f"{' vs '.join(vs_entities)}\n"
            )

        # Dedicated subs ride the config dict (already threaded to every source
        # fetch) so the keyless Reddit path can pull them floor-exempt without
        # widening pipeline.run / _retrieve_stream signatures.
        if dedicated_subreddits:
            config["_dedicated_subreddits"] = dedicated_subreddits

        def _main_runner() -> schema.Report:
            r = pipeline.run(
                topic=topic,
                config=config,
                depth=depth,
                requested_sources=requested_sources,
                mock=args.mock,
                x_handle=args.x_handle,
                x_related=x_related,
                web_backend=args.web_backend,
                external_plan=external_plan,
                subreddits=subreddits,
                tiktok_hashtags=tiktok_hashtags,
                tiktok_creators=tiktok_creators,
                lookback_days=args.lookback_days,
                as_of_date=args.as_of_date,
                github_user=github_user,
                github_repos=github_repos,
                internal_subrun=comp_enabled,
            )
            r.artifacts["resolved"] = {
                "entity": topic,
                "x_handle": (args.x_handle or "").lstrip("@"),
                "subreddits": list(subreddits or []),
                "github_user": (github_user or ""),
                "github_repos": list(github_repos or []),
                "context": config.get("_auto_resolve_context", "") or "",
            }
            return r

        if comp_enabled:
            from lib import competitors as competitors_mod
            from lib import fanout, resolve as resolve_mod

            if comp_explicit:
                discovered = comp_explicit
            else:
                if not resolve_mod._has_backend(config) and not args.mock:
                    sys.stderr.write(
                        "[Competitors] Cannot auto-discover peers without help.\n"
                        "\n"
                        "Search the web for the topic's current competitors and each "
                        "peer's handles, communities, and repositories. Then rerun "
                        "with a vs-topic plus --competitors-plan:\n"
                        "  /last30days '{topic} vs {peer1} vs {peer2}' "
                        "--competitors-plan '{\"Peer1\":{\"x_handle\":\"h1\",\"subreddits\":"
                        "[\"s1\"],...},\"Peer2\":{...}}'.\n"
                        "\n"
                        "Alternatively, pass --competitors-list 'A,B,C' to skip "
                        "discovery. Without --competitors-plan, peer sub-runs fall back to "
                        "planner defaults.\n"
                    )
                    return 2
                discovered = competitors_mod.discover_competitors(
                    topic, comp_count, config, lookback_days=args.lookback_days,
                )
                if not discovered:
                    sys.stderr.write(
                        f"[Competitors] No peers discovered for {topic!r}; aborting "
                        "comparison run. Pass --competitors-list to override.\n"
                    )
                    return 2

            sys.stderr.write(
                f"[Competitors] Comparing: {topic} vs " + " vs ".join(discovered) + "\n"
            )

            def _competitor_runner(entity: str) -> schema.Report:
                # Deep-copy config so per-entity auto_resolve context does not
                # leak across sub-runs. Each sub-run writes its own
                # `_auto_resolve_context` into its local config copy.
                entity_config = dict(config)
                plan_entry = comp_plan.get(entity.strip().lower(), {})
                resolved = {
                    "entity": entity,
                    "x_handle": "",
                    "subreddits": [],
                    "github_user": "",
                    "github_repos": [],
                    "context": "",
                }
                # Skip duplicate resolution when --competitors-plan already
                # contains the required identity fields.
                plan_covers_fully = bool(plan_entry.get("x_handle")) and bool(
                    plan_entry.get("subreddits")
                )
                if (
                    not args.mock
                    and not plan_covers_fully
                    and resolve_mod._has_backend(entity_config)
                ):
                    try:
                        r = resolve_mod.auto_resolve(entity, entity_config)
                    except Exception as exc:
                        sys.stderr.write(
                            f"[Competitors] auto_resolve failed for {entity!r}: "
                            f"{type(exc).__name__}: {exc}\n"
                        )
                        r = {}
                    resolved["x_handle"] = r.get("x_handle", "") or ""
                    resolved["subreddits"] = list(r.get("subreddits") or [])
                    resolved["github_user"] = r.get("github_user", "") or ""
                    resolved["github_repos"] = list(r.get("github_repos") or [])
                    resolved["context"] = r.get("context", "") or ""
                kwargs = subrun_kwargs_for(entity, plan_entry, resolved=resolved)
                # Record effective per-entity targeting for the Resolved block.
                resolved_effective = {
                    "entity": entity,
                    "x_handle": kwargs["x_handle"] or "",
                    "subreddits": kwargs["subreddits"] or [],
                    "github_user": kwargs["github_user"] or "",
                    "github_repos": kwargs["github_repos"] or [],
                    "context": kwargs["_context"],
                }
                if kwargs["_context"]:
                    entity_config["_auto_resolve_context"] = kwargs["_context"]
                sys.stderr.write(
                    f"[Competitors] {entity}: "
                    f"x=@{resolved_effective['x_handle'] or '-'} "
                    f"subs={len(resolved_effective['subreddits'])} "
                    f"gh={resolved_effective['github_user'] or '-'} "
                    f"({'plan' if plan_entry else 'auto'})\n"
                )
                report = pipeline.run(
                    topic=entity,
                    config=entity_config,
                    depth=depth,
                    requested_sources=requested_sources,
                    mock=args.mock,
                    x_handle=kwargs["x_handle"],
                    x_related=kwargs["x_related"],
                    subreddits=kwargs["subreddits"],
                    github_user=kwargs["github_user"],
                    github_repos=kwargs["github_repos"],
                    web_backend=args.web_backend,
                    lookback_days=args.lookback_days,
                    as_of_date=args.as_of_date,
                    internal_subrun=True,
                )
                report.artifacts["resolved"] = resolved_effective
                return report

            entity_reports = fanout.run_competitor_fanout(
                main_topic=topic,
                main_runner=_main_runner,
                competitors=discovered,
                competitor_runner=_competitor_runner,
            )
            if len(entity_reports) < 2:
                progress.end_processing()
                sys.stderr.write(
                    f"[Competitors] Fewer than 2 sub-runs survived ({len(entity_reports)}); "
                    "cannot render a comparison. Re-run without --competitors or check the "
                    "warnings above.\n"
                )
                return 1
            report = entity_reports[0][1]
        else:
            entity_reports = None
            report = _main_runner()
    except Exception as exc:
        progress.end_processing()
        progress.show_error(str(exc))
        raise
    _show_runtime_ui(report, progress)
    return _render_save_and_print(args, report, entity_reports)


if __name__ == "__main__":
    raise SystemExit(main())
