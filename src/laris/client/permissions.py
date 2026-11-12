"""Permission modes and rules (SR-C3).

Modes: `default` asks before anything that writes, `acceptEdits` lets file edits through and asks
for the rest, `plan` is read-only, `bypass` asks for nothing and exists only when the policy
(`agent.approval.allow_bypass`) allows it. Rules are `Tool` or `Tool(pattern)` strings in `allow`,
`ask` and `deny` lists. Order of decision, first match wins:

1. a built-in deny (installs outside the sandbox: settings cannot widen it) or a `deny` rule;
2. `plan` mode refuses everything that is not read-only;
3. an `ask` rule asks, even in `bypass`;
4. an `allow` rule (settings, the project's saved answers, the built-in rule for installs into the
   sandbox) allows;
5. the mode: `bypass` allows, `acceptEdits` allows edits, `default` asks for writes.

"Always allow" answers are kept in `~/.laris/projects/<slug>/state.json` or, for "everywhere", in
`permissions.allow` of `~/.laris/settings.json`.
"""

import fnmatch
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from laris.client.project_state import ProjectState
from laris.client.sandbox.installs import classify_install
from laris.shared.config import settings as settings_mod

MODES = ("default", "acceptEdits", "plan", "bypass")
EDIT_TOOLS = frozenset({"write_file", "edit_file"})
ALIASES = {
    "read": "read_file", "write": "write_file", "edit": "edit_file", "multiedit": "edit_file",
    "glob": "glob", "grep": "grep", "bash": "bash",
}  # fmt: skip
PATH_KEYS = ("path", "file_path")
_RULE = re.compile(r"^\s*([A-Za-z_*][\w*]*)\s*(?:\((.*)\))?\s*$", re.S)


@dataclass
class Decision:
    action: str  # allow | ask | deny
    reason: str = ""
    rule: str = ""  # the rule that decided, when one did


def canonical(tool: str) -> str:
    low = tool.strip().lower()
    return ALIASES.get(low, low)


def parse_rule(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """`Edit(src/**)` -> (`edit_file`, `src/**`); `Bash` -> (`bash`, None); junk -> None."""
    found = _RULE.match(text or "")
    if not found:
        return None
    pattern = found.group(2)
    return canonical(found.group(1)), (pattern.strip() if pattern is not None else None)


def _glob(pattern: str) -> "re.Pattern[str]":
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _subject(arguments: Dict[str, Any]) -> Tuple[str, str]:
    """(`command` | `path` | `text`, value) the rule pattern is matched against."""
    if isinstance(arguments.get("command"), str):
        return "command", arguments["command"].strip()
    for key in PATH_KEYS:
        if isinstance(arguments.get(key), str):
            return "path", arguments[key]
    for value in arguments.values():
        if isinstance(value, str):
            return "text", value
    return "text", ""


def pattern_matches(pattern: str, arguments: Dict[str, Any], root: Optional[Path] = None) -> bool:
    kind, value = _subject(arguments)
    if kind == "command":
        if pattern.endswith(":*"):  # a command prefix on a word boundary: `git status:*`
            prefix = pattern[:-2]
            return value == prefix or value.startswith(prefix + " ")
        return fnmatch.fnmatchcase(value, pattern)
    if kind == "path":
        # match the resolved path, never the spelling: `src/../secret.py` is not inside `src/`
        base = (root or Path.cwd()).resolve()
        try:
            resolved = (base / value).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        candidates = {resolved.as_posix()}
        try:
            candidates.add(resolved.relative_to(base).as_posix())
        except ValueError:
            pass
        wanted = pattern[2:] if pattern.startswith("./") else pattern
        regex = _glob(wanted)
        return any(regex.match(c) for c in candidates)
    return fnmatch.fnmatchcase(value, pattern)


def rule_matches(
    rule: str, tool: str, arguments: Dict[str, Any], root: Optional[Path] = None
) -> bool:
    parsed = parse_rule(rule)
    if parsed is None:
        return False
    name, pattern = parsed
    if name != "*" and name != canonical(tool):
        return False
    return pattern is None or pattern_matches(pattern, arguments, root)


def next_mode(mode: str, allow_bypass: bool = False) -> str:
    """Shift+Tab: default -> acceptEdits -> plan -> (bypass, when allowed) -> default."""
    order = [m for m in MODES if m != "bypass" or allow_bypass]
    return order[(order.index(mode) + 1) % len(order)] if mode in order else "default"


class PermissionEngine:
    def __init__(
        self,
        settings_file: Path,
        state: ProjectState,
        project_root: Path,
        sandbox_bin: Optional[Path] = None,
        allow_bypass: bool = False,
        always_ask: Tuple[str, ...] = (),
        mode: Optional[str] = None,
    ) -> None:
        self.settings_file = Path(settings_file)
        self.state = state
        self.project_root = Path(project_root)
        self.sandbox_bin = sandbox_bin
        self.allow_bypass = allow_bypass
        self.always_ask = frozenset(always_ask)
        self.session_allow: List[str] = []
        self._mode: Optional[str] = None  # None: follow `permissions.defaultMode` as saved now
        if mode:
            self.mode = mode

    # -- mode ------------------------------------------------------------------------------
    def configured_mode(self) -> str:
        try:
            mode = settings_mod.validate(settings_mod.read_raw(self.settings_file)).permissions
            return self._gate(mode.defaultMode)
        except settings_mod.SettingsError:
            return "default"

    def _gate(self, mode: str) -> str:
        return "default" if mode == "bypass" and not self.allow_bypass else mode

    @property
    def mode(self) -> str:
        return self._mode or self.configured_mode()

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in MODES:
            raise ValueError(f"unknown mode {value!r} (one of {', '.join(MODES)})")
        if value == "bypass" and not self.allow_bypass:
            raise ValueError("bypass mode is not allowed by this installation's policy")
        self._mode = value

    def cycle(self) -> str:
        self.mode = next_mode(self.mode, self.allow_bypass)
        return self.mode

    # -- rules -----------------------------------------------------------------------------
    def _settings_rules(self, kind: str) -> List[str]:
        try:
            perms = settings_mod.validate(settings_mod.read_raw(self.settings_file)).permissions
        except settings_mod.SettingsError:
            return []
        return list(getattr(perms, kind))

    def rules(self, kind: str) -> List[str]:
        rules = self._settings_rules(kind)
        extra = (self.state.read().get("permissions") or {}).get(kind, [])
        rules += [r for r in extra if isinstance(r, str)]
        if kind == "allow":
            rules += self.session_allow
        return rules

    def _first(self, kind: str, tool: str, arguments: Dict[str, Any]) -> Optional[str]:
        for rule in self.rules(kind):
            if rule_matches(rule, tool, arguments, self.project_root):
                return rule
        return None

    # -- the decision ----------------------------------------------------------------------
    def decide(self, tool: str, arguments: Dict[str, Any], writes: bool) -> Decision:
        name = canonical(tool)
        install = None
        if name == "bash" and isinstance(arguments.get("command"), str) and self.sandbox_bin:
            install = classify_install(arguments["command"], self.sandbox_bin)
            if install.kind == "outside":
                return Decision("deny", f"built-in rule: {install.reason}", "builtin:install")
        rule = self._first("deny", tool, arguments)
        if rule:
            return Decision("deny", f"denied by rule {rule}", rule)
        needs_care = writes or name in self.always_ask
        if self.mode == "plan" and needs_care:
            return Decision("deny", "plan mode is read-only")
        rule = self._first("ask", tool, arguments)
        if rule:
            return Decision("ask", f"rule {rule} asks", rule)
        rule = self._first("allow", tool, arguments)
        if rule:
            return Decision("allow", f"allowed by rule {rule}", rule)
        if install is not None and install.kind == "sandbox":
            return Decision("allow", "install into the sandbox", "builtin:sandbox-install")
        if not needs_care or self.mode == "bypass":
            return Decision("allow", f"{self.mode} mode")
        if self.mode == "acceptEdits" and name in EDIT_TOOLS:
            return Decision("allow", "acceptEdits mode")
        return Decision("ask", "needs your approval")

    # -- answers ---------------------------------------------------------------------------
    @staticmethod
    def suggest(tool: str, arguments: Dict[str, Any]) -> str:
        """The rule an "always allow" answer would save for this call."""
        name = canonical(tool)
        kind, value = _subject(arguments)
        if kind == "command" and value:
            try:
                words = shlex.split(value)
            except ValueError:
                words = value.split()
            head = (
                " ".join(words[:2]) if len(words) > 1 and not words[1].startswith("-") else words[0]
            )
            return f"{name}({head}:*)" if words else name
        if kind == "path" and value:
            return f"{name}({value})"
        return name

    def remember(self, rule: str, scope: str) -> None:
        """`session` (memory only), `project` (state.json) or `everywhere` (settings.json)."""
        if parse_rule(rule) is None:
            raise ValueError(f"not a rule: {rule!r}")
        if scope == "session":
            if rule not in self.session_allow:
                self.session_allow.append(rule)
        elif scope == "project":
            perms = dict(self.state.read().get("permissions") or {})
            allow = list(perms.get("allow", []))
            if rule not in allow:
                perms["allow"] = allow + [rule]
                self.state.update(permissions=perms)
        elif scope == "everywhere":
            data = settings_mod.read_raw(self.settings_file)
            allow = list((data.get("permissions") or {}).get("allow", []))
            if rule not in allow:
                settings_mod.write(
                    self.settings_file,
                    settings_mod.set_path(data, "permissions.allow", allow + [rule]),
                )
        else:
            raise ValueError(f"unknown scope {scope!r}")

    def describe(self) -> str:
        lines = [f"mode: {self.mode}" + ("" if self.allow_bypass else " (bypass not allowed)")]
        for kind in ("deny", "ask", "allow"):
            rules = self.rules(kind)
            lines.append(f"{kind}: " + (", ".join(rules) if rules else "(none)"))
        lines.append("built-in: installs outside the sandbox are denied")
        return "\n".join(lines)
