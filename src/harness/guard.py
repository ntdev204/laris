"""Confidentiality and untrusted-content guards.

- `SecretRedactor` hides credentials: environment secrets (by name marker and explicit list),
  known token shapes, and internal absolute paths.
- `LeakDetector` recognises internal text (system prompt, policy) in output by hashed word
  shingles and by a per-session canary token, without keeping the plaintext twice.
- `InjectionScanner` flags instruction-like text inside untrusted data.
- `StreamGuard` applies all of this to streamed model text with a small hold-back buffer.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Pattern, Set, Tuple

from config.runtime_schemas import SecurityConfig
from harness.strings import StringCatalogue

_WORD = re.compile(r"\w+", re.UNICODE)
MIN_SECRET_LENGTH = 8


def _hash(words: Tuple[str, ...]) -> int:
    return int.from_bytes(hashlib.blake2b(" ".join(words).encode(), digest_size=8).digest(), "big")


class SecretRedactor:
    def __init__(
        self,
        cfg: SecurityConfig,
        strings: StringCatalogue,
        project_root: Optional[Path] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        env = os.environ if environ is None else environ
        markers = [m.upper() for m in cfg.secret_env_markers]
        explicit = set(cfg.extra_secret_env)
        self._values = sorted(
            {
                value
                for name, value in env.items()
                if len(value) >= MIN_SECRET_LENGTH
                and (name in explicit or any(marker in name.upper() for marker in markers))
            },
            key=len,
            reverse=True,
        )
        self._patterns: List[Pattern[str]] = [re.compile(p) for p in cfg.secret_patterns]
        self._mask = strings.get("guard.secret_redacted")
        self._path_mask = strings.get("guard.path_redacted")
        self._redact_paths = cfg.redact_paths
        self._root = str(project_root.resolve()) if project_root else ""
        self._home = str(Path.home())

    def redact_secrets(self, text: str) -> Tuple[str, int]:
        """Hide credentials only (paths untouched): used on what the user types."""
        count = 0
        for value in self._values:
            if value in text:
                count += text.count(value)
                text = text.replace(value, self._mask)
        for pattern in self._patterns:
            text, n = pattern.subn(self._mask, text)
            count += n
        return text, count

    def redact(self, text: str) -> Tuple[str, int]:
        count = 0
        for value in self._values:
            if value in text:
                count += text.count(value)
                text = text.replace(value, self._mask)
        for pattern in self._patterns:
            text, n = pattern.subn(self._mask, text)
            count += n
        if self._redact_paths:
            text = self._relativise(text)
        return text, count

    def _relativise(self, text: str) -> str:
        """Absolute paths inside the project become relative; other home paths become `~`."""
        if self._root and self._root in text:
            text = text.replace(self._root + "/", "").replace(self._root, ".")
        if self._home and self._home in text:
            text = text.replace(self._home, "~")
        return text


class LeakDetector:
    """Detects internal text in output. Built once per session from the confidential sources."""

    def __init__(self, cfg: SecurityConfig, sources: Iterable[str], canary: str = "") -> None:
        self.n = cfg.leak_shingle_words
        self.min_hits = cfg.leak_min_shingles
        self.enabled = cfg.leak_detection
        self.canary = canary if cfg.canary_enabled else ""
        self._shingles: Set[int] = set()
        for text in sources:
            words = tuple(w.lower() for w in _WORD.findall(text))
            for i in range(len(words) - self.n + 1):
                self._shingles.add(_hash(words[i : i + self.n]))

    def leaked(self, text: str) -> bool:
        if self.canary and self.canary in text:
            return True
        if not self.enabled or not self._shingles:
            return False
        words = tuple(w.lower() for w in _WORD.findall(text))
        hits = 0
        for i in range(len(words) - self.n + 1):
            if _hash(words[i : i + self.n]) in self._shingles:
                hits += 1
                if hits >= self.min_hits:
                    return True
        return False


class InjectionScanner:
    def __init__(self, cfg: SecurityConfig) -> None:
        self.enabled = cfg.injection_scan
        self._patterns = [re.compile(p, re.IGNORECASE) for p in cfg.injection_patterns]

    def flagged(self, text: str) -> bool:
        return self.enabled and any(p.search(text) for p in self._patterns)


class Guard:
    """Facade used by the loop: sanitise tool results, scan text, build stream guards."""

    def __init__(
        self,
        cfg: SecurityConfig,
        strings: StringCatalogue,
        redactor: SecretRedactor,
        leak: LeakDetector,
        injection: InjectionScanner,
    ) -> None:
        self.cfg = cfg
        self.strings = strings
        self.redactor = redactor
        self.leak = leak
        self.injection = injection
        self.hits: Dict[str, int] = {}

    def _count(self, kind: str, n: int = 1) -> None:
        if n:
            self.hits[kind] = self.hits.get(kind, 0) + n

    def clean_text(self, text: str) -> str:
        """Final-text check: blocked on leak, otherwise secrets and internal paths hidden."""
        if self.leak.leaked(text):
            self._count("leak")
            return self.strings.get("guard.leak_blocked")
        text, n = self.redactor.redact(text)
        self._count("secret", n)
        return text

    def tool_result(self, result: Any, untrusted: bool) -> Any:
        """Redact every string; mark untrusted data and flag instruction-like content."""
        flagged = False

        def walk(value: Any) -> Any:
            nonlocal flagged
            if isinstance(value, str):
                if untrusted and self.injection.flagged(value):
                    flagged = True
                cleaned, n = self.redactor.redact(value)
                self._count("secret", n)
                return cleaned
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            if isinstance(value, list):
                return [walk(v) for v in value]
            return value

        cleaned = walk(result)
        if isinstance(cleaned, dict) and untrusted:
            cleaned["_trust"] = "untrusted"
            if flagged:
                self._count("injection")
                cleaned["_warning"] = self.strings.get("guard.injection_notice")
        return cleaned

    def stream(self) -> "StreamGuard":
        return StreamGuard(self)


class StreamGuard:
    """Sanitises streamed text. Output is delayed by `stream_holdback_chars` so a secret or a
    leaked passage cannot be emitted before the guard has seen all of it."""

    def __init__(self, guard: Guard) -> None:
        self.guard = guard
        self.holdback = guard.cfg.stream_holdback_chars
        self._buffer = ""
        self._context = ""
        self.blocked = False

    def feed(self, delta: str) -> List[str]:
        if self.blocked:
            return []
        self._buffer += delta
        out: List[str] = []
        while len(self._buffer) > self.holdback:
            cut = len(self._buffer) - self.holdback
            space = self._buffer.rfind(" ", 0, cut)
            cut = space + 1 if space > 0 else cut
            piece, self._buffer = self._buffer[:cut], self._buffer[cut:]
            out += self._emit(piece)
        return out

    def finish(self) -> List[str]:
        if self.blocked or not self._buffer:
            return []
        piece, self._buffer = self._buffer, ""
        return self._emit(piece)

    def _emit(self, piece: str) -> List[str]:
        window = self._context + piece
        if self.guard.leak.leaked(window):
            self.blocked = True
            self.guard._count("leak")
            return [self.guard.strings.get("guard.leak_blocked")]
        self._context = window[-400:]
        cleaned, n = self.guard.redactor.redact(piece)
        self.guard._count("secret", n)
        return [cleaned] if cleaned else []
