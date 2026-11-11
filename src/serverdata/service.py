"""One object that opens the server database and exposes the ports the model server uses."""

import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Set

from config.runtime_schemas import ServingConfig
from serverdata import netcheck
from serverdata.cache import TTLCache
from serverdata.crypto import SecretBox, load_master
from serverdata.db import Database
from serverdata.keys import KeyStore
from serverdata.traces import TraceStore
from serverdata.usage import UsageStore
from serving.auth import KeyRing
from serving.ports import Principal


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
        self.db = Database(database_path(cfg, root))
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

    # -- operator views (duck-typed by the model server's admin routes) ----------------------
    def usage_summary(self) -> Any:
        return self.usage.summary()

    def reasoning_list(self, limit: int) -> Any:
        return self.traces.list(None, limit)

    def reasoning_get(self, trace_id: int) -> Any:
        return self.traces.get(trace_id)

    def stats(self) -> Dict[str, Any]:
        return {"cache_hits": self.cache.hits, "cache_misses": self.cache.misses}
