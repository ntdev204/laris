"""The slash-command registry (SR-C2), shared by the engine and the plain terminal loop.

A command is a name, a one-line summary and a handler `(context, arguments) -> Result`. The built-in
commands are registered here; custom commands are Markdown files in `~/.laris/commands/` and
`./.laris/commands/` whose body becomes the user's message, with `$ARGUMENTS` replaced by what
followed the command. A project's custom commands are used only after the user trusts the folder
(SR-C5); a built-in name is never shadowed by a custom command.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from laris.client.permissions import parse_rule
from laris.client.project_state import ProjectState
from laris.client.sandbox import SandboxManager, sandbox_command
from laris.shared.config import settings as settings_mod

PROJECT_TEMPLATE = (
    "# Project instructions for LARIS\n\n"
    "Notes that apply to this project only (field, terminology, citation style, folders to\n"
    "ignore). They are sent to the assistant with every task. Do not put secrets here.\n"
)

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass
class Result:
    """What a command did: text to show, an agent turn to run, a new current session, or exit."""

    text: str = ""
    turn: Optional[str] = None
    conversation: Optional[Dict[str, Any]] = None
    exit: bool = False
    error: bool = False


@dataclass
class Context:
    chat: Any
    conversation: Dict[str, Any]
    home: Path
    cwd: Path
    sandbox: Optional[SandboxManager] = None
    registry: Optional["Registry"] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def settings_file(self) -> Path:
        return Path(self.chat.prefs.path)

    @property
    def state(self) -> ProjectState:
        return ProjectState(self.home, self.chat.project_root)


Handler = Callable[[Context, str], Result]


@dataclass
class Command:
    name: str
    summary: str
    handler: Handler
    usage: str = ""
    source: str = "built-in"  # built-in | user | project | skill


class Registry:
    def __init__(self) -> None:
        self.commands: Dict[str, Command] = {}

    def register(self, command: Command) -> None:
        self.commands[command.name] = command

    def command(self, name: str, summary: str, usage: str = "") -> Callable[[Handler], Handler]:
        def wrap(handler: Handler) -> Handler:
            self.register(Command(name, summary, handler, usage))
            return handler

        return wrap

    def names(self) -> List[str]:
        return sorted(self.commands)

    def complete(self, prefix: str, context: Optional[Context] = None) -> List[Command]:
        """Commands whose name starts with `prefix` (custom commands and skills included)."""
        merged = dict(self.commands)
        if context is not None:
            for command in discover_custom(context).values():
                merged.setdefault(command.name, command)
            for command in skill_commands(context).values():
                merged.setdefault(command.name, command)
        return [merged[n] for n in sorted(merged) if n.startswith(prefix.lower().lstrip("/"))]

    def dispatch(self, line: str, context: Context) -> Result:
        name, _, rest = line.strip().lstrip("/").partition(" ")
        name, rest = name.lower(), rest.strip()
        context.registry = self
        found = self.commands.get(name)
        if found is None:
            found = discover_custom(context).get(name) or skill_commands(context).get(name)
        if found is None:
            return Result(f"unknown command /{name}; /help lists the commands", error=True)
        try:
            return found.handler(context, rest)
        except settings_mod.SettingsError as exc:
            return Result(str(exc), error=True)
        except Exception as exc:  # a command never ends the session
            return Result(f"/{name}: {type(exc).__name__}: {exc}", error=True)


# -- custom commands and skills ------------------------------------------------------------------
def _parse_markdown(path: Path) -> Optional[Dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta: Dict[str, str] = {}
    found = _FRONT.match(text)
    if found:
        for line in found.group(1).splitlines():
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("\"'")
        text = text[found.end() :]
    meta["body"] = text.strip()
    return meta


def expand(body: str, arguments: str) -> str:
    """`$ARGUMENTS` becomes the text after the command; without the marker it is appended."""
    if "$ARGUMENTS" in body:
        return body.replace("$ARGUMENTS", arguments)
    return f"{body}\n\n{arguments}".strip() if arguments else body


def _custom_from(folder: Path, source: str) -> Dict[str, Command]:
    found: Dict[str, Command] = {}
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.md")):
        name = path.stem.lower()
        meta = _parse_markdown(path)
        if meta is None or not _NAME.match(name) or not meta["body"]:
            continue
        summary = meta.get("description") or meta["body"].splitlines()[0][:80]
        body = meta["body"]

        def handler(context: Context, arguments: str, body: str = body) -> Result:
            return Result(turn=expand(body, arguments))

        found[name] = Command(name, summary, handler, meta.get("argument-hint", ""), source)
    return found


def discover_custom(context: Context) -> Dict[str, Command]:
    """User commands always; project commands only when the folder is trusted. Built-in names
    cannot be shadowed, and a project command may not replace a user command of the same name."""
    builtin = BUILTIN.commands
    found: Dict[str, Command] = {}
    user = _custom_from(Path(context.home).expanduser() / "commands", "user")
    for name, command in user.items():
        if name not in builtin:
            found[name] = command
    if context.state.trusted:
        project = _custom_from(Path(context.chat.project_root) / ".laris" / "commands", "project")
        for name, command in project.items():
            if name not in builtin and name not in found:
                found[name] = command
    return found


def untrusted_project_commands(context: Context) -> List[str]:
    if context.state.trusted:
        return []
    folder = Path(context.chat.project_root) / ".laris" / "commands"
    return sorted(p.stem for p in folder.glob("*.md")) if folder.is_dir() else []


def skill_commands(context: Context) -> Dict[str, Command]:
    library = context.chat.skills_for(context.chat.runtime)
    found: Dict[str, Command] = {}
    for name in library.names():
        if name in BUILTIN.commands:
            continue

        def handler(ctx: Context, arguments: str, name: str = name) -> Result:
            return Result(turn=f"/{name} {arguments}".strip())

        found[name] = Command(name, library.skills[name].summary(110), handler, source="skill")
    return found


# -- built-in commands ---------------------------------------------------------------------------
BUILTIN = Registry()
cmd = BUILTIN.command


@cmd("help", "list the commands")
def _help(ctx: Context, rest: str) -> Result:
    lines = []
    for command in ctx.registry.complete("", ctx) if ctx.registry else []:  # type: ignore[union-attr]
        usage = f" {command.usage}" if command.usage else ""
        tag = "" if command.source == "built-in" else f"  ({command.source})"
        lines.append(f"  /{command.name}{usage} — {command.summary}{tag}")
    hidden = untrusted_project_commands(ctx)
    if hidden:
        lines.append(
            f"  {len(hidden)} project command(s) are not used until you trust this folder: /trust"
        )
    return Result("\n".join(lines))


@cmd("how-to-use", "the prepared user guide")
def _how(ctx: Context, rest: str) -> Result:
    return Result(ctx.chat.how_to_use())


@cmd("clear", "start a new, empty session")
def _clear(ctx: Context, rest: str) -> Result:
    conversation = dict(ctx.chat.conversations.create())
    return Result(f"new session {conversation['id']}", conversation=conversation)


BUILTIN.register(Command("new", "start a new session", _clear, source="built-in"))


@cmd("sessions", "list saved sessions")
def _sessions(ctx: Context, rest: str) -> Result:
    rows = ctx.chat.conversations.list()[:15]
    return Result("\n".join(f"  {r['id']}  {r['messages']:>3} msgs  {r['title']}" for r in rows))


@cmd("resume", "resume a saved session", "ID")
def _resume(ctx: Context, rest: str) -> Result:
    rows = ctx.chat.conversations.list()
    matches = [r["id"] for r in rows if rest and str(r["id"]).startswith(rest)]
    if len(matches) != 1:
        return Result(f"no such session: {rest}" if rest else "usage: /resume ID", error=True)
    conversation = dict(ctx.chat.conversations.get(matches[0]))
    return Result(f"resumed {matches[0]}: {conversation['title']}", conversation=conversation)


@cmd("continue", "resume the most recent session")
def _continue(ctx: Context, rest: str) -> Result:
    rows = [r for r in ctx.chat.conversations.list() if r["id"] != ctx.conversation["id"]]
    if not rows:
        return Result("no earlier session", error=True)
    conversation = dict(ctx.chat.conversations.get(rows[0]["id"]))
    return Result(f"resumed {rows[0]['id']}: {conversation['title']}", conversation=conversation)


@cmd("compact", "shrink the context", "[note]")
def _compact(ctx: Context, rest: str) -> Result:
    events = [e for e in ctx.chat.compact(ctx.conversation["id"], rest) if e["type"] == "compact"]
    if not events:
        return Result("nothing to compact")
    text = "\n".join(
        f"compacted {e['before']} → {e['after']} tokens ({e['method']})" for e in events
    )
    return Result(text, conversation=dict(ctx.chat.conversations.get(ctx.conversation["id"])))


@cmd("model", "show or set the model server", "[URL [NAME]]")
def _model(ctx: Context, rest: str) -> Result:
    if rest:
        parts = rest.split()
        ctx.chat.update_settings(
            {"base_url": parts[0], **({"model": parts[1]} if len(parts) > 1 else {})}
        )
    return Result(ctx.chat.model_health()["detail"])


@cmd("status", "model, session and service status")
def _status(ctx: Context, rest: str) -> Result:
    health = ctx.chat.model_health()
    info = {
        "session": ctx.conversation["id"],
        "model": health["detail"],
        "project": str(ctx.chat.project_root),
        "trusted": ctx.state.trusted,
        "service": ctx.chat.service.status(),
    }
    return Result(json.dumps(info, indent=2, ensure_ascii=False, default=str))


@cmd("cost", "tokens used in this session")
def _cost(ctx: Context, rest: str) -> Result:
    usage = ctx.chat.usage(ctx.conversation["id"])
    return Result(f"≈ {usage['tokens']} tokens in the context of {usage['window']}")


@cmd("context", "context size and auto-compact setting")
def _context(ctx: Context, rest: str) -> Result:
    usage = ctx.chat.usage(ctx.conversation["id"])
    cfg = ctx.chat.settings()
    return Result(
        f"≈ {usage['tokens']}/{usage['window']} tokens; auto-compact "
        f"{'on' if cfg['auto_compact'] else 'off'} at {int(cfg['compact_threshold'] * 100)}%"
    )


@cmd("config", "show or edit ~/.laris/settings.json", "[get PATH | set PATH VALUE]")
def _config(ctx: Context, rest: str) -> Result:
    words = rest.split(None, 2)
    data = settings_mod.read_raw(ctx.settings_file)
    if not words or words[0] == "get":
        if len(words) < 2:
            return Result(json.dumps(data, indent=2, ensure_ascii=False))
        try:
            value = settings_mod.get_path(data, words[1])
        except KeyError:
            return Result(f"{words[1]} is not set", error=True)
        return Result(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    if words[0] == "set" and len(words) == 3:
        changed = settings_mod.set_path(data, words[1], settings_mod.parse_value(words[2]))
        settings_mod.write(ctx.settings_file, changed)
        return Result(f"{words[1]} = {json.dumps(settings_mod.get_path(changed, words[1]))}")
    return Result("usage: /config [get PATH | set PATH VALUE]", error=True)


@cmd(
    "permissions",
    "approval mode and rules",
    "[mode MODE|next | allow|ask|deny RULE [everywhere]]",
)
def _permissions(ctx: Context, rest: str) -> Result:
    engine = ctx.chat.permissions
    words = rest.split(None, 2)
    if not words:
        return Result(engine.describe())
    if words[0] == "mode" and len(words) >= 2:
        engine.cycle() if words[1] == "next" else setattr(engine, "mode", words[1])
        return Result(f"mode: {engine.mode}")
    if words[0] in ("allow", "ask", "deny") and len(words) >= 2:
        rule = rest.split(None, 1)[1].removesuffix(" everywhere").strip()
        if parse_rule(rule) is None:
            return Result(f"not a rule: {rule}", error=True)
        data = settings_mod.read_raw(ctx.settings_file)
        path = f"permissions.{words[0]}"
        try:
            current = list(settings_mod.get_path(data, path))
        except KeyError:
            current = []
        if rule not in current:
            data = settings_mod.set_path(data, path, current + [rule])
            settings_mod.write(ctx.settings_file, data)
        return Result(f"{words[0]}: {rule}")
    return Result("usage: /permissions [mode MODE|next | allow|ask|deny RULE]", error=True)


@cmd("memory", "list memory notes", "")
def _memory(ctx: Context, rest: str) -> Result:
    lines = []
    for label, folder in (
        ("user", Path(ctx.home).expanduser() / "memory"),
        ("project", Path(ctx.chat.project_root) / ".laris" / "memory"),
    ):
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            lines.append(f"  [{label}] {path.name}")
    return Result("\n".join(lines) or "no memory notes yet")


@cmd("init", "create this project's .laris folder")
def _init(ctx: Context, rest: str) -> Result:
    root = Path(ctx.chat.project_root) / ".laris"
    for sub in ("skills", "commands", "memory"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    note = root / "LARIS.md"
    created = not note.exists()
    if created:
        note.write_text(PROJECT_TEMPLATE, encoding="utf-8")
    return Result(
        f"{root} ready" + (" (LARIS.md created)" if created else " (nothing overwritten)")
    )


@cmd("trust", "trust this folder's custom commands and skills", "[off]")
def _trust(ctx: Context, rest: str) -> Result:
    ctx.state.trust(rest.strip().lower() != "off")
    return Result("folder trusted" if ctx.state.trusted else "folder no longer trusted")


@cmd("login", "show the signed-in account (sign in with `laris login`)")
def _login(ctx: Context, rest: str) -> Result:
    from laris.shared.harness import credentials

    cfg = ctx.chat.runtime.config.app
    key = credentials.load_saved(cfg)
    if not key:
        return Result("not signed in; run `laris login` in a terminal")
    return Result(f"signed in as {credentials.fingerprint(key)}")


@cmd("logout", "forget the saved API key")
def _logout(ctx: Context, rest: str) -> Result:
    from laris.shared.harness import credentials

    removed = credentials.forget(ctx.chat.runtime.config.app)
    return Result("saved key removed" if removed else "no saved key")


@cmd("doctor", "check settings, model, sandbox and trust")
def _doctor(ctx: Context, rest: str) -> Result:
    lines = []
    try:
        settings_mod.validate(settings_mod.read_raw(ctx.settings_file))
        lines.append("settings: ok")
    except settings_mod.SettingsError as exc:
        lines.append(f"settings: {exc}")
    health = ctx.chat.model_health()
    lines.append(f"model: {'ok' if health['ok'] else 'unavailable'} — {health['detail']}")
    lines.append("sandbox: " + (ctx.sandbox.check().state if ctx.sandbox else "not set up"))
    lines.append(f"folder trusted: {'yes' if ctx.state.trusted else 'no'}")
    return Result("\n".join(lines))


@cmd("vault", "vault size, or search its notes", "[words]")
def _vault(ctx: Context, rest: str) -> Result:
    from laris.shared.vault.index import VaultIndex
    from laris.shared.vault.search import NoteSearch

    cfg = ctx.chat.runtime.config.vault
    folder = Path(ctx.chat.project_root) / cfg.dir
    if not folder.is_dir():
        return Result("no vault yet; it is created by the first ingest or answer")
    index = VaultIndex.build(
        folder, cache_file=Path(ctx.chat.project_root) / cfg.cache_dir / "index.sqlite"
    )
    if not rest:
        return Result(
            f"vault {cfg.dir}/: {len(index.notes)} notes, {len(index.unresolved)} broken links"
        )
    return Result(
        "\n".join(f"  {h.score:6.2f}  {h.path}" for h in NoteSearch(index).search(rest, 8))
    )


@cmd("skills", "list skills")
def _skills(ctx: Context, rest: str) -> Result:
    library = ctx.chat.skills_for(ctx.chat.runtime)
    lines = [f"  /{n}: {library.skills[n].summary(110)}" for n in library.names()]
    lines += [f"  skill problem: {p}" for p in library.problems]
    return Result("\n".join(lines) or "no skills")


@cmd("workflows", "list workflows")
def _workflows(ctx: Context, rest: str) -> Result:
    items = ctx.chat.runtime.workflows().summary()
    return Result("\n".join(f"  /workflow {i['name']}: {i['description']}" for i in items))


@cmd("workflow", "run a workflow", "NAME <request>")
def _workflow(ctx: Context, rest: str) -> Result:
    return Result(turn=f"/workflow {rest}")


@cmd("hooks", "list the configured hooks")
def _hooks(ctx: Context, rest: str) -> Result:
    hooks = settings_mod.validate(settings_mod.read_raw(ctx.settings_file)).hooks
    lines = [
        f"  {event} [{matcher.matcher or '*'}] {hook.command}"
        for event, matchers in hooks.items()
        for matcher in matchers
        for hook in matcher.hooks
    ]
    return Result("\n".join(lines) or "no hooks configured")


@cmd("sandbox", "the sandbox's state; `reset` rebuilds it", "[reset]")
def _sandbox(ctx: Context, rest: str) -> Result:
    if ctx.sandbox is None:
        return Result("the sandbox is not set up in this session", error=True)
    return Result(sandbox_command(ctx.sandbox, rest))


@cmd("tools", "list the agent's tools")
def _tools(ctx: Context, rest: str) -> Result:
    return Result(
        "\n".join(
            f"  {s.name}{' (asks)' if s.writes else ''}: {s.description}"
            for s in ctx.chat.tool_specs()
        )
    )


@cmd("write", "auto-approve write tools", "on|off")
def _write(ctx: Context, rest: str) -> Result:
    ctx.chat.update_settings({"allow_write": rest == "on"})
    return Result("write tools auto-approved" if rest == "on" else "write tools ask permission")


@cmd("learn", "local fine-tune data collection", "on|off")
def _learn(ctx: Context, rest: str) -> Result:
    ctx.chat.update_settings({"learning_enabled": rest == "on"})
    return Result(f"local fine-tune data: {'on' if rest == 'on' else 'off'}")


@cmd("rate", "rate the last answer", "up|down")
def _rate(ctx: Context, rest: str) -> Result:
    try:
        ctx.chat.rate(str(ctx.extras.get("last_example", "")), rest)
    except (KeyError, ValueError):
        return Result("usage: /rate up|down after a saved answer", error=True)
    return Result(f"rating recorded: {rest}")


@cmd("exit", "leave laris")
def _exit(ctx: Context, rest: str) -> Result:
    return Result(exit=True)


BUILTIN.register(Command("quit", "leave laris", _exit))
