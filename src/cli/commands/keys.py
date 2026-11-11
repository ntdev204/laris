"""`laris-server keys|usage|reasoning`: manage API keys and read usage and the model's reasoning.

These run on the server machine and read the server database directly; there is no network path to
them. Keys are shown once, when created. The model's reasoning is for the operator only.
"""

import argparse
import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional

from config.loader import load_runtime_config
from serverdata import ServerData, tls


def _data() -> ServerData:
    root = Path.cwd()
    return ServerData(load_runtime_config(root).serving, root)


def _when(value: Optional[float]) -> str:
    if not value:
        return "-"
    return datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def _limit(text: str) -> Optional[int]:
    return None if text.lower() in ("unlimited", "none", "-") else int(text)


def _line(data: ServerData, record: Any) -> str:
    import time

    limit = "unlimited" if record.token_limit is None else str(record.token_limit)
    where = f"  from {','.join(record.allowed_ips)}" if record.allowed_ips else ""
    return (
        f"{record.id}  {record.status(time.time()):9}  {record.role:9} "
        f"{record.tokens_used}/{limit} tokens  expires {_when(record.expires_at)}  "
        f"{record.label}{where}"
    )


class _Create:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--label", required=True, help="Whose key this is")
        parser.add_argument("--role", default="user", help="user, readonly, auditor or admin")
        parser.add_argument(
            "--tokens", default="unlimited", help="Token quota: a number or `unlimited`"
        )
        parser.add_argument("--expires-days", type=float, default=None)
        parser.add_argument("--permission", action="append", default=[], help="Extra permission")
        parser.add_argument(
            "--allow-ip",
            action="append",
            default=[],
            help="Only these addresses may use the key: a CIDR, or @server for this machine",
        )

    def run(self, args: argparse.Namespace) -> int:
        from serverdata.keys import KeyError_

        data = _data()
        try:
            record, plaintext = data.keys.create(
                args.label,
                args.role,
                _limit(args.tokens),
                args.permission,
                args.expires_days,
                allowed_ips=args.allow_ip,
            )
        except (KeyError_, ValueError) as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(_line(data, record))
        print("permissions:", ", ".join(sorted(data.keys.effective_permissions(record))))
        print(f"\nAPI key (shown once, give it to the user): {plaintext}")
        print("The running server accepts it at once.")
        return 0


class _List:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        data = _data()
        records = data.keys.list()
        print("\n".join(_line(data, r) for r in records) or "no keys yet")
        return 0


class _Show:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("id")

    def run(self, args: argparse.Namespace) -> int:
        from serverdata.keys import KeyError_

        data = _data()
        try:
            record = data.keys.get(args.id)
        except KeyError_ as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(_line(data, record))
        print("permissions:", ", ".join(sorted(data.keys.effective_permissions(record))))
        print(f"created {_when(record.created_at)}  last used {_when(record.last_used_at)}")
        return 0


class _Revoke:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("id")

    def run(self, args: argparse.Namespace) -> int:
        from serverdata.keys import KeyError_

        data = _data()
        try:
            print(_line(data, data.keys.revoke(args.id)))
        except KeyError_ as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(f"The running server stops accepting it within {data.cfg.cache_ttl_s:g} s.")
        return 0


class _Limit:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("id")
        parser.add_argument("--tokens", required=True, help="New quota: a number or `unlimited`")
        parser.add_argument("--add", action="store_true", help="Add the number to the old quota")

    def run(self, args: argparse.Namespace) -> int:
        from serverdata.keys import KeyError_

        data = _data()
        try:
            print(_line(data, data.keys.set_limit(args.id, _limit(args.tokens), args.add)))
        except (KeyError_, ValueError) as exc:
            print(f"[ERROR] {exc}")
            return 2
        return 0


class _Reveal:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("id", help="Key id, or `default` for the built-in key")

    def run(self, args: argparse.Namespace) -> int:
        from serverdata.keys import KeyError_

        data = _data()
        try:
            key_id = args.id
            if key_id == "default":
                record = data.keys.default_key()
                if record is None:
                    print("[ERROR] the default key is created when the server first starts")
                    return 2
                key_id = record.id
            print(data.keys.reveal(key_id))
        except KeyError_ as exc:
            print(f"[ERROR] {exc}")
            return 2
        return 0


class _Ip:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("id")
        parser.add_argument("--allow", action="append", default=[], help="CIDR or @server")
        parser.add_argument("--clear", action="store_true", help="Allow any address again")

    def run(self, args: argparse.Namespace) -> int:
        from serverdata.keys import KeyError_

        data = _data()
        try:
            rules = [] if args.clear else args.allow
            print(_line(data, data.keys.set_allowed_ips(args.id, rules)))
        except KeyError_ as exc:
            print(f"[ERROR] {exc}")
            return 2
        return 0


class _Roles:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        data = _data()
        for role, perms in sorted(data.keys.roles.items()):
            print(f"{role:9} {', '.join(sorted(perms))}")
        return 0


class _Usage:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--days", type=float, default=0, help="Only the last N days")

    def run(self, args: argparse.Namespace) -> int:
        import time

        data = _data()
        since = time.time() - args.days * 86400 if args.days else 0.0
        rows = data.usage.summary(since)
        for row in rows:
            print(
                f"{row['key_id']:10} {row['requests']:6} requests  "
                f"{row['prompt'] or 0} prompt + {row['completion'] or 0} completion tokens"
            )
        if not rows:
            print("no usage yet")
        return 0


class _ReasoningList:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--key", default=None, help="Only this key id")
        parser.add_argument("--limit", type=int, default=20)

    def run(self, args: argparse.Namespace) -> int:
        for row in _data().traces.list(args.key, args.limit):
            print(
                f"#{row['id']:<6} {_when(row['ts'])}  key {row['key_id']}  "
                f"{row['reasoning_chars']:6} chars  {row['task'][:60]}"
            )
        return 0


class _ReasoningShow:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("id", type=int)

    def run(self, args: argparse.Namespace) -> int:
        row = _data().traces.get(args.id)
        if row is None:
            print("[ERROR] no such trace")
            return 2
        head = f"trace #{row['id']}  key {row['key_id']}  session {row['session_id']}"
        print(f"{head}  {_when(row['ts'])}")
        print(f"task: {row['task']}")
        print(f"brain notes: {', '.join(json.loads(row['brain'])) or '-'}")
        print(f"tool calls: {row['tool_calls']}")
        print("--- reasoning ---")
        print(row["reasoning"] or "(the model gave no reasoning)")
        return 0


class _ReasoningPurge:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--days", type=float, default=None, help="Delete older than N days")

    def run(self, args: argparse.Namespace) -> int:
        data = _data()
        days = args.days if args.days is not None else data.cfg.trace_retention_days
        print(f"deleted {data.traces.purge(days)} trace(s) older than {days:g} days")
        return 0


class _TlsInit:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--host", action="append", default=[], help="Name or IP clients use (repeatable)"
        )
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--force", action="store_true", help="Replace an existing certificate")

    def run(self, args: argparse.Namespace) -> int:
        cfg = load_runtime_config(Path.cwd()).serving
        try:
            cert, key = tls.create_self_signed(cfg.tls_dir, args.host, args.days, args.force)
        except FileExistsError as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(f"certificate {cert}\nprivate key {key} (mode 0600)")
        print("`laris-server model serve` now serves HTTPS from this folder.")
        print(f"Fingerprint (give it to users): {tls.fingerprint(str(cert))}")
        print("Users run: laris login --server <address> --trust-fingerprint <value>")
        return 0


TLS_COMMANDS: Dict[str, Any] = {"init": _TlsInit()}
KEYS_COMMANDS: Dict[str, Any] = {
    "create": _Create(),
    "list": _List(),
    "show": _Show(),
    "revoke": _Revoke(),
    "limit": _Limit(),
    "roles": _Roles(),
    "reveal": _Reveal(),
    "ip": _Ip(),
}
USAGE_COMMANDS: Dict[str, Any] = {"summary": _Usage()}
REASONING_COMMANDS: Dict[str, Any] = {
    "list": _ReasoningList(),
    "show": _ReasoningShow(),
    "purge": _ReasoningPurge(),
}
