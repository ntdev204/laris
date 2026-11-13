"""The coding tools: `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash` (SR-C3, SR-C5).

They work on the project folder (and `permissions.additionalDirectories`), never outside it. Every
path is resolved first, so `..` and symlinks cannot leave the allowed folders; the path policy
(secrets, internal files) applies to reads and writes; `.git/` and the policy folder `.laris/` are
never written. Every `Write` and `Edit` saves the file's previous content to a checkpoint first, and
`/rewind` restores it. `Bash` runs in the sandbox environment with a timeout, in a working directory
inside the project; installs outside the sandbox are refused here too (the permission engine also
denies them: defence in depth). Output is untrusted and is redacted by the agent loop's guard.
"""

import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from laris.client.agent.tools import Sandbox, ToolExecutionError, ToolSpec, schema
from laris.client.proc import kill_tree, new_group_options
from laris.client.sandbox import SandboxManager, classify_install, command_env

NEVER_WRITTEN = (".git", ".laris")
SKIPPED_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".ruff_cache"}


class Checkpoints:
    """Previous contents of edited files, one folder per session, newest last."""

    def __init__(self, folder: Path, keep: int = 200) -> None:
        self.folder = Path(folder)
        self.keep = keep
        self.index = self.folder / "index.jsonl"

    def _entries(self) -> List[Dict[str, Any]]:
        try:
            lines = self.index.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
        return out

    def _write(self, entries: List[Dict[str, Any]]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.index.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        os.replace(temp, self.index)

    def record(self, path: Path, tool: str) -> int:
        """Save `path`'s current content (or the fact that it does not exist) before an edit."""
        entries = self._entries()
        seq = (entries[-1]["seq"] + 1) if entries else 1
        existed = path.is_file()
        self.folder.mkdir(parents=True, exist_ok=True)
        if existed:
            shutil.copyfile(path, self.folder / f"{seq}.blob")
        entries.append(
            {"seq": seq, "path": str(path), "existed": existed, "tool": tool, "time": time.time()}
        )
        for old in entries[: -self.keep]:
            (self.folder / f"{old['seq']}.blob").unlink(missing_ok=True)
        self._write(entries[-self.keep :])
        return seq

    def list(self) -> List[Dict[str, Any]]:
        return self._entries()

    def rewind(
        self, steps: Optional[int] = 1, allowed: Optional[Callable[[Path], bool]] = None
    ) -> List[Dict[str, Any]]:
        """Undo the last `steps` edits (all when None), newest first. A path the policy no longer
        allows is skipped and reported, never written."""
        entries = self._entries()
        count = len(entries) if steps is None else max(0, min(steps, len(entries)))
        results: List[Dict[str, Any]] = []
        for entry in reversed(entries[len(entries) - count :]):
            path = Path(entry["path"])
            blob = self.folder / f"{entry['seq']}.blob"
            if allowed is not None and not allowed(path):
                results.append({"path": str(path), "status": "skipped", "why": "not allowed"})
            elif entry["existed"] and blob.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name + ".laris-rewind")
                shutil.copyfile(blob, temp)
                os.replace(temp, path)
                results.append({"path": str(path), "status": "restored"})
            elif not entry["existed"]:
                path.unlink(missing_ok=True)
                results.append({"path": str(path), "status": "removed"})
            else:
                results.append(
                    {"path": str(path), "status": "skipped", "why": "checkpoint missing"}
                )
            blob.unlink(missing_ok=True)
        self._write(entries[: len(entries) - count])
        return results


@dataclass
class CodingContext:
    root: Path
    cfg: Any  # CodingConfig
    policy: Any  # PathPolicy
    redact: Callable[[str], str]
    checkpoints: Optional[Checkpoints] = None
    extra_roots: Sequence[Path] = ()
    sandbox: Optional[SandboxManager] = None
    env: Dict[str, str] = field(default_factory=dict)
    inherit_env: bool = False

    @property
    def roots(self) -> List[Path]:
        return [self.root.resolve(), *[Path(r).expanduser().resolve() for r in self.extra_roots]]

    def inside(self, path: Path) -> bool:
        return any(path == r or r in path.parents for r in self.roots)

    def display(self, path: Path) -> str:
        for base in self.roots:
            try:
                return path.relative_to(base).as_posix()
            except ValueError:
                continue
        return path.name

    def resolve(self, raw: str, write: bool = False) -> Path:
        path = Path(raw).expanduser()
        path = (path if path.is_absolute() else self.root / path).resolve()
        if not self.inside(path):
            raise ToolExecutionError("outside_project", "the path is outside the project folders")
        if self.policy is not None and self.policy.denied(path):
            raise ToolExecutionError("denied", "this file is internal or secret")
        if write:
            for base in self.roots:
                if base == path or base in path.parents:
                    parts = path.relative_to(base).parts
                    if parts and parts[0] in NEVER_WRITTEN or ".git" in parts:
                        raise ToolExecutionError("denied", "this folder is never written by tools")
        return path

    def editable(self, path: Path) -> bool:
        try:
            self.resolve(str(path), write=True)
        except ToolExecutionError:
            return False
        return True


def _text(path: Path, limit: int) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolExecutionError("unreadable", f"cannot read the file: {exc.strerror}") from exc
    if len(data) > limit:
        raise ToolExecutionError("too_large", f"the file is larger than {limit} bytes")
    if b"\x00" in data[:8192]:
        raise ToolExecutionError("binary", "this looks like a binary file")
    return data.decode("utf-8", errors="replace")


def _replace(text: str, args: Dict[str, Any]) -> Tuple[str, int]:
    old, new = args["old_string"], args["new_string"]
    if not old:
        raise ToolExecutionError("invalid_arguments", "old_string must not be empty")
    if old == new:
        raise ToolExecutionError("no_change", "old_string and new_string are the same")
    count = text.count(old)
    if count == 0:
        raise ToolExecutionError("not_found", "old_string was not found in the file")
    if count > 1 and not args.get("replace_all", False):
        raise ToolExecutionError(
            "not_unique",
            f"old_string appears {count} times; add context to make it unique or set replace_all",
            {"matches": count},
        )
    return text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1), count


def preview_change(ctx: CodingContext, tool: str, args: Dict[str, Any]) -> str:
    """The unified diff an approval dialog shows for `Write` or `Edit`; empty when it cannot be
    computed (the call itself then fails with its own error)."""
    if tool not in ("Write", "Edit") or not isinstance(args.get("path"), str):
        return ""
    try:
        path = ctx.resolve(args["path"], write=True)
        before = _text(path, ctx.cfg.edit_max_bytes) if path.is_file() else ""
        if tool == "Write":
            after = str(args.get("content", ""))
        else:
            after = _replace(before, args)[0]
    except (ToolExecutionError, KeyError, TypeError):
        return ""
    name = ctx.display(path)
    lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), f"a/{name}", f"b/{name}", lineterm=""
    )
    text = "\n".join(lines) or "(no change)"
    if not path.is_file():
        text = "new file\n" + text
    limit = ctx.cfg.diff_max_chars
    return text if len(text) <= limit else text[:limit] + "\n… (diff truncated)"


def build_coding_tools(ctx: CodingContext, sandbox: Sandbox) -> Tuple[ToolSpec, ...]:
    cfg = ctx.cfg

    def read(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_read(args["path"])
        if not path.is_file():
            raise ToolExecutionError("not_found", "no such file")
        lines = _text(path, cfg.edit_max_bytes * 5).splitlines()
        start = max(1, int(args.get("offset", 1)))
        count = min(int(args.get("limit", cfg.read_max_lines)), cfg.read_max_lines)
        chunk = lines[start - 1 : start - 1 + count]
        text = "\n".join(f"{start + i:>6}\t{line}" for i, line in enumerate(chunk))
        return {
            "path": ctx.display(path),
            "total_lines": len(lines),
            "start": start,
            "end": start + len(chunk) - 1,
            "text": text,
            "truncated": start - 1 + count < len(lines),
        }

    def write(args: Dict[str, Any]) -> Any:
        path = ctx.resolve(args["path"], write=True)
        if path.is_dir():
            raise ToolExecutionError("is_directory", "the path is a folder")
        content = ctx.redact(args["content"])  # never persist a credential
        if len(content.encode("utf-8")) > cfg.edit_max_bytes:
            raise ToolExecutionError("too_large", "the content is too large")
        created = not path.exists()
        if ctx.checkpoints is not None:
            ctx.checkpoints.record(path, "Write")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "path": ctx.display(path),
            "bytes": len(content.encode("utf-8")),
            "created": created,
        }

    def edit(args: Dict[str, Any]) -> Any:
        path = ctx.resolve(args["path"], write=True)
        if not path.is_file():
            raise ToolExecutionError("not_found", "no such file")
        args = {**args, "new_string": ctx.redact(args["new_string"])}
        new_text, count = _replace(_text(path, cfg.edit_max_bytes), args)
        if ctx.checkpoints is not None:
            ctx.checkpoints.record(path, "Edit")
        path.write_text(new_text, encoding="utf-8")
        return {"path": ctx.display(path), "replacements": count if args.get("replace_all") else 1}

    def _files(base: Path) -> Any:
        if base.is_file():
            yield base
            return
        for folder, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
            for name in sorted(names):
                found = Path(folder) / name
                try:  # a symlink planted in the folder may point out of it
                    resolved = found.resolve()
                except (OSError, RuntimeError):
                    continue
                if ctx.inside(resolved) and not (
                    ctx.policy is not None
                    and (ctx.policy.denied(found) or ctx.policy.denied(resolved))
                ):
                    yield found

    def glob(args: Dict[str, Any]) -> Any:
        base = ctx.resolve(args.get("path", "."))
        if not base.is_dir():
            raise ToolExecutionError("not_a_directory", "not a directory")
        pattern, found = args["pattern"], []
        try:
            candidates = base.glob(pattern)
        except (ValueError, NotImplementedError) as exc:
            raise ToolExecutionError("invalid_pattern", str(exc)) from exc
        for path in sorted(candidates):
            resolved = path.resolve()
            if (
                path.is_file()
                and ctx.inside(resolved)
                and not any(part in SKIPPED_DIRS for part in path.relative_to(base).parts)
                and not (ctx.policy is not None and ctx.policy.denied(resolved))
            ):
                found.append(ctx.display(resolved))
        limit = cfg.glob_max_results
        return {"files": found[:limit], "truncated": len(found) > limit}

    def grep(args: Dict[str, Any]) -> Any:
        try:
            regex = re.compile(args["pattern"], re.I if args.get("ignore_case") else 0)
        except re.error as exc:
            raise ToolExecutionError("invalid_pattern", f"bad regular expression: {exc}") from exc
        base = ctx.resolve(args.get("path", "."))
        wanted = args.get("glob")
        limit = min(int(args.get("max_results", cfg.grep_max_results)), cfg.grep_max_results)
        matches: List[Dict[str, Any]] = []
        for path in _files(base):
            shown = ctx.display(path.resolve())
            if (
                wanted
                and not fnmatch.fnmatch(shown, wanted)
                and not fnmatch.fnmatch(path.name, wanted)
            ):
                continue
            try:
                if path.stat().st_size > cfg.grep_max_file_bytes:
                    continue
                text = _text(path, cfg.grep_max_file_bytes)
            except (ToolExecutionError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append({"path": shown, "line": number, "text": line[:300]})
                    if len(matches) > limit:
                        return {"matches": matches[:limit], "truncated": True}
        return {"matches": matches, "truncated": False}

    def bash(args: Dict[str, Any]) -> Any:
        command = args["command"]
        if ctx.sandbox is not None:
            check = classify_install(command, ctx.sandbox.bin)
            if check.kind == "outside":
                raise ToolExecutionError("denied", f"built-in rule: {check.reason}")
        cwd = ctx.resolve(args["cwd"]) if args.get("cwd") else ctx.root.resolve()
        if not cwd.is_dir():
            raise ToolExecutionError("not_a_directory", "cwd is not a folder")
        limit = min(
            float(args.get("timeout_s", cfg.bash_default_timeout_s)), cfg.bash_max_timeout_s
        )
        note = ""
        if ctx.sandbox is not None:
            state = ctx.sandbox.ensure()
            env = command_env(ctx.sandbox, ctx.env, ctx.inherit_env)
            note = state.hint() if state.state != "ready" else ""
        else:
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(Path.home()),
                **ctx.env,
            }
        shell = shutil.which("bash") or "/bin/sh"
        proc = subprocess.Popen(
            [shell, "-c", command], cwd=cwd, env=env, text=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **new_group_options(),
        )  # fmt: skip
        timed_out = False
        try:
            output, _ = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(proc)
            output, _ = proc.communicate()
        cap = cfg.bash_output_max_chars
        clipped = len(output) > cap
        result: Dict[str, Any] = {
            "exit_code": None if timed_out else proc.returncode,
            "timed_out": timed_out,
            "output": output[:cap] + ("\n… (output truncated)" if clipped else ""),
            "cwd": ctx.display(cwd) or ".",
        }
        if note:
            result["sandbox"] = note
        return result

    path_arg = {"type": "string", "description": "Path relative to the project folder"}
    return (
        ToolSpec(
            "Read",
            "Read a text file with line numbers; offset (first line, 1-based) and limit (lines).",
            schema(
                {"path": path_arg, "offset": {"type": "integer", "minimum": 1},
                 "limit": {"type": "integer", "minimum": 1}},
                ["path"],
            ),
            read,
            untrusted=True,
        ),
        ToolSpec(
            "Write",
            "Create or overwrite a file with the given content (needs approval; the previous "
            "content is checkpointed).",
            schema({"path": path_arg, "content": {"type": "string"}}, ["path", "content"]),
            write,
            writes=True,
        ),
        ToolSpec(
            "Edit",
            "Replace one exact piece of text in a file. old_string must appear exactly once "
            "(add surrounding context) unless replace_all is true (needs approval).",
            schema(
                {"path": path_arg, "old_string": {"type": "string"},
                 "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
                ["path", "old_string", "new_string"],
            ),
            edit,
            writes=True,
        ),
        ToolSpec(
            "Glob",
            "List files matching a glob pattern such as `src/**/*.py`.",
            schema({"pattern": {"type": "string"}, "path": path_arg}, ["pattern"]),
            glob,
        ),
        ToolSpec(
            "Grep",
            "Search file contents with a regular expression; optional path, glob filter, "
            "ignore_case and max_results.",
            schema(
                {"pattern": {"type": "string"}, "path": path_arg, "glob": {"type": "string"},
                 "ignore_case": {"type": "boolean"},
                 "max_results": {"type": "integer", "minimum": 1}},
                ["pattern"],
            ),
            grep,
            untrusted=True,
        ),
        ToolSpec(
            "Bash",
            "Run a shell command in the sandbox environment (needs approval unless a rule allows "
            "it). timeout_s and cwd (inside the project) are optional. Installs go into the "
            "sandbox only.",
            schema(
                {"command": {"type": "string"}, "timeout_s": {"type": "integer", "minimum": 1},
                 "cwd": path_arg},
                ["command"],
            ),
            bash,
            writes=True,
            timeout_s=cfg.bash_max_timeout_s + 15.0,
            untrusted=True,
        ),
    )  # fmt: skip
