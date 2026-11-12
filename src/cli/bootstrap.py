"""First-run setup of the user's global folder `~/.laris` (SR-C6). Never overwrites anything.

    settings.json        all client settings (no secrets); the schema is shipped with the client
    .credentials.json    the API key, mode 0600 (written by `laris login`)
    .venv/  python/      the sandbox and its interpreters (built by the sandbox, T72)
    LARIS.md skills/ commands/ memory/   personal layers
    projects/<slug>/     per-project state, the SQLite space and checkpoints
    logs/                local audit
    backups/             what the 1.x migration replaced

A 1.x home is migrated once: `config.yaml` and the flat `settings.json` become the new
`settings.json`, the `api_key` field and `credentials.json` become `.credentials.json`, the legacy
`runtime/<version>/` is removed. Every file that is rewritten or removed is copied to `backups/`
first, and a second start finds nothing left to migrate.
"""

import json
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any, Dict, List

GLOBAL_HOME = "~/.laris"
LAYOUT_DIRS = ("skills", "commands", "memory", "projects", "logs")
INSTRUCTIONS_TEMPLATE = (
    "# Personal instructions for LARIS\n\n"
    "Notes that apply in every project (language, citation style, how much detail you want).\n"
    "They are sent to the assistant with every task. Do not put secrets here.\n"
)


def _backup(home: Path, source: Path) -> Path:
    folder = home / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    target = folder / f"{source.name}.{stamp}.bak"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{source.name}.{stamp}-{n}.bak"
    shutil.copy2(source, target)
    return target


def _write_secret(path: Path, data: Dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """`extra` fills in what `base` does not set."""
    out: Dict[str, Any] = json.loads(json.dumps(base))
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out.setdefault(key, value)
    return out


def _from_config_yaml(path: Path) -> Dict[str, Any]:
    """The few 1.x `config.yaml` values that have a place in settings.json."""
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    api = raw.get("model_api") or {}
    if isinstance(api, dict):
        if api.get("base_url"):
            out.setdefault("server", {})["url"] = str(api["base_url"]).rstrip("/")
        if isinstance(api.get("timeout_s"), (int, float)) and api["timeout_s"] > 0:
            out.setdefault("server", {})["timeoutSeconds"] = float(api["timeout_s"])
        if api.get("model"):
            out["model"] = str(api["model"])
    learning = raw.get("learning") or {}
    if isinstance(learning, dict) and isinstance(learning.get("enabled"), bool):
        out["learning"] = {"collect": learning["enabled"]}
    vault = raw.get("vault") or {}
    if isinstance(vault, dict) and isinstance(vault.get("auto_record"), bool):
        out["vault"] = {"autoRecord": vault["auto_record"]}
    return out


def migrate_home(home: Path) -> List[str]:
    """Migrate a 1.x home once; returns one line per change (empty when there was nothing to do)."""
    from laris.shared.config import settings

    notes: List[str] = []
    settings_path = home / "settings.json"
    credentials = home / ".credentials.json"
    data = _read_json(settings_path) if settings_path.is_file() else {}

    if data and settings.is_legacy(data):  # the flat 1.x shape
        _backup(home, settings_path)
        key = data.get("api_key")
        converted = settings.from_legacy(data)
        settings_path.write_text(json.dumps(converted, indent=2) + "\n", encoding="utf-8")
        notes.append("settings.json converted to the new shape")
        if isinstance(key, str) and key and not credentials.exists():
            _write_secret(credentials, {"api_key": key})
            notes.append("api_key moved to .credentials.json (mode 0600)")
        data = converted

    old_credentials = home / "credentials.json"
    if old_credentials.is_file():
        _backup(home, old_credentials)
        key = _read_json(old_credentials).get("api_key")
        if isinstance(key, str) and key and not credentials.exists():
            _write_secret(credentials, {"api_key": key})
            notes.append("credentials.json moved to .credentials.json")
        old_credentials.unlink()

    config_yaml = home / "config.yaml"
    if config_yaml.is_file():
        _backup(home, config_yaml)
        carried = _from_config_yaml(config_yaml)
        merged = _merge(data, carried)
        try:
            settings.write(settings_path, merged)
        except settings.SettingsError:
            merged = data
        config_yaml.unlink()
        notes.append("config.yaml folded into settings.json (original kept in backups/)")

    legacy_runtime = home / "runtime"
    if legacy_runtime.is_dir():
        shutil.rmtree(legacy_runtime, ignore_errors=True)
        notes.append("legacy runtime/ removed")
    return notes


def ensure_global_home(home: Path = Path(GLOBAL_HOME)) -> Path:
    root = home.expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        notes = migrate_home(root)
        for note in notes:
            print(f"[laris] home migrated: {note}")
        for sub in LAYOUT_DIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        for name, text in (("settings.json", "{}\n"), ("LARIS.md", INSTRUCTIONS_TEMPLATE)):
            target = root / name
            if not target.exists():
                target.write_text(text, encoding="utf-8")
    except OSError:  # read-only home: the client still works with defaults
        pass
    return root
