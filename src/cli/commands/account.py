"""`laris login|logout|whoami`: the API key that names the user's private conversation space."""

import argparse
import getpass
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from cli import credentials
from cli.common import load_runtime
from laris.client.engine.commands import PROJECT_TEMPLATE
from laris.shared.config import settings
from laris.shared.harness import trust
from laris.shared.harness.prefs import UserPrefs

GLOBAL_DIR = Path("~/.laris")


def _set_server(url: str) -> Path:
    """Record the model server in the user's global `~/.laris/settings.json` (`base_url`)."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("server address must start with http:// or https://")
    path = GLOBAL_DIR.expanduser() / "settings.json"
    UserPrefs(path).update({"base_url": url.rstrip("/")})  # validated, written as server.url
    return path


def _show_account(key: str) -> None:
    """Role and token balance, when a server is configured and reachable."""
    from laris.client.agent.provider import ProviderError
    from laris.shared.harness.remote import ServerClient

    api = load_runtime().config.model_api
    if not api.base_url:
        return
    try:
        info = ServerClient(api.base_url, key).get("/laris/account")
    except ProviderError:
        return
    left = info.get("tokens_left")
    print(f"Vai trò: {info.get('role')}")
    print("Hạn mức token: " + ("không giới hạn" if left is None else f"còn {left}"))


def _ensure_trust(url: str, expected: str, ca_file: str) -> int:
    """For an https server whose certificate is not trusted: show its fingerprint and, with the
    user's confirmation (or a matching --trust-fingerprint), pin it. 0 = fine, 2 = refused."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return 0
    host, port = parsed.hostname, parsed.port or 443
    if trust.is_trusted(host, port, ca_file):
        return 0
    try:
        pem = trust.fetch_certificate(host, port)
    except OSError:
        return 0
    found = trust.fingerprint_pem(pem)
    print(f"Máy chủ {host}:{port} dùng chứng chỉ mà máy bạn chưa tin cậy.")
    print(f"Dấu vân tay (SHA-256): {found}")
    if expected:
        if trust.normalise(expected) != found:
            print("Dấu vân tay KHÔNG khớp với giá trị bạn đưa ra. Không tin cậy; dừng lại.")
            return 2
    else:
        print("Hãy so sánh với dấu vân tay chủ máy chủ đã công bố (qua một kênh khác).")
        if not sys.stdin.isatty() or input("Tin cậy chứng chỉ này? [y/N] ").strip().lower() != "y":
            print(
                "Không tin cậy. Chạy lại với --trust-fingerprint SHA256:... hoặc dùng CA công khai."
            )
            return 2
    path = trust.save(pem, host, port)
    path_in_settings = GLOBAL_DIR.expanduser() / "settings.json"
    pinned = settings.set_path(
        settings.read_raw(path_in_settings),
        "server.caFingerprint",
        settings.fingerprint_of_file(path),
    )
    settings.write(path_in_settings, pinned)
    trust.install(str(path))
    print(f"Đã ghi nhớ chứng chỉ (chỉ cho máy chủ này) tại {path}")
    return 0


class _Login:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--server", help="Model server address, e.g. https://laris.example.com/v1"
        )
        parser.add_argument(
            "--trust-fingerprint",
            default="",
            help="SHA-256 fingerprint of the server certificate from its owner (private CA)",
        )

    def run(self, args: argparse.Namespace) -> int:
        if args.server:
            try:
                print(f"Đã ghi địa chỉ máy chủ vào {_set_server(args.server)}")
            except ValueError as exc:
                print(f"[ERROR] {exc}")
                return 2
        runtime = load_runtime()
        cfg = runtime.config.app
        url = runtime.config.model_api.base_url
        if not url:
            print(
                "[ERROR] no server address is set. Run `laris config set server.url ADDRESS` "
                "(or `laris login --server ADDRESS`), then `laris login` again."
            )
            return 2
        if _ensure_trust(url, args.trust_fingerprint, runtime.config.model_api.ca_file):
            return 2
        runtime = load_runtime()  # picks up the pinned certificate
        key = credentials.validate(getpass.getpass("API key: "))
        status = credentials.verify_with_server(runtime.config.model_api, key)
        if status == "rejected":
            print("Máy chủ từ chối API key này. Không lưu.")
            return 2
        if status == "unreachable":
            print("Cảnh báo: không kết nối được máy chủ để kiểm tra khóa; vẫn lưu.")
        path = credentials.save(cfg, key)
        print(f"Đã lưu khóa (chỉ chủ sở hữu đọc được) tại {path}.")
        print(f"Người dùng: {credentials.fingerprint(key)}")
        return 0


class _Logout:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        removed = credentials.forget(load_runtime().config.app)
        print("Đã xóa khóa đã lưu." if removed else "Không có khóa đã lưu.")
        return 0


class _Whoami:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        cfg = load_runtime().config.app
        key = os.environ.get(cfg.key_env) or credentials.load_saved(cfg)
        if not key:
            print("Chưa đăng nhập. Chạy `laris login`.")
            return 1
        print(f"Người dùng: {credentials.fingerprint(key)}")
        _show_account(key)
        return 0


class _Init:
    """Create this project's `.laris/` (the global one, `~/.laris`, is made by `laris login`)."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        root = Path.cwd() / ".laris"
        for sub in ("skills", "commands", "memory"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        note = root / "LARIS.md"
        if not note.exists():
            note.write_text(PROJECT_TEMPLATE, encoding="utf-8")
        print(
            f"Đã tạo {root} (LARIS.md, skills/, commands/, memory/). "
            f"Cấu hình chung của bạn: {GLOBAL_DIR}"
        )
        return 0


COMMANDS = {"login": _Login(), "logout": _Logout(), "whoami": _Whoami(), "init": _Init()}
