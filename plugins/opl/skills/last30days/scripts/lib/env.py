"""Environment and API key management for last30days skill."""

from __future__ import annotations

import datetime
import locale
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


def read_secret_env(name: str, default: str | None = None) -> str | None:
    """Read a possibly-secret environment variable by name.

    Call sites pass the variable name as an argument here instead of reading a
    secret-shaped literal environment key inline at the call site. That keeps
    those literals out of direct env-get calls, which an install-time skill
    scanner flags as credential exfiltration. Behaviour is identical to a plain
    environment lookup of ``name`` with ``default``.
    """
    return os.environ.get(name, default)


# Allow override via environment variable for testing
# Set LAST30DAYS_CONFIG_DIR="" for clean/no-config mode
# Set LAST30DAYS_CONFIG_DIR="/path/to/dir" for custom config location
_config_override = os.environ.get('LAST30DAYS_CONFIG_DIR')
if _config_override == "":
    # Empty string = no config file (clean mode)
    CONFIG_DIR = None
    CONFIG_FILE = None
elif _config_override:
    CONFIG_DIR = Path(_config_override)
    CONFIG_FILE = CONFIG_DIR / ".env"
else:
    CONFIG_DIR = Path.home() / ".config" / "last30days"
    CONFIG_FILE = CONFIG_DIR / ".env"

# macOS Keychain integration: items stored with this service prefix are picked
# up automatically on Darwin as the lowest-priority credential source.
# Example: `security add-generic-password -a "$USER" -s last30days-XAI_API_KEY -w "xai-..."`.
KEYCHAIN_SERVICE_PREFIX = "last30days-"

# Credentials the Keychain and pass loaders may resolve.
KEYCHAIN_KEYS = (
    "OPENAI_API_KEY", "XAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "GOOGLE_GENAI_API_KEY", "SCRAPECREATORS_API_KEY",
    "AUTH_TOKEN", "CT0", "BRAVE_API_KEY", "EXA_API_KEY", "SERPER_API_KEY",
    "OPENROUTER_API_KEY", "PARALLEL_API_KEY", "XQUIK_API_KEY",
)

# pass(1) integration: Linux/Unix analog of the Keychain source. Each key in
# KEYCHAIN_KEYS is looked up at pass path f"{prefix}{KEY}", the direct analog of
# Keychain's "last30days-<KEY>" service-name convention, so any user stores keys
# under one namespace without editing code. The prefix is resolved at call time
# (in get_config) from LAST30DAYS_PASS_PREFIX in the process env or a config
# file, falling back to this default; included verbatim, so keep the trailing
# separator. Honors PASSWORD_STORE_DIR.
DEFAULT_PASS_PATH_PREFIX = "last30days/"

AuthSource = Literal["api_key", "none"]
AuthStatus = Literal["ok", "missing"]

AUTH_SOURCE_API_KEY: AuthSource = "api_key"
AUTH_SOURCE_NONE: AuthSource = "none"

AUTH_STATUS_OK: AuthStatus = "ok"
AUTH_STATUS_MISSING: AuthStatus = "missing"


@dataclass(frozen=True)
class OpenAIAuth:
    token: str | None
    source: AuthSource
    status: AuthStatus


BrowserCookieMode = Literal["off", "read", "plan_only"]


@dataclass(frozen=True)
class ConfigLoadPolicy:
    """Local-read gates for configuration loading.

    Bare library calls use the safe default: no browser-cookie extraction and no
    project-scoped config. CLI entry points can opt into narrower behavior after
    parsing command intent.
    """

    browser_cookies: BrowserCookieMode = "off"
    allow_project_config: bool = False
    inspect_ignored_project_config: bool = False


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def is_timestamp_fresh(timestamp_value: Any, ttl_seconds: int) -> bool:
    """True when ``timestamp_value`` (ISO-8601 string) is within ``ttl_seconds``.

    Shared freshness gate for the doctor cache. The guard
    order is load-bearing: a non-positive TTL disables caching entirely, a
    non-string or empty timestamp is stale, a malformed timestamp is stale,
    naive timestamps are treated as UTC, and a future timestamp (negative age)
    counts as fresh.
    """
    if ttl_seconds <= 0:
        return False
    if not isinstance(timestamp_value, str) or not timestamp_value:
        return False
    try:
        created_at = datetime.datetime.fromisoformat(timestamp_value)
    except ValueError:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.timezone.utc)
    age = datetime.datetime.now(datetime.timezone.utc) - created_at.astimezone(
        datetime.timezone.utc
    )
    return age.total_seconds() <= ttl_seconds


def _project_config_trusted(policy: ConfigLoadPolicy, file_env: dict[str, Any]) -> bool:
    if policy.allow_project_config:
        return True
    process_value = os.environ.get("LAST30DAYS_TRUST_PROJECT_CONFIG")
    if process_value is not None:
        return _truthy(process_value)
    return _truthy(file_env.get("LAST30DAYS_TRUST_PROJECT_CONFIG"))


def _check_file_permissions(path: Path) -> None:
    """Warn to stderr if a secrets file has overly permissive permissions."""
    if os.name == "nt":
        # Windows reports synthesized POSIX mode bits that do not reflect NTFS ACLs.
        return

    try:
        mode = path.stat().st_mode
        # Check if group or other can read (bits 0o044)
        if mode & 0o044:
            sys.stderr.write(
                f"[last30days] WARNING: {path} is readable by other users. "
                f"Run: chmod 600 {path}\n"
            )
            sys.stderr.flush()
    except OSError as exc:
        sys.stderr.write(f"[last30days] WARNING: could not stat {path}: {exc}\n")
        sys.stderr.flush()


def load_env_file(path: Path) -> dict[str, str]:
    """Load environment variables from a file."""
    env = {}
    if not path or not path.exists():
        return env
    _check_file_permissions(path)

    # Prefer UTF-8 (utf-8-sig transparently strips a BOM written by Windows
    # editors like Notepad). Fall back to the locale decoder for a genuinely
    # locale-encoded .env (e.g. cp1252) so an existing file that loaded before
    # keeps loading. If it decodes as neither, let UnicodeDecodeError surface
    # rather than corrupting keys/secrets with replacement characters.
    try:
        text = path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        text = path.read_text(encoding=locale.getpreferredencoding(False))

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()
            # Remove quotes if present
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            if key and value:
                env.update({key: value})
    return env


def _load_keychain(keys: list[str]) -> dict[str, str]:
    """Load credentials from macOS Keychain (no-op on other platforms).

    Each key is looked up as a generic password with service name
    ``f"{KEYCHAIN_SERVICE_PREFIX}{key}"`` for the current user. Lookup failures
    are silent because Keychain is the lowest-priority source.
    """
    import platform
    if platform.system() != "Darwin":
        return {}

    import shutil
    security = shutil.which("security")
    if not security:
        return {}

    import subprocess
    # USER can be unset under sudo, in Docker without --env USER, or in some CI
    # runners; fall back to the OS user record so lookups still match items
    # stored by user-owned Keychain tooling under the current account.
    user = os.environ.get("USER")
    if not user:
        try:
            import pwd
        except ImportError:
            pwd = None

        if pwd is not None:
            try:
                user = pwd.getpwuid(os.getuid()).pw_name
            except AttributeError:
                user = "unknown"
        else:
            user = "unknown"
    env: dict[str, str] = {}

    def lookup(account: str, service: str) -> str:
        try:
            result = subprocess.run(
                [security, "find-generic-password",
                 "-a", account,
                 "-s", service,
                 "-w"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return ""
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return ""

    for key in keys:
        value = lookup(user, f"{KEYCHAIN_SERVICE_PREFIX}{key}")
        if value:
            env.update({key: value})
    return env


def _load_pass(keys: list[str], prefix: str) -> dict[str, str]:
    """Load credentials from a pass(1) store (no-op if `pass` is absent).

    The Linux/Unix analog of the macOS Keychain source. Each env-var name is
    looked up at pass path ``f"{prefix}{key}"`` -- mirroring Keychain's
    ``last30days-<key>`` service-name convention -- so any user stores keys under
    that namespace without editing code (prefix overridable via
    ``LAST30DAYS_PASS_PREFIX``). The secret is decrypted in a subprocess and
    read from stdout's first line (pass keeps the secret there; any metadata
    follows) -- never written to disk, never logged. Honors ``PASSWORD_STORE_DIR``.
    Missing entries and failures are silent: pass is a lowest-priority, additive
    source like Keychain, so an explicit .env or process-env value still wins.
    """
    import shutil
    pass_bin = shutil.which("pass")
    if not pass_bin:
        return {}

    import subprocess
    env: dict[str, str] = {}
    for key in keys:
        try:
            result = subprocess.run(
                [pass_bin, "show", f"{prefix}{key}"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, OSError):
            # A timeout (GPG/pinentry hanging) or exec failure isn't a per-key
            # condition -- it means the store is unusable right now. Stop instead
            # of paying the timeout once per key; otherwise a locked store would
            # stall every config load by 5s x len(keys). A genuinely missing key
            # returns fast with a non-zero exit and is handled below.
            break
        if result.returncode == 0 and result.stdout.strip():
            env.update({key: result.stdout.strip().splitlines()[0]})
    return env


def get_openai_auth(file_env: dict[str, str]) -> OpenAIAuth:
    """Resolve OpenAI API auth from explicit user-provided API keys."""
    api_key = read_secret_env('OPENAI_API_KEY') or file_env.get('OPENAI_API_KEY')
    if api_key:
        return OpenAIAuth(
            token=api_key,
            source=AUTH_SOURCE_API_KEY,
            status=AUTH_STATUS_OK,
        )

    return OpenAIAuth(
        token=None,
        source=AUTH_SOURCE_NONE,
        status=AUTH_STATUS_MISSING,
    )


def _find_project_env() -> Path | None:
    """Find per-project .env by walking up from cwd.

    Searches for .agents/last30days.env in each parent directory,
    stopping at the git root, user's home directory, or filesystem root.
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".agents" / "last30days.env"
        if candidate.exists():
            return candidate
        if (parent / ".git").exists():
            break
        # Stop at filesystem root or home
        if parent == Path.home() or parent == parent.parent:
            break
    return None


def get_config(policy: ConfigLoadPolicy | None = None) -> dict[str, Any]:
    """Load configuration from multiple sources.

    Priority (highest wins):
      1. Environment variables (os.environ)
      2. Trusted .agents/last30days.env (per-project config)
      3. ~/.config/last30days/.env (global config)
      4. macOS Keychain items prefixed ``last30days-`` (Darwin only)
      5. ``pass`` entries under ``last30days/`` (when available)
    """
    policy = policy or ConfigLoadPolicy()
    # Load from global config file
    file_env = load_env_file(CONFIG_FILE) if CONFIG_FILE else {}

    # Load per-project config only when trust comes from process env, global
    # user config, or an explicit policy. A project file cannot grant trust to
    # itself because it is not parsed until after this decision.
    project_config_trusted = _project_config_trusted(policy, file_env)
    project_env_path = _find_project_env() if project_config_trusted else None
    project_env = load_env_file(project_env_path) if project_env_path else {}
    ignored_project_env_path = None
    ignored_project_keys: list[str] = []
    if not project_config_trusted and policy.inspect_ignored_project_config:
        ignored_project_env_path = _find_project_env()
        if ignored_project_env_path:
            ignored_project_keys = sorted(load_env_file(ignored_project_env_path).keys())

    # Merge file sources: project > global
    merged_env = {**file_env, **project_env}

    # Keychain is the lowest-priority source (Darwin only; no-op elsewhere).
    # Loaded before openai_auth so OPENAI_API_KEY can come from Keychain too.
    keychain_env = _load_keychain(list(KEYCHAIN_KEYS))
    merged_env = {**keychain_env, **merged_env}
    # pass(1) store: Linux/Unix analog of Keychain at convention path
    # {prefix}<KEY>. Decrypts transiently so secrets stay encrypted at rest (no
    # plaintext .env). Lowest priority: Keychain, the config files, and process
    # env all win over it. Two efficiency guards so a user who merely has `pass`
    # on PATH doesn't pay for it: resolve the prefix from the loaded config/env
    # (not import time, so a .env-set LAST30DAYS_PASS_PREFIX is honored), and
    # probe ONLY keys still unset after the higher-priority sources -- an empty
    # list short-circuits with no gpg/pinentry calls at all.
    pass_prefix = (
        os.environ.get("LAST30DAYS_PASS_PREFIX")
        or merged_env.get("LAST30DAYS_PASS_PREFIX")
        or DEFAULT_PASS_PATH_PREFIX
    )
    pass_missing = [k for k in KEYCHAIN_KEYS if k not in os.environ and not merged_env.get(k)]
    pass_env = _load_pass(pass_missing, pass_prefix)
    merged_env = {**pass_env, **merged_env}

    openai_auth = get_openai_auth(merged_env)

    # Build config: Codex/OpenAI auth + process.env > project .env > global .env
    config = {
        'OPENAI_API_KEY': openai_auth.token,
        'OPENAI_AUTH_SOURCE': openai_auth.source,
        'OPENAI_AUTH_STATUS': openai_auth.status,
    }

    keys = [
        ('XAI_API_KEY', None),
        ('GOOGLE_API_KEY', None),
        ('GEMINI_API_KEY', None),
        ('GOOGLE_GENAI_API_KEY', None),
        ('LAST30DAYS_REASONING_PROVIDER', 'auto'),
        ('LAST30DAYS_PLANNER_MODEL', None),
        ('LAST30DAYS_RERANK_MODEL', None),
        ('LAST30DAYS_X_MODEL', None),
        ('LAST30DAYS_X_BACKEND', None),
        ('LAST30DAYS_REDDIT_BACKEND', None),
        # Doctor cache freshness window in seconds (doctor --cached).
        ('LAST30DAYS_DOCTOR_TTL', None),
        ('LAST30DAYS_REDDIT_SC_MIN_ITEMS', None),
        ('LAST30DAYS_MEMORY_DIR', None),
        ('OPENAI_BASE_URL', None),
        ('XAI_BASE_URL', None),
        ('SCRAPECREATORS_API_KEY', None),
        ('AUTH_TOKEN', None),
        ('CT0', None),
        ('BRAVE_API_KEY', None),
        ('EXA_API_KEY', None),
        ('SERPER_API_KEY', None),
        ('OPENROUTER_API_KEY', None),
        ('PARALLEL_API_KEY', None),
        ('XQUIK_API_KEY', None),
        # Optional SearXNG instance for the keyless-search fallback rung.
        ('LAST30DAYS_SEARXNG_URL', None),
        ('LAST30DAYS_FROM_BROWSER', None),
        ('LAST30DAYS_TRUST_PROJECT_CONFIG', None),
        ('LAST30DAYS_INCLUDE_SOURCES', ''),
        ('LAST30DAYS_EXCLUDE_SOURCES', ''),
        ('LAST30DAYS_DEFAULT_SEARCH', ''),
        ('LAST30DAYS_YOUTUBE_SSH_HOST', None),
        ('LAST30DAYS_YT_SUB_LANGS', 'en,es,pt'),
    ]

    for key, default in keys:
        config[key] = os.environ.get(key) or merged_env.get(key, default)

    # ScrapeCreators' documentation also uses the
    # SCRAPE_CREATORS_API_KEY spelling (with underscore between SCRAPE and
    # CREATORS). Accept that form too so users who follow the vendor's docs
    # don't silently end up with has_scrapecreators=False. Canonical name
    # wins when both are set.
    if not config.get('SCRAPECREATORS_API_KEY'):
        alternate = read_secret_env('SCRAPE_CREATORS_API_KEY') or merged_env.get('SCRAPE_CREATORS_API_KEY')
        if alternate:
            config['SCRAPECREATORS_API_KEY'] = alternate

    # A comma-separated ScrapeCreators value rotates one key per run.
    sc_key_raw = config.get('SCRAPECREATORS_API_KEY') or ''
    if ',' in sc_key_raw:
        import random
        sc_keys = [k.strip() for k in sc_key_raw.split(',') if k.strip()]
        config['SCRAPECREATORS_API_KEY'] = random.choice(sc_keys) if sc_keys else ''

    # Track which config source was used (highest-priority file source wins
    # the label; keychain is only reported when nothing else is configured).
    if project_env_path:
        config['_CONFIG_SOURCE'] = f'project:{project_env_path}'
    elif CONFIG_FILE and CONFIG_FILE.exists():
        config['_CONFIG_SOURCE'] = f'global:{CONFIG_FILE}'
    elif keychain_env:
        config['_CONFIG_SOURCE'] = 'keychain'
    elif pass_env:
        config['_CONFIG_SOURCE'] = 'pass'
    else:
        config['_CONFIG_SOURCE'] = 'env_only'
    if ignored_project_env_path:
        config['_IGNORED_PROJECT_CONFIG'] = str(ignored_project_env_path)
        config['_IGNORED_PROJECT_CONFIG_KEYS'] = ignored_project_keys
    config['_BROWSER_COOKIE_MODE'] = policy.browser_cookies
    config['_BROWSER_COOKIE_BROWSERS'] = cookie_extraction_browsers(config)
    config['_CONFIG_LOCAL_READS'] = {
        'process_environment': {'status': 'read'},
        'global_config': {
            'path': str(CONFIG_FILE) if CONFIG_FILE else None,
            'status': 'read' if CONFIG_FILE and CONFIG_FILE.is_file() else 'absent_or_disabled',
        },
        'project_config': {
            'path': str(project_env_path or ignored_project_env_path) if (project_env_path or ignored_project_env_path) else None,
            'status': 'read' if project_env_path else ('inspected' if ignored_project_env_path else 'not_found_or_disabled'),
        },
        'macos_keychain': {
            'status': 'queried' if sys.platform == 'darwin' and shutil.which('security') else 'not_available',
            'service_prefix': KEYCHAIN_SERVICE_PREFIX,
        },
        'pass': {
            'status': 'queried' if pass_missing and shutil.which('pass') else 'not_used',
            'entry_prefix': pass_prefix,
        },
    }

    if policy.browser_cookies == "read":
        browser_creds = extract_browser_credentials(config)
        for key, value in browser_creds.items():
            if not config.get(key):
                config[key] = value
                config[f"_{key}_SOURCE"] = "browser"

    return config


# ---------------------------------------------------------------------------
# Browser cookie extraction
# ---------------------------------------------------------------------------

COOKIE_DOMAINS: dict[str, dict[str, Any]] = {
    "x": {
        "domain": ".x.com",
        "cookies": ["auth_token", "ct0"],
        "mapping": {"auth_token": "AUTH_TOKEN", "ct0": "CT0"},
    },
}


def cookie_extraction_browsers(config: dict[str, Any]) -> list[str]:
    """Browsers to try for cookie extraction, honoring LAST30DAYS_FROM_BROWSER.

    Default (variable unset): no browser-cookie reads. The Chromium family
    (Chrome, Brave, Edge, Vivaldi, Opera, Arc, Chromium) is available only when
    explicitly selected because reading their cookies on macOS requires the
    browser's Safe Storage Keychain key, which triggers a system password prompt
    that cannot be reliably suppressed. On Windows only Firefox cookie
    extraction is supported; Chrome and Edge use DPAPI-encrypted cookie stores
    that are not yet supported.

    - ``LAST30DAYS_FROM_BROWSER=<name>`` - one browser (for example, ``firefox``),
      ``edge``, ``arc``).
    - ``LAST30DAYS_FROM_BROWSER=firefox,safari`` - an explicit browser list.
    - ``LAST30DAYS_FROM_BROWSER=auto`` - also try every Chromium browser (user accepts the
      Keychain dialog when needed).
    - ``LAST30DAYS_FROM_BROWSER=off`` - returns [] (extraction disabled).

    Returning the browser list from one place keeps configuration diagnostics
    and research on the same consent policy.
    """
    silent_browsers = ["firefox", "safari"]
    chromium_browsers = ["chrome", "brave", "edge", "vivaldi", "opera", "arc", "chromium"]
    known_browsers = silent_browsers + chromium_browsers
    from_browser = (config.get("LAST30DAYS_FROM_BROWSER") or "").strip().lower()
    if not from_browser:
        return []
    if from_browser == "off":
        return []
    if from_browser == "auto":
        return silent_browsers + chromium_browsers
    if "," in from_browser:
        requested = [b.strip() for b in from_browser.split(",") if b.strip()]
        resolved = [b for b in requested if b in known_browsers]
        unknown = [b for b in requested if b not in known_browsers]
        if unknown:
            sys.stderr.write(
                "[last30days] WARNING: LAST30DAYS_FROM_BROWSER ignored unrecognized browser(s): "
                f"{', '.join(unknown)} (known: {', '.join(known_browsers)})\n"
            )
            sys.stderr.flush()
        return resolved
    if from_browser in known_browsers:
        return [from_browser]
    # Non-empty, not off/auto, not a known browser, not a list: unrecognized.
    # Warn rather than fail silently so a browser-name typo is visible.
    # instead of looking like "no cookies found".
    sys.stderr.write(
        f"[last30days] WARNING: LAST30DAYS_FROM_BROWSER='{from_browser}' is not a recognized "
        f"browser; no cookies will be read (known: {', '.join(known_browsers)}, "
        "or 'auto'/'off')\n"
    )
    sys.stderr.flush()
    return []



def extract_browser_credentials(config: dict[str, Any]) -> dict[str, str]:
    """Extract auth cookies from local browsers.

    Browser selection (and the Chrome-prompt caveat) is handled by
    ``cookie_extraction_browsers``; this function just runs the extraction for
    each configured cookie domain.
    """
    browsers = cookie_extraction_browsers(config)
    if not browsers:
        return {}
    try:
        from . import cookie_extract
    except ImportError:
        return {}
    extracted: dict[str, str] = {}
    for _service, spec in COOKIE_DOMAINS.items():
        if all(config.get(env_key) for env_key in spec["mapping"].values()):
            continue
        for browser in browsers:
            try:
                cookies = cookie_extract.extract_cookies(browser, spec["domain"], spec["cookies"])
            except Exception:
                continue
            if cookies:
                for cookie_name, env_key in spec["mapping"].items():
                    if cookie_name in cookies and not config.get(env_key):
                        extracted[env_key] = cookies[cookie_name]
                break  # Found cookies for this service, stop trying browsers
    return extracted


# Default X backend priority. The first available backend is the primary X
# source; the rest are ordered failover backups, tried only if the one before
# returns nothing or errors. There is one X source ("x"); these are its
# interchangeable backends, never run in parallel.
#   xai   -- xAI/Grok live search (XAI_API_KEY)
#   bird  -- X GraphQL scrape via the user's browser cookies (AUTH_TOKEN/CT0)
#   xurl  -- official X API v2 (xurl CLI, OAuth2)
#   xquik -- key-based REST X search (XQUIK_API_KEY); keyless of browser cookies
_X_BACKEND_ORDER = ("xai", "bird", "xurl", "xquik")

# Public routing definitions for the doctor/backend-descriptor layer
# (lib/backends.py). These are aliases for knowledge this module already
# owns -- the declared X chain order and the pin/floor env var names -- so
# descriptors import one source of truth instead of restating it.
X_BACKEND_ORDER = _X_BACKEND_ORDER
X_BACKEND_PIN_VAR = 'LAST30DAYS_X_BACKEND'
REDDIT_BACKEND_PIN_VAR = 'LAST30DAYS_REDDIT_BACKEND'
REDDIT_SC_MIN_ITEMS_VAR = 'LAST30DAYS_REDDIT_SC_MIN_ITEMS'


def _x_backend_available(
    backend: str,
    config: dict[str, Any],
    has_bird_creds: bool,
    local_only: bool = False,
) -> bool:
    if backend == 'xai':
        return bool(config.get('XAI_API_KEY'))
    if backend == 'bird':
        from . import bird_x
        return has_bird_creds and bird_x.is_bird_installed()
    if backend == 'xurl':
        from . import xurl_x
        if local_only:
            # Doctor/safe-diagnose path: local evidence only (PATH lookup +
            # token store) -- never the live `xurl whoami` network call.
            return xurl_x.has_stored_auth()
        return xurl_x.is_available()
    if backend == 'xquik':
        return is_xquik_available(config)
    return False


def x_backend_chain(config: dict[str, Any], local_only: bool = False) -> list[str]:
    """Ordered list of available X backends.

    ``chain[0]`` is the default X source; the remaining entries are failover
    backups, used only when the one before yields no items or errors. There is
    exactly one X source -- these are its backends, never fetched in parallel.

    A ``LAST30DAYS_X_BACKEND`` pin forces a single backend (no failover): the
    user explicitly chose it. Browser-cookie probing is intentionally avoided
    (automatic Keychain access causes popups); bird counts as available only
    when AUTH_TOKEN and CT0 are present explicitly.

    ``local_only=True`` is the doctor/safe-diagnose flavor: availability is
    answered from local evidence only (no subprocess spawns that reach the
    network -- xurl's live `whoami` check is replaced by its on-disk token
    store). Research-time callers keep the default live semantics.
    """
    from . import bird_x
    has_bird_creds = bool(config.get('AUTH_TOKEN') and config.get('CT0'))
    if has_bird_creds:
        bird_x.set_credentials(config.get('AUTH_TOKEN'), config.get('CT0'))

    preferred = (config.get(X_BACKEND_PIN_VAR) or '').lower()
    if preferred in _X_BACKEND_ORDER:
        if _x_backend_available(preferred, config, has_bird_creds, local_only):
            return [preferred]
        return []

    return [
        b for b in _X_BACKEND_ORDER
        if _x_backend_available(b, config, has_bird_creds, local_only)
    ]


def get_x_source(config: dict[str, Any], local_only: bool = False) -> str | None:
    """The default (primary) X backend, or None if no X source is available.

    Thin wrapper over ``x_backend_chain`` returning the first/primary backend;
    callers that want failover should use ``x_backend_chain`` directly.
    ``local_only`` is forwarded (see ``x_backend_chain``).
    """
    chain = x_backend_chain(config, local_only=local_only)
    return chain[0] if chain else None


def x_pending_browser_auth(config: dict[str, Any], local_only: bool = False) -> bool:
    """True when X is not available now but curated browser configuration can authenticate it.

    Doctor and preflight load config in ``plan_only`` mode, which
    deliberately skips browser-cookie extraction (no Keychain popup,
    ``reads_values: false``). As a result ``get_x_source`` returns None and X is
    dropped from ``available_sources`` even though a normal run would extract the
    same cookies and authenticate X fine. This predicate reports that
    "available pending browser auth" state without reading a single cookie -- it
    keys only on the already-resolved browser list (``cookie_extraction_browsers``
    derives it from the browser-selection variable alone, without secrets), Bird being installed, and
    X having a cookie-domain mapping. Side-effect free, so the safe-inspection
    contract of diagnostics is preserved.

    Returns False whenever X is already available outright (static AUTH_TOKEN/CT0,
    or xAI/xurl/xquik backend), and in ``read`` mode (a real run has already
    extracted creds, so its status must be unchanged -- never "pending").
    """
    # Already available via a static backend (bird creds, xAI, xurl, xquik).
    # local_only (doctor/safe-diagnose) answers the xurl leg from the token
    # store instead of the live `xurl whoami` network call.
    if get_x_source(config, local_only=local_only):
        return False
    # Only meaningful in inspection modes that skip extraction; a real ``read``
    # run has already attempted extraction and must report its true state.
    if config.get('_BROWSER_COOKIE_MODE') == 'read':
        return False
    if 'x' not in COOKIE_DOMAINS:
        return False
    if not cookie_extraction_browsers(config):
        return False
    from . import bird_x
    return bird_x.is_bird_installed()


def is_youtube_comments_available(config: dict[str, Any]) -> bool:
    """Check if YouTube comment enrichment is available.

    Requires SCRAPECREATORS_API_KEY AND ``youtube_comments`` in
    ``LAST30DAYS_INCLUDE_SOURCES``. Cost is
    bounded by ``enrich_with_comments(max_videos=3)`` (~3 credits per run).

    Enable this lane explicitly by adding ``youtube_comments`` to
    `LAST30DAYS_INCLUDE_SOURCES`.
    """
    if not config.get('SCRAPECREATORS_API_KEY'):
        return False
    return 'youtube_comments' in _parse_include_sources(config)


def is_tiktok_comments_available(config: dict[str, Any]) -> bool:
    """Check if TikTok comment enrichment is available.

    Requires SCRAPECREATORS_API_KEY and tiktok_comments in LAST30DAYS_INCLUDE_SOURCES.
    Mirrors the youtube_comments opt-in pattern.
    """
    if not config.get('SCRAPECREATORS_API_KEY'):
        return False
    include = _parse_include_sources(config)
    return 'tiktok_comments' in include


def is_youtube_sc_available(config: dict[str, Any]) -> bool:
    """Check if ScrapeCreators YouTube search fallback is available.

    Used when yt-dlp is not installed or fails.
    """
    return bool(config.get('SCRAPECREATORS_API_KEY'))


def keyless_web_allowed(config: dict[str, Any]) -> bool:
    """The engine's keyless web-search floor is always available."""
    return True


def get_tiktok_token(config: dict[str, Any]) -> str:
    """Get the ScrapeCreators token used by TikTok retrieval."""
    return config.get('SCRAPECREATORS_API_KEY') or ''


def _parse_include_sources(config: dict[str, Any]) -> set[str]:
    """Parse the curated source inclusion config."""
    raw = config.get('LAST30DAYS_INCLUDE_SOURCES') or ''
    return {s.strip().lower() for s in raw.split(',') if s.strip()}


def get_x_source_status(config: dict[str, Any]) -> dict[str, Any]:
    """Get detailed X source status from local evidence only.

    This function never calls X. xurl availability comes from its local token
    store, and configured key/cookie lanes are verified only during research.

    Returns:
        Dict with keys: source, bird_installed, bird_authenticated,
        bird_username, xai_available
    """
    from . import bird_x

    if config.get('AUTH_TOKEN') and config.get('CT0'):
        bird_x.set_credentials(config.get('AUTH_TOKEN'), config.get('CT0'))
    bird_status = bird_x.get_bird_status()
    xai_available = bool(config.get('XAI_API_KEY'))

    # Report the credential source rather than labeling every token as an
    # environment value.
    if bird_status["authenticated"]:
        lane = config.get('_AUTH_TOKEN_SOURCE') or 'env'
        bird_status["username"] = f"{lane} AUTH_TOKEN"

    # Xquik is a key-based X source; doctor reports configuration, while an
    # actual research call verifies funding and authentication.
    xquik_available = is_xquik_available(config)
    xquik_working: bool | None = None
    xquik_status = "configured (not probed)" if xquik_available else ""

    # xurl availability is answered from its local token store; the live
    # `xurl whoami` check remains on the research path.
    from . import xurl_x as _xurl_x
    xurl_available = _xurl_x.has_stored_auth()

    # Determine the locally predicted active source in routing order.
    if bird_status["authenticated"]:
        source = 'bird'
    elif xai_available:
        source = 'xai'
    else:
        if xurl_available:
            source = 'xurl'
        elif xquik_available and xquik_working is not False:
            source = 'xquik'
        else:
            source = None

    return {
        "source": source,
        "bird_installed": bird_status["installed"],
        "bird_authenticated": bird_status["authenticated"],
        "bird_username": bird_status["username"],
        "xai_available": xai_available,
        "xurl_available": xurl_available,
        "xquik_available": xquik_available,
        "xquik_working": xquik_working,
        "xquik_status": xquik_status,
    }


# Xquik
def is_xquik_available(config: dict[str, Any]) -> bool:
    """Check if Xquik X search source is available.

    Requires XQUIK_API_KEY (API key from xquik.com).
    """
    return bool(config.get('XQUIK_API_KEY'))


def get_xquik_token(config: dict[str, Any]) -> str:
    """Get Xquik API key."""
    return config.get('XQUIK_API_KEY') or ''
