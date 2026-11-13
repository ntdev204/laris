"""The part of an engine session before `ready`: making sure there is a server that can be
verified and an API key it accepts (ADR-019 D25).

When something is missing the engine sends `login_required` and waits for `login`; it asks again
until the session can start, or the front end leaves. A server address and a certificate
fingerprint packaged with the program (D24) need no question at all. The key is checked against
the server before it is saved and never appears in an event.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, MutableMapping, Optional, TextIO

from laris.protocol import engine as e1
from laris.shared.config import packaged, settings
from laris.shared.harness import credentials, trust
from laris.shared.harness.prefs import UserPrefs


class LoginGate:
    def __init__(
        self,
        reader: TextIO,
        writer: TextIO,
        load_runtime: Callable[[], Any],
        home: Optional[Path] = None,
        environ: Optional[MutableMapping[str, str]] = None,
    ) -> None:
        self.reader, self.writer = reader, writer
        self.load_runtime = load_runtime
        self.home = Path(home or Path("~/.laris").expanduser())
        self.environ = os.environ if environ is None else environ
        self._accepted = ""  # the fingerprint a person confirmed
        self._typed = ""  # a key typed in this session, not yet checked

    # -- wire ----------------------------------------------------------------------------------
    def _emit(self, message: Any) -> None:
        self.writer.write(json.dumps(message.model_dump(mode="json"), ensure_ascii=False) + "\n")
        self.writer.flush()

    def _ask(self, reason: Any, server: str, fingerprint: str = "", message: str = "") -> bool:
        """Send `login_required` and apply the answer. False when the front end left."""
        self._emit(
            e1.LoginRequired(reason=reason, server=server, fingerprint=fingerprint, message=message)
        )
        while True:
            line = self.reader.readline()
            if not line:
                return False  # end of input: the front end is gone
            if not line.strip():
                continue
            try:
                command = e1.parse_command(json.loads(line))
            except (ValueError, e1.ProtocolError) as exc:
                self._emit(e1.ErrorEvent(code="bad_command", message=str(exc)))
                continue
            if isinstance(command, e1.Shutdown):
                return False
            if not isinstance(command, e1.Login):
                self._emit(
                    e1.ErrorEvent(code="login_required", message="answer `login_required` first")
                )
                continue
            if command.server:
                try:
                    self._set_server(command.server)
                except (ValueError, OSError) as exc:
                    self._emit(e1.LoginRequired(reason="no_server", server="", message=str(exc)))
                    continue
            if command.trust and fingerprint and reason == "untrusted_certificate":
                self._accepted = fingerprint
            if command.key:
                self._typed = command.key
            return True

    def _set_server(self, url: str) -> None:
        # people type a host name: `laris.example.com` becomes `https://laris.example.com/v1`
        UserPrefs(self.home / "settings.json").update({"base_url": settings.server_address(url)})

    # -- the decision --------------------------------------------------------------------------
    def run(self) -> bool:
        """True when the session can start; False when the front end left first."""
        note = ""
        while True:
            try:
                runtime = self.load_runtime()
            except Exception as exc:  # e.g. a server address the settings schema refuses
                if not self._ask("no_server", "", message=f"{type(exc).__name__}: {exc}"):
                    return False
                continue
            api, app = runtime.config.model_api, runtime.config.app
            if not api.base_url:
                if not self._ask("no_server", "", message=note):
                    return False
                note = ""
                continue
            expected = packaged.ca_fingerprint() if api.base_url == packaged.server_url() else ""
            decision = trust.decide(
                api.base_url, api.ca_file, expected=expected, accept=self._accepted, home=self.home
            )
            if decision.status == "pinned":
                continue  # load the configuration again: it now names the pinned certificate
            if decision.status in ("unknown", "mismatch"):
                reason = "untrusted_certificate" if decision.status == "unknown" else (
                    "certificate_mismatch" if expected else "untrusted_certificate"
                )  # fmt: skip
                self._accepted = ""
                if not self._ask(reason, api.base_url, decision.fingerprint):
                    return False
                continue
            key = self._typed or self.environ.get(app.key_env) or credentials.load_saved(app)
            if not key:
                if not self._ask("no_key", api.base_url, message=note):
                    return False
                note = ""
                continue
            try:
                key = credentials.validate(key)
            except credentials.CredentialError as exc:
                self._typed, note = "", str(exc)
                if not self._ask("invalid", api.base_url, message=note):
                    return False
                continue
            status = credentials.verify_with_server(api, key)
            if status == "rejected":
                typed, self._typed = bool(self._typed), ""
                if not typed and self.environ.get(app.key_env) == key:
                    hint = f"the key in {app.key_env} was refused"
                else:
                    hint = "" if typed else "the saved key was refused"
                    if not typed:
                        credentials.forget(app)
                if not self._ask("rejected", api.base_url, message=hint):
                    return False
                continue
            if self._typed:
                credentials.save(app, key)
                self._typed = ""
            self.environ[app.key_env] = key
            if status == "unreachable":
                self._emit(
                    e1.ErrorEvent(
                        code="server_unreachable",
                        message=f"could not reach {api.base_url}; the key was not checked",
                    )
                )
            return True
