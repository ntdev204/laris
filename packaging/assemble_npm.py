"""Build the npm packages from the per-platform program directories.

Usage: python packaging/assemble_npm.py <artifacts_dir> <out_dir>

`<artifacts_dir>/binary-<platform>/laris.tar.gz` holds one platform's frozen client (a tarball,
because CI artifacts lose file modes). `<out_dir>/<platform>` becomes
`@ntdev204/laris-cli-<platform>`; `<out_dir>/launcher` becomes `@ntdev204/laris-cli` with the
platform packages as optionalDependencies, so npm downloads only the one for the user's machine.
Nothing is published here.
"""

import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Dict

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


def main(artifacts: Path, out: Path) -> None:
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
    shutil.copytree(NPM, launcher, ignore=shutil.ignore_patterns("dist", "node_modules", "*.tgz"))
    launcher_meta["optionalDependencies"] = {f"{SCOPE}-{p}": version for p in PLATFORMS}
    launcher_meta["scripts"].pop("prepack", None)
    launcher_meta["files"] = ["bin", "scripts", "README.md"]
    (launcher / "package.json").write_text(
        json.dumps(launcher_meta, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
