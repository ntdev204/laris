"""Build the npm packages from the per-platform program directories.

Usage: python packaging/assemble_npm.py <artifacts_dir> <out_dir> [<front_end_build>]

`<artifacts_dir>/binary-<platform>/laris.tar.gz` holds one platform's frozen client (a tarball,
because CI artifacts lose file modes). `<out_dir>/<platform>` becomes
`@ntdev204/laris-cli-<platform>`; `<out_dir>/launcher` becomes `@ntdev204/laris-cli` with the
platform packages as optionalDependencies, so npm downloads only the one for the user's machine.
The launcher also carries the compiled Ink front end (`npm ci && npm run build` in `packaging/npm`
writes `build/src`, the default for `<front_end_build>`). Nothing is published here.
"""

import json
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


def main(artifacts: Path, out: Path, front_end: Optional[Path] = None) -> None:
    front_end = front_end or NPM / "build" / "src"
    if not (front_end / "main.js").is_file():
        raise SystemExit(
            f"no compiled front end at {front_end}: run `npm ci && npm run build` in packaging/npm"
        )
    launcher_meta = json.loads((NPM / "package.json").read_text(encoding="utf-8"))
    version = launcher_meta["version"]
    shutil.rmtree(out, ignore_errors=True)

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
            "files": ["laris"],
            "publishConfig": {"access": "public"},
            "repository": launcher_meta["repository"],
        }
        (pkg / "package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{platform}: ok")
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
