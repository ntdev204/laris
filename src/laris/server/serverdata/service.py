"""One object that opens the server database and exposes the ports the model server uses."""

import hashlib
import os
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Set

import laris.server.serverdata.netcheck as netcheck
from laris.server.serverdata.cache import TTLCache
from laris.server.serverdata.crypto import SecretBox, load_master
from laris.server.serverdata.db import Database
from laris.server.serverdata.keys import KeyStore
from laris.server.serverdata.traces import TraceStore
from laris.server.serverdata.usage import UsageStore
from laris.server.serving.auth import KeyRing
from laris.server.serving.ports import Principal
from laris.shared.config.runtime_schemas import ServingConfig


class DatabaseAuthenticator:
    """Keys from the database (new keys work at once, revocations within the cache TTL), plus
    optional fixed keys for testing."""

    def __init__(
        self,
        keys: KeyStore,
        cache: TTLCache,
        static: Optional[KeyRing] = None,
        own: Optional[Callable[[], Set[netcheck.Address]]] = None,
    ) -> None:
        self.keys, self.cache, self.static = keys, cache, static
        self.own = own or (lambda: set())

    def authenticate(
        self, supplied: Optional[str], client_ip: Optional[str] = None
    ) -> Optional[Principal]:
        text = (supplied or "").strip()
        if not text:
            return None
        token = hashlib.sha256(text.encode("utf-8")).hexdigest()
        principal = self.cache.get(token)
        if not isinstance(principal, Principal):
            record = self.keys.verify(text)
            principal = None
            if record is not None:
                principal = Principal(
                    record.id,
                    record.role,
                    self.keys.effective_permissions(record),
                    record.token_limit,
                    record.tokens_used,
                    record.allowed_ips,
                )
                self.cache.put(token, principal)
        if principal is not None:
            # the address rule is checked on every request, never cached; a key used from an
            # address it is not allowed from looks exactly like an unknown key
            if not netcheck.allowed(client_ip, principal.allowed_ips, self.own):
                return None
            return principal
        if self.static is not None and self.static.check(text):
            return Principal("static", "user", self.keys.roles.get("user", frozenset()))
        return None


def database_path(cfg: ServingConfig, root: Path) -> Path:
    folder = Path(cfg.data_dir)
    return (folder if folder.is_absolute() else root / folder) / "laris-server.db"


def open_database(
    cfg: ServingConfig, root: Path, environ: Optional[Mapping[str, str]] = None
) -> Any:
    """SQLite (one file) or PostgreSQL (`serving.database_engine`, DSN in the environment)."""
    if cfg.database_engine == "postgres":
        from laris.server.storage import PgDatabase, StorageError

        dsn = (environ if environ is not None else os.environ).get(cfg.database_url_env, "")
        if not dsn and cfg.database_url_file:
            try:
                dsn = Path(cfg.database_url_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise StorageError(f"cannot read {cfg.database_url_file}: {exc.strerror}") from exc
        if not dsn:
            raise StorageError(
                f"set {cfg.database_url_env} (or serving.database_url_file) to the PostgreSQL "
                "connection string"
            )
        return PgDatabase(
            dsn,
            min_size=cfg.database_pool_min,
            max_size=cfg.database_pool_max,
            timeout_s=cfg.database_timeout_s,
        )
    return Database(database_path(cfg, root))


class ServerData:
    def __init__(
        self,
        cfg: ServingConfig,
        root: Path,
        redact: Callable[[str], str] = lambda t: t,
        static: Optional[KeyRing] = None,
        environ: Optional[Mapping[str, str]] = None,
        extra_ips: Optional[list] = None,
    ) -> None:
        self.db: Any = open_database(cfg, root, environ)
        self.cfg = cfg
        self.box = SecretBox(load_master(cfg.master_env, cfg.master_file, environ))
        extras = [*cfg.server_ips, *(extra_ips or [])]
        self._own = TTLCache(60.0, 1)  # the machine's addresses, refreshed every minute
        known = sorted({p for perms in cfg.roles.values() for p in perms} | set(cfg.extra_known))
        self.keys = KeyStore(
            self.db, cfg.roles, cfg.privileged_roles, cfg.privileged_permissions, known, self.box
        )
        self.cache = TTLCache(cfg.cache_ttl_s, cfg.cache_max_entries)
        self.known_permissions = known

        def own() -> Set[netcheck.Address]:
            cached = self._own.get("own")
            if cached is None:
                cached = netcheck.own_addresses(extras)
                self._own.put("own", cached)
            return cached  # type: ignore[no-any-return]

        self.own = own
        self.auth = DatabaseAuthenticator(self.keys, self.cache, static, own)
        self.usage = UsageStore(self.db)
        self.traces = TraceStore(self.db, redact)

    def ensure_default_key(self) -> "Optional[str]":
        """On first start create the built-in key: every permission, no token limit, usable only
        from this machine. Returns its plaintext when it was just created, else None."""
        if self.keys.default_key() is not None:
            return None
        _, plaintext = self.keys.create(
            self.cfg.default_key_label,
            "admin",
            None,
            self.known_permissions,
            allowed_ips=[netcheck.SERVER],
            builtin=True,
        )
        return plaintext

    def deliver_default_key(self, plaintext: str) -> str:
        """Write the new default key to `serving.first_admin_file` (mode 0600, owner only) and
        return the path ("" when no file is configured). The key is never printed or logged."""
        import os
        from pathlib import Path

        if not self.cfg.first_admin_file:
            return ""
        path = Path(self.cfg.first_admin_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(plaintext + "\n")
        return str(path)

    # -- operator views (duck-typed by the model server's admin routes) ----------------------
    def usage_summary(self) -> Any:
        return self.usage.summary()

    def reasoning_list(self, limit: int) -> Any:
        return self.traces.list(None, limit)

    def reasoning_get(self, trace_id: int) -> Any:
        return self.traces.get(trace_id)

    def stats(self) -> Dict[str, Any]:
        return {"cache_hits": self.cache.hits, "cache_misses": self.cache.misses}
