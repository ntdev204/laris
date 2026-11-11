"""Build the client wheel: only the modules `cli.client` can reach, never the server, the gateway,
the policy files or tests. Usage: python packaging/build_client.py <out_dir>"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Set

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
ENTRY = "cli.client"
# Never shipped, whatever imports them: server side and operator tooling.
EXCLUDE = ("gateway", "serving", "cli.main", "cli.server")


def module_file(name: str) -> Optional[Path]:
    path = SRC / (name.replace(".", "/") + ".py")
    if path.is_file():
        return path
    package = SRC / name.replace(".", "/") / "__init__.py"
    return package if package.is_file() else None


def closure(entry: str) -> Set[str]:
    seen: Set[str] = set()
    todo = [entry]
    while todo:
        name = todo.pop()
        if name in seen or any(name == e or name.startswith(e + ".") for e in EXCLUDE):
            continue
        file = module_file(name)
        if file is None:
            continue
        seen.add(name)
        parts = name.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                todo.append(node.module)
                todo += [f"{node.module}.{a.name}" for a in node.names]
    return seen


SETUP = """\
import glob
from setuptools import Extension, find_packages, setup

modules = sorted(glob.glob("src/**/*.c", recursive=True))
extensions = [
    Extension(m[len("src/"):-2].replace("/", "."), [m], extra_compile_args=["-O2", "-g0"])
    for m in modules
]
setup(
    packages=find_packages("src"),
    package_dir={"": "src"},
    package_data={"harness": ["public_strings.yaml"]},
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
sys.path[:] = [p for p in sys.path if not p.rstrip("/").endswith("/src")]
sys.path.insert(0, sys.argv[1])
failed = []
for m in pkgutil.walk_packages([sys.argv[1]]):
    try:
        importlib.import_module(m.name)
    except Exception as exc:
        failed.append(f"{m.name}: {exc!r}"[:160])
for banned in ("gateway", "serving", "cli.main"):
    try:
        importlib.import_module(banned)
        failed.append(f"{banned} must not be in the client")
    except ImportError:
        pass
print("\\n".join(failed) or "ok")
sys.exit(1 if failed else 0)
"""


def smoke(wheel: Path) -> None:
    """Unpack the wheel alone and import every module in it; no source file may remain."""
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(wheel).extractall(tmp)
        leftovers = [p for p in Path(tmp).rglob("*") if p.suffix in (".c", ".pyx")]
        leftovers += [p for p in Path(tmp).rglob("*.py") if p.name != "__init__.py"]
        if leftovers:
            raise SystemExit(f"readable source left in the wheel: {leftovers[:3]}")
        python = Path(os.environ.get("LARIS_BUILD_PYTHON", REPO / ".venv/bin/python"))
        subprocess.run([str(python), "-I", "-c", SMOKE, tmp], check=True)


def main(out: Path) -> None:
    files = sorted({module_file(m) for m in closure(ENTRY)} - {None})
    version = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M)
    assert version
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for file in files:
            target = stage / "src" / file.relative_to(SRC)  # type: ignore[union-attr]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)  # type: ignore[arg-type]
        shutil.copy2(SRC / "harness" / "public_strings.yaml", stage / "src/harness/")
        compile_sources(stage, files)  # type: ignore[arg-type]
        (stage / "pyproject.toml").write_text(
            PYPROJECT.format(version=version.group(1), deps=DEPENDENCIES), encoding="utf-8"
        )
        (stage / "setup.py").write_text(SETUP, encoding="utf-8")
        out.mkdir(parents=True, exist_ok=True)
        python = Path(os.environ.get("LARIS_BUILD_PYTHON", REPO / ".venv/bin/python"))
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--no-build-isolation",
                "--python",
                str(python),
                "--out-dir",
                str(out),
                "-q",
                str(stage),
            ],
            check=True,
        )
    (out / ".gitignore").unlink(missing_ok=True)
    smoke(next(out.glob("*.whl")))
    (out / "requirements.txt").write_text("\n".join(DEPENDENCIES) + "\n", encoding="utf-8")
    print(f"{len(files)} modules compiled")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
