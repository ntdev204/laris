"""What the model server needs from the outside, as plain types and protocols.

The server itself keeps no state. Who may call (keys, roles, permissions), how many tokens were used
and where the model's reasoning goes are provided by adapters (`serverdata`), so this package stays
free of storage code.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Optional, Protocol, Tuple

# permissions a route can require
CHAT, EMBED, MODELS, WORKFLOWS, HELP, ACCOUNT = (
    "chat",
    "embed",
    "models",
    "workflows",
    "help",
    "account",
)


@dataclass(frozen=True)
class Principal:
    """The caller behind an accepted key."""

    key_id: str
    role: str
    permissions: FrozenSet[str] = field(default_factory=frozenset)
    token_limit: Optional[int] = None  # None = unlimited
    tokens_used: int = 0
    allowed_ips: Tuple[str, ...] = ()  # CIDRs or "@server"; empty = any address

    def can(self, permission: str) -> bool:
        return permission in self.permissions


class QuotaExceeded(Exception):
    """The key has no tokens left for this request."""


class Authenticator(Protocol):
    def authenticate(
        self, supplied: Optional[str], client_ip: Optional[str] = None
    ) -> Optional[Principal]: ...


class Reservation(Protocol):
    """Tokens set aside for one request: end it with `settle` (real use) or `release`."""

    def settle(self, usage: Dict[str, Any]) -> None: ...

    def release(self) -> None: ...


class UsageMeter(Protocol):
    def reserve(self, principal: Principal, estimated_tokens: int) -> Reservation:
        """Set tokens aside atomically; raise QuotaExceeded when the key cannot cover them."""

    def check(self, principal: Principal, estimated_tokens: int) -> None:
        """Raise QuotaExceeded when the key cannot cover the request."""

    def record(self, principal: Principal, usage: Dict[str, Any]) -> None: ...

    def account(self, principal: Principal) -> Dict[str, Any]: ...


class TraceSink(Protocol):
    """Receives the model's private reasoning. Nothing sent here is ever returned to a client."""

    def record(self, principal: Principal, trace: Dict[str, Any]) -> None: ...
