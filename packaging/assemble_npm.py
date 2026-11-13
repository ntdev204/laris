"""Build the npm packages from the per-platform program directories.

Usage: python packaging/assemble_npm.py <artifacts_dir> <out_dir> [<front_end_build>]

`<artifacts_dir>/binary-<platform>/laris.tar.gz` holds one platform's frozen client (a tarball,
because CI artifacts lose file modes). `<out_dir>/<platform>` becomes
`@ntdev204/laris-cli-<platform>`; `<out_dir>/launcher` becomes `@ntdev204/laris-cli` with the
platform packages as optionalDependencies, so npm downloads only the one for the user's machine.
The launcher also carries the compiled Ink front end (`npm ci && npm run build` in `packaging/npm`
writes `build/src`, the default for `<front_end_build>`). Nothing is published here.

Packaged defaults (ADR-019 D24): when `LARIS_DEFAULT_SERVER_URL` is set (a repository variable in
the release workflow), every platform package gets a `defaults.json` beside the program with the
server address and, if `LARIS_DEFAULT_SERVER_CA_FINGERPRINT` is set, the SHA-256 fingerprint of the
server's private certificate authority. Neither value is in the source tree.
"""

import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Dict, Optional

HERE = Path(__file__).resolve().parent
NPM = HERE / "npm"
SCOPE = "@ntdev204/laris-cli"

# platform -> (npm `os`, npm `cpu`)
PLATFORMS: Dict[str, tuple] = {
    "win32-x64": ("win32", "x64"),
    "linux-x64": ("linux", "x64"),
    "linux-arm64": ("linux", "arm64"),
    "darwin-x64": ("darwin", "x64"),
    "darwin-arm64": ("darwin", "arm64"),
}


def packaged_defaults(environ: Optional[Dict[str, str]] = None) -> Optional[Dict[str, object]]:
    """The content of `defaults.json`, or None when the build names no default server."""
    env = os.environ if environ is None else environ
    url = env.get("LARIS_DEFAULT_SERVER_URL", "").strip().rstrip("/")
    if not url:
        return None
    if not url.startswith("https://"):
        raise SystemExit("LARIS_DEFAULT_SERVER_URL must start with https://")
    server: Dict[str, str] = {"url": url}
    fingerprint = env.get("LARIS_DEFAULT_SERVER_CA_FINGERPRINT", "").strip()
    if fingerprint:
        digits = "".join(c for c in fingerprint.upper().replace("SHA256", "") if c.isalnum())
        if len(digits) != 64 or any(c not in "0123456789ABCDEF" for c in digits):
            raise SystemExit("LARIS_DEFAULT_SERVER_CA_FINGERPRINT must be a SHA-256 fingerprint")
        server["caFingerprint"] = fingerprint
    return {"server": server}


def main(artifacts: Path, out: Path, front_end: Optional[Path] = None) -> None:
    front_end = front_end or NPM / "build" / "src"
    if not (front_end / "main.js").is_file():
        raise SystemExit(
            f"no compiled front end at {front_end}: run `npm ci && npm run build` in packaging/npm"
        )
    launcher_meta = json.loads((NPM / "package.json").read_text(encoding="utf-8"))
    version = launcher_meta["version"]
    shutil.rmtree(out, ignore_errors=True)
    defaults = packaged_defaults()

    missing = []
    for platform, (os_name, cpu) in PLATFORMS.items():
        archive = artifacts / f"binary-{platform}" / "laris.tar.gz"
        if not archive.is_file():
            missing.append(platform)
            continue
        pkg = out / platform
        pkg.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            tar.extractall(pkg, filter="tar")  # keeps file modes, refuses paths outside pkg
        if not any((pkg / "laris").glob("laris*")):
            raise SystemExit(f"{platform}: the archive has no laris program")
        manifest = {
            "name": f"{SCOPE}-{platform}",
            "version": version,
            "description": f"LARIS client for {platform}; install {SCOPE} instead.",
            "license": launcher_meta["license"],
            "os": [os_name],
            "cpu": [cpu],
            "files": ["laris", "defaults.json"],
            "publishConfig": {"access": "public"},
            "repository": launcher_meta["repository"],
        }
        (pkg / "package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if defaults is not None:
            (pkg / "defaults.json").write_text(
                json.dumps(defaults, indent=2) + "\n", encoding="utf-8"
            )
        print(f"{platform}: ok" + (" (with a default server)" if defaults else ""))
    if missing:
        raise SystemExit(f"no build for: {', '.join(missing)}")

    launcher = out / "launcher"
    shutil.copytree(
        NPM,
        launcher,
        ignore=shutil.ignore_patterns(
            "dist", "node_modules", "*.tgz", "build", "test", "src", "tsconfig.json",
            "package-lock.json",
        ),
    )  # fmt: skip
    shutil.copytree(front_end, launcher / "build" / "src")
    launcher_meta["optionalDependencies"] = {f"{SCOPE}-{p}": version for p in PLATFORMS}
    launcher_meta.pop("devDependencies", None)
    launcher_meta["scripts"] = {"postinstall": launcher_meta["scripts"]["postinstall"]}
    launcher_meta["files"] = ["bin", "scripts", "build/src", "README.md"]
    (launcher / "package.json").write_text(
        json.dumps(launcher_meta, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
