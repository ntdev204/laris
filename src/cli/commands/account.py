"""`laris login|logout|whoami`: the API key that names the user's private conversation space."""

import argparse
import getpass
import os

from cli import credentials
from cli.common import load_runtime


class _Login:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        cfg = load_runtime().config.app
        key = credentials.validate(getpass.getpass("API key: "))
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
        return 0


COMMANDS = {"login": _Login(), "logout": _Logout(), "whoami": _Whoami()}
