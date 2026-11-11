"""Split the built wheels into one npm package per platform plus a small launcher package.

Usage: python packaging/assemble_npm.py <wheels_dir> <out_dir>

`<out_dir>/launcher` is `@ntdev204/laris-cli` (the `laris` command); it lists the platform packages
as optionalDependencies, so npm downloads only the one that matches the user's machine.
`<out_dir>/<platform>` are `@ntdev204/laris-cli-<platform>`, each with only that platform's wheels.
Nothing is published here: pack and publish the platform packages first, then the launcher.
"""

import json
import re
import shutil
import sys
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


def platform_of(wheel: str) -> Optional[str]:
    """Maps a wheel's platform tag to a package platform; None when it is not one we ship."""
    tag = wheel[:-4].split("-")[-1]
    if tag == "win_amd64":
        return "win32-x64"
    if tag in ("linux_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"):
        return "linux-x64"
    if tag in ("linux_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"):
        return "linux-arm64"
    if re.fullmatch(r"macosx_\d+_\d+_x86_64", tag):
        return "darwin-x64"
    if re.fullmatch(r"macosx_\d+_\d+_arm64", tag):
        return "darwin-arm64"
    return None


def main(wheels: Path, out: Path) -> None:
    launcher_meta = json.loads((NPM / "package.json").read_text(encoding="utf-8"))
    version = launcher_meta["version"]
    requirements = next(iter(sorted(wheels.rglob("requirements.txt"))), None)
    if requirements is None:
        raise SystemExit("requirements.txt missing from the wheel directory")

    shutil.rmtree(out, ignore_errors=True)
    found: Dict[str, list] = {}
    for wheel in sorted(wheels.rglob("*.whl")):
        platform = platform_of(wheel.name)
        if platform is None:
            raise SystemExit(f"unexpected wheel platform: {wheel.name}")
        if wheel.name.split("-")[1] != version:
            raise SystemExit(f"{wheel.name} does not match package version {version}")
        found.setdefault(platform, []).append(wheel)

    missing = sorted(set(PLATFORMS) - set(found))
    if missing:
        raise SystemExit(f"no wheels for: {', '.join(missing)}")

    for platform, files in found.items():
        os_name, cpu = PLATFORMS[platform]
        pkg = out / platform
        (pkg / "vendor").mkdir(parents=True)
        for wheel in files:
            shutil.copy2(wheel, pkg / "vendor" / wheel.name)
        shutil.copy2(requirements, pkg / "vendor" / "requirements.txt")
        manifest = {
            "name": f"{SCOPE}-{platform}",
            "version": version,
            "description": f"Compiled LARIS client for {platform}; install {SCOPE} instead.",
            "license": launcher_meta["license"],
            "os": [os_name],
            "cpu": [cpu],
            "files": ["vendor"],
            "publishConfig": {"access": "public"},
            "repository": launcher_meta["repository"],
        }
        (pkg / "package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{platform}: {len(files)} wheels")

    launcher = out / "launcher"
    shutil.copytree(NPM, launcher, ignore=shutil.ignore_patterns("vendor", "node_modules", "*.tgz"))
    launcher_meta["optionalDependencies"] = {f"{SCOPE}-{p}": version for p in PLATFORMS}
    launcher_meta["scripts"].pop("prepack", None)  # the wheels come from CI, not from this folder
    launcher_meta["files"] = ["bin", "scripts", "README.md"]
    (launcher / "package.json").write_text(
        json.dumps(launcher_meta, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
