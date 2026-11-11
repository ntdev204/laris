"""Turn the compiled client wheel into a self-contained program (no Python needed to run it).

Usage: python packaging/build_binary.py <wheel_dir> <out_dir>

Creates a throwaway virtualenv, installs the wheel and its pinned libraries into it (never the
source tree), freezes `cli.client` with PyInstaller (one directory, `<out_dir>/laris`) and
smoke-tests the result. PyInstaller is a build-time tool only, not a runtime dependency.
"""

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import List

ENTRY = "from cli.client import main\nimport sys\nsys.exit(main())\n"
PYINSTALLER = "pyinstaller>=6.10,<7"


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def top_level_packages(wheel: Path) -> List[str]:
    names = {n.split("/")[0] for n in zipfile.ZipFile(wheel).namelist() if "/" in n}
    return sorted(n for n in names if not n.endswith(".dist-info") and not n.endswith(".data"))


def run(cmd: List[str], **kw) -> None:  # type: ignore[no-untyped-def]
    subprocess.run(cmd, check=True, **kw)


def main(wheels: Path, out: Path) -> None:
    wheel = next(iter(sorted(wheels.glob("*.whl"))), None)
    if wheel is None:
        raise SystemExit(f"no wheel in {wheels}")
    requirements = wheels / "requirements.txt"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        venv = work / "venv"
        run([sys.executable, "-m", "venv", str(venv)])
        py = str(venv_python(venv))
        run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
        run([py, "-m", "pip", "install", "-q", "--no-index", "--no-deps", str(wheel)])
        run([py, "-m", "pip", "install", "-q", "-r", str(requirements), PYINSTALLER])
        entry = work / "laris_entry.py"
        entry.write_text(ENTRY, encoding="utf-8")
        args = [
            py, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "laris",
            "--distpath", str(out), "--workpath", str(work / "build"), "--specpath", str(work),
            "--copy-metadata", "laris", "--collect-data", "harness",
        ]
        for package in top_level_packages(wheel):
            args += ["--collect-submodules", package]
        imports = wheels / "imports.txt"
        if imports.is_file():  # compiled modules hide their imports from the freezer
            for name in imports.read_text(encoding="utf-8").split():
                args += ["--hidden-import", name]
        run(args + [str(entry)], cwd=work)  # cwd away from the source tree: only the wheel is seen
    exe = out / "laris" / ("laris.exe" if os.name == "nt" else "laris")
    for probe in (["--version"], ["--help"], ["skills", "check"]):
        result = subprocess.run([str(exe), *probe], capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not (result.stdout or result.stderr).strip():
            raise SystemExit(f"smoke test failed: {probe}\n{result.stdout}\n{result.stderr}")
    version = subprocess.run([str(exe), "--version"], capture_output=True, text=True).stdout
    print(f"built {exe}: {version.strip()}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
