"""`laris-server db migrate`: bring the server database up to the current schema.

With `serving.database_engine: postgres` this applies the numbered SQL migrations of
`laris.server.storage` (the DSN is read from the environment variable `serving.database_url_env`);
with SQLite the file is migrated when it is opened. Safe to run again and from several containers
at once.
"""

import argparse
from pathlib import Path

from laris.shared.config.loader import load_runtime_config


class _Migrate:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        from laris.server.serverdata.service import open_database
        from laris.server.storage import StorageError, migration_files

        root = Path.cwd()
        serving = load_runtime_config(root).serving
        try:
            db = open_database(serving, root)
        except StorageError as exc:
            print(f"database: {exc}")
            return 2
        if serving.database_engine == "postgres":
            rows = db.session().execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            print(f"PostgreSQL schema at version {rows['v']} of {len(migration_files())}")
            db.close()
        else:
            print(f"SQLite database ready at {db.path}")
        return 0


class _ImportSqlite:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("path", help="The old laris-server.db (SQLite) file")

    def run(self, args: argparse.Namespace) -> int:
        from laris.server.serverdata.service import open_database
        from laris.server.storage import StorageError
        from laris.server.storage.importer import ImportError_, import_sqlite

        root = Path.cwd()
        serving = load_runtime_config(root).serving
        if serving.database_engine != "postgres":
            print("[ERROR] set serving.database_engine: postgres (and the DSN variable) first")
            return 2
        try:
            db = open_database(serving, root)
            added = import_sqlite(db, Path(args.path))
        except (StorageError, ImportError_) as exc:
            print(f"[ERROR] {exc}")
            return 2
        db.close()
        print(
            f"imported {added['keys']} key(s), {added['usage']} usage row(s), "
            f"{added['traces']} trace(s); rows already present were left alone"
        )
        return 0


COMMANDS = {"migrate": _Migrate(), "import-sqlite": _ImportSqlite()}
