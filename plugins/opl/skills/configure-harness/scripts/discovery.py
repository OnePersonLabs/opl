"""Read-only, provenance-aware inventory for configure-harness.

Installed Codex state comes only from the native inventory adapter. Files on
disk describe available candidates; their presence never implies enablement.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil


_INVENTORY_FILE = Path(__file__).resolve().parents[3] / "scripts" / "opl_codex_inventory.py"
_MAX_FILE_BYTES = 512_000
_MAX_ENTRIES = 2_000
_SECRET = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[:=]\s*)"
    r"([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/-]+")
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/@\s]+@")


def _inventory_adapter():
    spec = importlib.util.spec_from_file_location("opl_codex_inventory", _INVENTORY_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_inventory = _inventory_adapter()
collect_inventory = _inventory.collect_inventory


def list_registered_marketplaces(cwd: Path, home: Path) -> list[Path]:
    """Read Codex's registered marketplace roots without contacting a server."""
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(home)
    response = _inventory._cli(_inventory._command(), ["plugin", "marketplace", "list", "--json"],
                               cwd, environment, 10.0)
    if not isinstance(response, dict) or not isinstance(response.get("marketplaces"), list):
        raise ValueError("Codex marketplace list returned an invalid shape.")
    roots = []
    for entry in response["marketplaces"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("root"), str):
            raise ValueError("Codex marketplace list omitted a local root.")
        root = Path(entry["root"])
        if not root.is_absolute():
            raise ValueError("Codex marketplace root is not absolute.")
        roots.append(root)
    return roots


def _safe_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    redacted = _BEARER.sub("Bearer [redacted]", value)
    redacted = _SECRET.sub(lambda match: match.group(1) + "[redacted]", redacted)
    return _URL_CREDENTIALS.sub(r"\1[redacted]@", redacted)


def _description(item: dict, value: object) -> None:
    description = _safe_text(value).strip()
    item["description"] = description
    item["summary"] = description[:256]
    item["textChars"] = len(description)
    item["estimatedTokens"] = math.ceil(len(description) / 4)
    item["tokenEstimateBasis"] = "description characters / 4"


def _diagnostic(result: dict, code: str, message: str, source: str, **fields: str) -> None:
    result["diagnostics"].append({"code": code, "message": message, "source": source,
                                  **{key: _safe_text(value) for key, value in fields.items()}})


def _inside(path: Path, root: Path) -> bool:
    return not path.is_symlink() and path.resolve().is_relative_to(root.resolve())


def _read_json(path: Path, root: Path) -> dict:
    if not _inside(path, root) or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("Manifest is missing, outside its root, or too large.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Manifest must be a JSON object.")
    return value


def _manifest_path(plugin_root: Path) -> Path | None:
    """Codex accepts both `.codex-plugin` and root-level plugin manifests."""
    for path in (plugin_root / ".codex-plugin" / "plugin.json", plugin_root / "plugin.json"):
        if path.is_file() and not path.is_symlink():
            return path
    return None


def _skill_metadata(path: Path) -> dict:
    """Read only small YAML frontmatter scalars; no YAML loader or execution."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
        return {}
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return {}
    metadata: dict[str, object] = {}
    index = 1
    while index < end:
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        key, value = match.groups()
        if key in ("name", "description"):
            if value in (">", ">-", "|", "|-"):
                chunks = []
                index += 1
                while index < end and (lines[index].startswith((" ", "\t")) or not lines[index].strip()):
                    chunks.append(lines[index].strip())
                    index += 1
                metadata[key] = (" " if value.startswith(">") else "\n").join(chunks).strip()
                continue
            metadata[key] = value.strip().strip('"\'')
        elif key == "dependencies" and value.startswith("["):
            try:
                dependencies = json.loads(value)
                if isinstance(dependencies, list):
                    metadata[key] = [part for part in dependencies if isinstance(part, str)]
            except json.JSONDecodeError:
                pass
        elif key == "dependencies" and not value:
            dependencies = []
            index += 1
            while index < end and (lines[index].startswith((" ", "\t")) or not lines[index].strip()):
                match = re.match(r"^\s+-\s+(.+?)\s*$", lines[index])
                if match:
                    dependencies.append(match.group(1).strip('"\''))
                index += 1
            metadata[key] = dependencies
            continue
        index += 1
    return metadata


def _policy_metadata(path: Path) -> dict:
    metadata_path = path.parent / "agents" / "openai.yaml"
    if metadata_path.is_symlink() or not metadata_path.is_file() or metadata_path.stat().st_size > _MAX_FILE_BYTES:
        return {"implicitInvocation": None, "dependencyMetadataComplete": None}
    content = metadata_path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*allow_implicit_invocation:\s*(true|false)\s*(?:#.*)?$", content)
    metadata = {"implicitInvocation": match.group(1) == "true" if match else None,
                "dependencyMetadataComplete": True, "declaredTools": []}
    lines = content.splitlines()
    dependency_start = next((i for i, line in enumerate(lines) if line == "dependencies:"), None)
    if dependency_start is None:
        return metadata
    end = next((i for i in range(dependency_start + 1, len(lines))
                if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    section = lines[dependency_start + 1:end]
    tools_start = next((i for i, line in enumerate(section) if re.match(r"^\s+tools:\s*$", line)), None)
    if tools_start is None:
        metadata["dependencyMetadataComplete"] = False
        return metadata
    tools = []
    current = None
    for line in section[tools_start + 1:]:
        entry = re.match(r"^\s+-\s+(name|type|value):\s*(.*?)\s*$", line)
        if entry:
            if current is not None:
                tools.append(current)
            current = {entry.group(1): entry.group(2).strip('"\'')}
            continue
        field = re.match(r"^\s+(name|type|value):\s*(.*?)\s*$", line)
        if field and current is not None:
            current[field.group(1)] = field.group(2).strip('"\'')
        elif line.strip() and not line.lstrip().startswith("#") and not re.match(r"^\s+description:", line):
            metadata["dependencyMetadataComplete"] = False
    if current is not None:
        tools.append(current)
    safe_id = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    for tool in tools:
        if all(isinstance(tool.get(key), str) and safe_id.fullmatch(tool[key]) for key in ("name", "type", "value")):
            metadata["declaredTools"].append({key: tool[key] for key in ("name", "type", "value")})
        else:
            metadata["dependencyMetadataComplete"] = False
    return metadata


def _skill_item(path: Path, source: str, plugin: str | None, enabled: bool | None = None) -> dict:
    metadata = _skill_metadata(path)
    name = _safe_text(metadata.get("name") or path.parent.name)
    item = {"kind": "skill", "id": f"skill:{plugin or ''}:{path.resolve()}", "name": name,
            "source": source, "plugin": plugin, "path": str(path.resolve()),
            "enabled": enabled, "onDemand": None, **_policy_metadata(path)}
    _description(item, metadata.get("description"))
    if metadata.get("dependencies"):
        item["dependencies"] = [_safe_text(part) for part in metadata["dependencies"]]
    return item


def _plugin_item(manifest: dict, path: Path, source: str, owner: str | None = None) -> dict:
    plugin_root = path.parent.parent if path.parent.name == ".codex-plugin" else path.parent
    name = _safe_text(manifest.get("name") or plugin_root.name)
    item = {"kind": "plugin", "id": f"plugin:{source}:{owner or name}:{plugin_root.resolve()}",
            "name": name, "source": source, "plugin": owner, "path": str(plugin_root.resolve()),
            "enabled": None, "onDemand": None}
    _description(item, manifest.get("description") or manifest.get("interface", {}).get("shortDescription")
                 if isinstance(manifest.get("interface", {}), dict) else manifest.get("description"))
    dependencies = manifest.get("dependencies")
    if isinstance(dependencies, list):
        item["dependencies"] = [_safe_text(part) for part in dependencies if isinstance(part, str)]
    return item


def _plugin_skills(plugin_root: Path, source: str, owner: str) -> list[dict]:
    skills_root = plugin_root / "skills"
    if not skills_root.is_dir() or not _inside(skills_root, plugin_root):
        return []
    items = []
    for skill_dir in sorted(skills_root.iterdir()):
        if len(items) >= _MAX_ENTRIES:
            break
        path = skill_dir / "SKILL.md"
        if skill_dir.is_dir() and _inside(skill_dir, plugin_root) and path.is_file() and _inside(path, plugin_root):
            items.append(_skill_item(path, source, owner))
    return items


def _native(result: dict, cwd: Path, home: Path) -> None:
    inventory = collect_inventory(cwd, codex_home=home)
    for kind in ("plugin", "skill", "mcp"):
        result["complete"][kind] = inventory.get("complete", {}).get(kind) is True
    for diagnostic in inventory.get("diagnostics", []):
        if isinstance(diagnostic, dict):
            _diagnostic(result, _safe_text(diagnostic.get("code")) or "native_error",
                        _safe_text(diagnostic.get("message")) or "Native inventory is incomplete.", "native")
    for native in inventory.get("items", []):
        if not isinstance(native, dict) or native.get("kind") not in ("plugin", "skill", "mcp"):
            continue
        if not _safe_text(native.get("id")) or not _safe_text(native.get("name")):
            result["complete"][native["kind"]] = False
            _diagnostic(result, "native_identity_missing", "Native metadata omitted an item identity.", "native")
            continue
        item = {"kind": native["kind"], "id": _safe_text(native.get("id")),
                "name": _safe_text(native.get("name")), "source": "native",
                "plugin": _safe_text(native["plugin"]) if isinstance(native.get("plugin"), str) else None,
                "enabled": native.get("enabled") if isinstance(native.get("enabled"), bool) else None,
                "onDemand": None}
        if native["kind"] == "skill" and isinstance(native.get("path"), str):
            path = Path(native["path"])
            item["path"] = str(path)
            try:
                metadata = _skill_metadata(path)
                item.update(_policy_metadata(path))
            except (OSError, UnicodeError):
                metadata = {}
                item["implicitInvocation"] = None
                item["dependencyMetadataComplete"] = False
                _diagnostic(result, "skill_metadata_unreadable", "Could not read native skill metadata.", "native")
            _description(item, metadata.get("description"))
            if metadata.get("dependencies"):
                item["dependencies"] = [_safe_text(part) for part in metadata["dependencies"]]
        else:
            _description(item, None)
        if isinstance(native.get("reason"), str):
            item["reason"] = _safe_text(native["reason"])
        result["items"].append(item)


def _cache(result: dict, home: Path) -> None:
    root = home / "plugins" / "cache"
    if not root.exists():
        return
    try:
        if not root.is_dir() or not _inside(root, home):
            raise ValueError("Plugin cache root is invalid.")
        count = 0
        for marketplace in sorted(root.iterdir()):
            if not marketplace.is_dir() or not _inside(marketplace, root):
                continue
            for plugin in sorted(marketplace.iterdir()):
                if not plugin.is_dir() or not _inside(plugin, root):
                    continue
                for version in sorted(plugin.iterdir()):
                    if not version.is_dir() or not _inside(version, root):
                        continue
                    count += 1
                    if count > _MAX_ENTRIES:
                        raise ValueError("Plugin cache entry limit exceeded.")
                    relative = version.relative_to(root).as_posix()
                    manifest_path = _manifest_path(version)
                    if manifest_path is None:
                        result["complete"]["cache"] = False
                        _diagnostic(result, "cache_manifest_missing", "A cached plugin version has no manifest.",
                                    "cache", path=relative)
                        continue
                    try:
                        manifest = _read_json(manifest_path, root)
                        owner = f"{_safe_text(manifest.get('name'))}@{marketplace.name}"
                        result["items"].append(_plugin_item(manifest, manifest_path, "cache", owner))
                        result["items"].extend(_plugin_skills(version, "cache", owner))
                    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                        result["complete"]["cache"] = False
                        cause = "invalid_json" if isinstance(error, json.JSONDecodeError) else "unreadable_manifest"
                        _diagnostic(result, "cache_manifest_invalid", "A cached plugin manifest could not be read.",
                                    "cache", path=relative, cause=cause)
    except (OSError, ValueError):
        result["complete"]["cache"] = False
        _diagnostic(result, "cache_scan_incomplete", "Plugin cache discovery is incomplete.", "cache")


def _marketplaces(result: dict, paths: list[Path]) -> None:
    for supplied in paths:
        path = Path(supplied).resolve()
        entry_path = None
        try:
            if path.name not in ("marketplace.json", "api_marketplace.json") or path.parent.name != "plugins" or path.parent.parent.name != ".agents":
                raise ValueError("Marketplace path is not a supported local manifest.")
            root = path.parent.parent.parent
            data = _read_json(path, root)
            entries = data.get("plugins")
            if not isinstance(entries, list) or len(entries) > _MAX_ENTRIES:
                raise ValueError("Marketplace plugin entries are invalid.")
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    raise ValueError("Marketplace entry is invalid.")
                source = entry.get("source")
                if not isinstance(source, dict) or source.get("source") != "local" or not isinstance(source.get("path"), str):
                    # Remote entries are catalog names only. Never fetch or execute them.
                    item = {"kind": "plugin", "id": f"plugin:marketplace:{path}:{entry['name']}",
                            "name": _safe_text(entry["name"]), "source": "marketplace", "plugin": None,
                            "enabled": None, "onDemand": None}
                    _description(item, entry.get("description"))
                    result["items"].append(item)
                    continue
                plugin_root = (root / source["path"]).resolve()
                if not plugin_root.is_relative_to(root) or plugin_root.is_symlink():
                    raise ValueError("Local plugin source escapes marketplace root.")
                entry_path = plugin_root.relative_to(root).as_posix()
                manifest_path = _manifest_path(plugin_root)
                if manifest_path is None:
                    result["complete"]["marketplace"] = False
                    _diagnostic(result, "marketplace_plugin_manifest_missing",
                                "A local marketplace plugin has no manifest.", "marketplace",
                                manifest=path.name, path=entry_path)
                    continue
                manifest = _read_json(manifest_path, root)
                owner = f"{_safe_text(entry['name'])}@{_safe_text(data.get('name')) or root.name}"
                result["items"].append(_plugin_item(manifest, manifest_path, "marketplace", owner))
                result["items"].extend(_plugin_skills(plugin_root, "marketplace", owner))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            result["complete"]["marketplace"] = False
            cause = "invalid_json" if isinstance(error, json.JSONDecodeError) else "invalid_or_unreadable_manifest"
            fields = {"manifest": path.name, "cause": cause}
            if entry_path is not None:
                fields["path"] = entry_path
            _diagnostic(result, "marketplace_invalid", "A local marketplace could not be fully read.",
                        "marketplace", **fields)


def _standalone(result: dict, cwd: Path, home: Path) -> None:
    roots = ((home / "skills", home), (home / "skills" / ".system", home),
             (home / ".agents" / "skills", home),
             (home.parent / ".agents" / "skills", home.parent),
             (cwd / ".agents" / "skills", cwd),
             (cwd / ".codex" / "skills", cwd))
    known = {(item.get("source"), item.get("path")) for item in result["items"]}
    for root, boundary in roots:
        try:
            if not root.exists():
                continue
            if not root.is_dir() or not _inside(root, boundary):
                raise ValueError("Skill root is invalid.")
            for index, skill_dir in enumerate(sorted(root.iterdir())):
                if index >= _MAX_ENTRIES:
                    raise ValueError("Skill entry limit exceeded.")
                path = skill_dir / "SKILL.md"
                if skill_dir.is_dir() and _inside(skill_dir, root) and path.is_file() and _inside(path, root):
                    item = _skill_item(path, "filesystem", None)
                    if (item["source"], item["path"]) not in known:
                        result["items"].append(item)
        except (OSError, UnicodeError, ValueError):
            result["complete"]["filesystem"] = False
            _diagnostic(result, "skill_scan_incomplete", "A standalone skill directory could not be fully read.", "filesystem")


def discover(cwd: Path, home: Path, marketplaces: list[Path], clis: list[str]) -> dict:
    """Discover configured state and local candidates without mutating either."""
    cwd, home = Path(cwd).resolve(), Path(home).resolve()
    result = {"schemaVersion": 1, "items": [], "diagnostics": [],
              "complete": {kind: True for kind in ("plugin", "skill", "mcp", "cache", "marketplace", "filesystem", "cli")}}
    _native(result, cwd, home)
    _cache(result, home)
    paths = []
    registered_count = None
    try:
        registered = list_registered_marketplaces(cwd, home)
        registered_count = len(registered)
        for root in registered:
            first = root / ".agents" / "plugins" / "marketplace.json"
            second = root / ".agents" / "plugins" / "api_marketplace.json"
            if first.is_file():
                paths.append(first)
            elif second.is_file():
                paths.append(second)
            else:
                result["complete"]["marketplace"] = False
                _diagnostic(result, "marketplace_manifest_missing",
                            "A registered local marketplace has no supported manifest.", "marketplace")
    except (_inventory.InventoryError, OSError, ValueError) as error:
        result["complete"]["marketplace"] = False
        _diagnostic(result, getattr(error, "code", "marketplace_registry_invalid"),
                    "Could not read Codex's registered marketplace list.", "marketplace")
    paths.extend(Path(path) for path in marketplaces)
    unique_paths = sorted({path.resolve() for path in paths})
    result["scope"] = {"registeredMarketplaceRoots": registered_count,
                       "marketplaceManifestsScanned": len(unique_paths),
                       "explicitMarketplaceManifests": len(marketplaces),
                       "cliNamesRequested": len(clis)}
    _marketplaces(result, unique_paths)
    _standalone(result, cwd, home)
    for name in clis:
        if not isinstance(name, str) or not name or any(char in name for char in ("/", "\\", "\0")):
            result["complete"]["cli"] = False
            _diagnostic(result, "cli_name_invalid", "A requested CLI name is invalid.", "path")
            continue
        found = shutil.which(name)
        item = {"kind": "cli", "id": f"cli:{name}", "name": name, "source": "path",
                "plugin": None, "enabled": None, "available": found is not None,
                "onDemand": None}
        _description(item, None)
        if found:
            item["path"] = str(Path(found).resolve())
        result["items"].append(item)
    result["items"].sort(key=lambda item: (item["kind"], item["name"], item["source"], item["id"]))
    return result
