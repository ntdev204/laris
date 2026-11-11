"""First-run setup of the user's global folder `~/.laris` (never overwrites anything).

settings.json   like Claude Code: base_url (server), model, api_key (by `laris login`, mode 0600),
                api_key_env, personal notes, preferences saved from the chat (/model ...)
config.yaml     client configuration (the server address is in settings.json)
LARIS.md        personal instructions sent with every task
skills/         skills the user creates, available in every project
memory/         personal notes available in every project
"""

from pathlib import Path

GLOBAL_HOME = "~/.laris"
CONFIG_TEMPLATE = """\
# LARIS client configuration (global). ./.laris/config.yaml in a project wins over this.
# Never put an API key here: use `laris login`.
app:
  settings_file: ~/.laris/settings.json
"""
SETTINGS_TEMPLATE = "{}\n"  # `laris login --server URL` adds "base_url"; edit by hand if you like
INSTRUCTIONS_TEMPLATE = (
    "# Personal instructions for LARIS\n\n"
    "Notes that apply in every project (language, citation style, how much detail you want).\n"
    "They are sent to the assistant with every task. Do not put secrets here.\n"
)


def ensure_global_home(home: Path = Path(GLOBAL_HOME)) -> Path:
    root = home.expanduser()
    try:
        for sub in ("skills", "memory"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        for name, text in (
            ("settings.json", SETTINGS_TEMPLATE),
            ("config.yaml", CONFIG_TEMPLATE),
            ("LARIS.md", INSTRUCTIONS_TEMPLATE),
        ):
            target = root / name
            if not target.exists():
                target.write_text(text, encoding="utf-8")
                if name == "settings.json":
                    target.chmod(0o600)  # it can hold the API key
    except OSError:  # read-only home: the client still works with defaults
        pass
    return root
