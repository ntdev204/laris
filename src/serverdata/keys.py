"""API keys: creation, lookup, revocation and limits. Only SHA-256 digests are stored.

A key looks like `lk_<id>_<secret>`; the id selects the row and the whole string is verified against
its digest in constant time. The plaintext is shown once, when the key is created.
"""

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from serverdata.crypto import SecretBox, SecretBoxError
from serverdata.db import Database

PREFIX = "lk_"
DUMMY = hashlib.sha256(b"no such key").hexdigest()


class KeyError_(ValueError):
    """Invalid key request (unknown role or permission, bad limit, unknown id)."""


@dataclass(frozen=True)
class KeyRecord:
    id: str
    label: str
    role: str
    extra_permissions: FrozenSet[str]
    token_limit: Optional[int]
    tokens_used: int
    created_at: float
    expires_at: Optional[float]
    revoked_at: Optional[float]
    last_used_at: Optional[float]
    allowed_ips: Tuple[str, ...] = ()
    builtin: bool = False

    def status(self, now: float) -> str:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= now:
            return "expired"
        if self.token_limit is not None and self.tokens_used >= self.token_limit:
            return "exhausted"
        return "active"


def _legacy_digest(key: str) -> str:
    """Plain SHA-256, used before keys were stored encrypted; upgraded on first use."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _record(row: Any) -> KeyRecord:
    return KeyRecord(
        row["id"],
        row["label"],
        row["role"],
        frozenset(json.loads(row["extra_permissions"])),
        row["token_limit"],
        row["tokens_used"],
        row["created_at"],
        row["expires_at"],
        row["revoked_at"],
        row["last_used_at"],
        tuple(json.loads(row["allowed_ips"] or "[]")),
        bool(row["builtin"]),
    )


class KeyStore:
    def __init__(
        self,
        db: Database,
        roles: Dict[str, List[str]],
        privileged_roles: List[str],
        privileged_permissions: List[str],
        known_permissions: List[str],
        box: SecretBox,
    ) -> None:
        self.db = db
        self.box = box
        self.roles = {role: frozenset(perms) for role, perms in roles.items()}
        self.privileged_roles = set(privileged_roles)
        self.privileged_permissions = set(privileged_permissions)
        self.known = set(known_permissions)

    # -- creation --------------------------------------------------------------------------
    def create(
        self,
        label: str,
        role: str,
        token_limit: Optional[int],
        extra_permissions: Optional[List[str]] = None,
        expires_in_days: Optional[float] = None,
        now: Optional[float] = None,
        allowed_ips: Optional[List[str]] = None,
        builtin: bool = False,
    ) -> "tuple[KeyRecord, str]":
        if role not in self.roles:
            raise KeyError_(f"unknown role '{role}' (known: {', '.join(sorted(self.roles))})")
        extras = sorted(set(extra_permissions or []))
        unknown = [p for p in extras if p not in self.known]
        if unknown:
            raise KeyError_(f"unknown permission(s): {', '.join(unknown)}")
        if role not in self.privileged_roles and self.privileged_permissions & set(extras):
            raise KeyError_("reasoning and admin permissions are for privileged roles only")
        if token_limit is not None and token_limit < 0:
            raise KeyError_("token limit must be zero or more, or unlimited")
        stamp = time.time() if now is None else now
        key_id = secrets.token_hex(4)
        plaintext = f"{PREFIX}{key_id}_{secrets.token_urlsafe(24)}"
        expires = stamp + expires_in_days * 86400 if expires_in_days else None
        rules = self._rules(allowed_ips)
        self.db.connection().execute(
            "INSERT INTO keys (id, digest, secret_enc, label, role, extra_permissions,"
            " token_limit, created_at, expires_at, allowed_ips, builtin)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key_id, self.box.lookup_digest(plaintext), self.box.seal(plaintext), label[:80],
             role, json.dumps(extras), token_limit, stamp, expires, json.dumps(rules),
             int(builtin)),
        )  # fmt: skip
        return self.get(key_id), plaintext

    @staticmethod
    def _rules(rules: Optional[List[str]]) -> List[str]:
        import ipaddress

        out = []
        for rule in rules or []:
            if rule != "@server":
                try:
                    ipaddress.ip_network(rule, strict=False)
                except ValueError as exc:
                    raise KeyError_(f"not an IP address or CIDR: {rule}") from exc
            out.append(rule)
        return out

    # -- lookup ----------------------------------------------------------------------------
    def get(self, key_id: str) -> KeyRecord:
        row = self.db.connection().execute("SELECT * FROM keys WHERE id=?", (key_id,)).fetchone()
        if row is None:
            raise KeyError_(f"no key with id '{key_id}'")
        return _record(row)

    def list(self) -> List[KeyRecord]:
        rows = self.db.connection().execute("SELECT * FROM keys ORDER BY created_at").fetchall()
        return [_record(r) for r in rows]

    def verify(self, supplied: Optional[str], now: Optional[float] = None) -> Optional[KeyRecord]:
        """The record for a valid, active key; None for anything else (same work either way)."""
        text = (supplied or "").strip()
        key_id = text[len(PREFIX) :].split("_", 1)[0] if text.startswith(PREFIX) else ""
        row = None
        if key_id:
            row = (
                self.db.connection().execute("SELECT * FROM keys WHERE id=?", (key_id,)).fetchone()
            )
        known = row["digest"] if row else DUMMY
        keyed = hmac.compare_digest(self.box.lookup_digest(text), known)
        legacy = hmac.compare_digest(_legacy_digest(text), known)
        if row is None or not (keyed or legacy):
            return None
        if keyed and row["secret_enc"] is not None:
            blob = bytes(row["secret_enc"])
            if self.box.needs_upgrade(blob):  # sealed by the older cipher: reseal with AES-GCM
                self.db.connection().execute(
                    "UPDATE keys SET secret_enc=? WHERE id=?", (self.box.seal(text), key_id)
                )
        if legacy and not keyed:  # an older key: store it encrypted from now on
            self.db.connection().execute(
                "UPDATE keys SET digest=?, secret_enc=? WHERE id=?",
                (self.box.lookup_digest(text), self.box.seal(text), key_id),
            )
        record = _record(row)
        stamp = time.time() if now is None else now
        if record.revoked_at is not None or (record.expires_at and record.expires_at <= stamp):
            return None
        return record

    def reveal(self, key_id: str) -> str:
        """The key itself, decrypted. Only the operator's `keys reveal` calls this."""
        row = (
            self.db.connection()
            .execute("SELECT secret_enc FROM keys WHERE id=?", (key_id,))
            .fetchone()
        )
        if row is None:
            raise KeyError_(f"no key with id '{key_id}'")
        if row["secret_enc"] is None:
            raise KeyError_("this key predates encrypted storage and has not been used since")
        try:
            return self.box.open(bytes(row["secret_enc"]))
        except SecretBoxError as exc:
            raise KeyError_(str(exc)) from exc

    def set_allowed_ips(self, key_id: str, rules: List[str]) -> KeyRecord:
        self.get(key_id)
        self.db.connection().execute(
            "UPDATE keys SET allowed_ips=? WHERE id=?", (json.dumps(self._rules(rules)), key_id)
        )
        return self.get(key_id)

    def default_key(self) -> Optional[KeyRecord]:
        row = (
            self.db.connection()
            .execute("SELECT * FROM keys WHERE builtin=1 ORDER BY created_at LIMIT 1")
            .fetchone()
        )
        return _record(row) if row else None

    def effective_permissions(self, record: KeyRecord) -> FrozenSet[str]:
        return self.roles.get(record.role, frozenset()) | record.extra_permissions

    # -- changes ---------------------------------------------------------------------------
    def revoke(self, key_id: str, now: Optional[float] = None) -> KeyRecord:
        self.get(key_id)
        stamp = time.time() if now is None else now
        self.db.connection().execute(
            "UPDATE keys SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (stamp, key_id)
        )
        return self.get(key_id)

    def set_limit(self, key_id: str, token_limit: Optional[int], add: bool = False) -> KeyRecord:
        record = self.get(key_id)
        if token_limit is not None and token_limit < 0:
            raise KeyError_("token limit must be zero or more, or unlimited")
        if add:
            if token_limit is None or record.token_limit is None:
                raise KeyError_("--add needs a numeric amount and a key that has a limit")
            token_limit += record.token_limit
        self.db.connection().execute(
            "UPDATE keys SET token_limit=? WHERE id=?", (token_limit, key_id)
        )
        return self.get(key_id)
