"""Build the client wheel from the blocks `protocol`, `shared` and `client`, never the server, the
model, research code, the policy files or tests.
Usage: python packaging/build_client.py <out_dir>"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Set

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
# The client is built from whole blocks (ADR-019): `protocol`, `shared` and `client`, plus the
# command modules of the `laris` program. Nothing of `server`, `model` or `research` is shipped, and
# no policy file (`.laris/`) either.
CLIENT_BLOCKS = ("protocol", "shared", "client")
CLI_MODULES = (
    "__init__",
    "client",
    "bootstrap",
    "common",
    "credentials",
    "parser",
    "commands/__init__",
    "commands/account",
    "commands/agent",
    "commands/app",
    "commands/learn",
    "commands/skills",
    "commands/vault",
)
NOT_SHIPPED = (
    "laris.server",
    "laris.model",
    "laris.research",
    "cli.main",
    "cli.server",
    "cli.model",
)


def module_file(name: str) -> Optional[Path]:
    path = SRC / (name.replace(".", "/") + ".py")
    if path.is_file():
        return path
    package = SRC / name.replace(".", "/") / "__init__.py"
    return package if package.is_file() else None


def client_files() -> List[Path]:
    """Every source file of the client program: the three blocks and its command modules."""
    files: List[Path] = [SRC / "laris" / "__init__.py"]
    for block in CLIENT_BLOCKS:
        files += sorted((SRC / "laris" / block).rglob("*.py"))
    files += [SRC / "cli" / f"{name}.py" for name in CLI_MODULES]
    return files


SETUP = """\
import glob
import os
import sys
from setuptools import Extension, find_packages, setup

modules = sorted(glob.glob(os.path.join("src", "**", "*.c"), recursive=True))
flags = ["/O2"] if sys.platform == "win32" else ["-O2", "-g0"]


def dotted(path):
    return os.path.relpath(path, "src")[:-2].replace(os.sep, ".")


extensions = [Extension(dotted(m), [m], extra_compile_args=flags) for m in modules]
setup(
    packages=find_packages("src"),
    package_dir={"": "src"},
    package_data={"laris.shared.harness": ["public_strings.yaml"]},
    exclude_package_data={"": ["*.c", "*.py"]},  # the C files quote the source: never shipped
    include_package_data=False,
    ext_modules=extensions,
    zip_safe=False,
)
"""

PYPROJECT = """\
[build-system]
requires = ["setuptools>=68.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "laris"
version = "{version}"
description = "LARIS terminal client (the model and system policy run on the LARIS server)"
requires-python = ">=3.10"
dependencies = {deps}

[project.optional-dependencies]
ocr = ["Pillow==12.3.0", "pytesseract==0.3.13", "pypdf==7.0.1"]

[project.scripts]
laris = "cli.client:main"
"""
DEPENDENCIES = ["pyyaml>=6.0", "pydantic>=2.0", "numpy>=1.24.0", "pyarrow>=12.0.0"]


def imported_modules(files: list) -> list:
    """Every module the client source imports. Compiled extensions hide their imports from
    freezers, so these are handed to PyInstaller as hidden imports."""
    names: Set[str] = set()
    for file in files:
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names if a.name != "*")
    return sorted(n for n in names if module_file(n) is None)


def compile_sources(stage: Path, files: list) -> None:
    """Turn every module (except package markers) into C, then delete its Python source."""
    from Cython.Build import cythonize  # build-time only; never a runtime dependency
    from Cython.Compiler import Options

    Options.docstrings = False  # no prose about the code in the binary

    sources = [str(stage / "src" / f.relative_to(SRC)) for f in files if f.name != "__init__.py"]
    cythonize(
        sources,
        compiler_directives={
            "language_level": 3,
            "embedsignature": False,
            "annotation_typing": False,  # keep Python annotation semantics (pydantic, dataclasses)
        },
        quiet=True,
    )
    for source in sources:
        Path(source).unlink()


SMOKE = """
import importlib, pkgutil, sys
# the development checkout must not be able to fill in for a missing module
sys.meta_path[:] = [f for f in sys.meta_path if "editable" not in type(f).__module__.lower()
                    and "editable" not in type(f).__name__.lower()]
sys.path[:] = [p for p in sys.path if not p.replace("\\\\", "/").rstrip("/").endswith("/src")]
sys.path.insert(0, sys.argv[1])
failed = []
for m in pkgutil.walk_packages([sys.argv[1]]):
    try:
        importlib.import_module(m.name)
    except Exception as exc:
        failed.append(f"{m.name}: {exc!r}"[:160])
for banned in BANNED:
    try:
        importlib.import_module(banned)
        failed.append(f"{banned} must not be in the client")
    except ImportError:
        pass
print("\\n".join(failed) or "ok")
sys.exit(1 if failed else 0)
"""


def build_python() -> Path:
    """The interpreter that builds and smoke-tests the wheel: LARIS_BUILD_PYTHON, else this one."""
    return Path(os.environ.get("LARIS_BUILD_PYTHON", sys.executable))


def wheel_command(python: Path, stage: Path, out: Path) -> list:
    """`pip wheel` where pip exists (CI, Windows, macOS); `uv build` for pip-less uv venvs."""
    has_pip = subprocess.run([str(python), "-c", "import pip"], capture_output=True).returncode == 0
    if has_pip:
        return [str(python), "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                "--wheel-dir", str(out), "-q", str(stage)]
    return ["uv", "build", "--wheel", "--no-build-isolation", "--python", str(python),
            "--out-dir", str(out), "-q", str(stage)]


def smoke(wheel: Path) -> None:
    """Unpack the wheel alone and import every module in it; no source file may remain."""
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(wheel).extractall(tmp)
        leftovers = [p for p in Path(tmp).rglob("*") if p.suffix in (".c", ".pyx")]
        leftovers += [p for p in Path(tmp).rglob("*.py") if p.name != "__init__.py"]
        if leftovers:
            raise SystemExit(f"readable source left in the wheel: {leftovers[:3]}")
        python = build_python()
        script = SMOKE.replace("BANNED", repr(NOT_SHIPPED))
        subprocess.run([str(python), "-I", "-c", script, tmp], check=True)


def main(out: Path) -> None:
    files = client_files()
    version = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M)
    assert version
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for file in files:
            target = stage / "src" / file.relative_to(SRC)  # type: ignore[union-attr]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)  # type: ignore[arg-type]
        shared = Path("laris/shared/harness/public_strings.yaml")
        shutil.copy2(SRC / shared, stage / "src" / shared)
        compile_sources(stage, files)  # type: ignore[arg-type]
        (stage / "pyproject.toml").write_text(
            PYPROJECT.format(version=version.group(1), deps=DEPENDENCIES), encoding="utf-8"
        )
        (stage / "setup.py").write_text(SETUP, encoding="utf-8")
        out.mkdir(parents=True, exist_ok=True)
        python = build_python()
        subprocess.run(wheel_command(python, stage, out), check=True)
    (out / ".gitignore").unlink(missing_ok=True)
    smoke(next(out.glob("*.whl")))
    (out / "requirements.txt").write_text("\n".join(DEPENDENCIES) + "\n", encoding="utf-8")
    (out / "imports.txt").write_text("\n".join(imported_modules(files)) + "\n", encoding="utf-8")
    print(f"{len(files)} modules compiled")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
