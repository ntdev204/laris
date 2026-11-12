"""Ask a server whether it accepts an API key (standard library only)."""

import urllib.error
import urllib.request


def check_key(base_url: str, key: str, timeout_s: float = 5.0) -> str:
    """Ask the server whether it accepts the key: `ok`, `rejected` or `unreachable`."""
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s):
            return "ok"
    except urllib.error.HTTPError as exc:
        return "rejected" if exc.code in (401, 403) else "unreachable"
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return "unreachable"
