"""One-off: move the top-level packages of `src/` into the blocks of ADR-019 and rewrite imports.

Usage: python scripts/move_to_blocks.py [--apply]

Without `--apply` it prints the planned moves. The script is kept for the record (task T50); it
refuses to run twice because the old packages no longer exist after the move.
`cli` stays where it is: the entry points are split by block in T52.
"""

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

# (old dotted prefix, new dotted prefix). The longest matching prefix wins.
RULES: List[Tuple[str, str]] = [
    ("core", "laris.shared.core"),
    ("config", "laris.shared.config"),
    ("retrieval", "laris.shared.retrieval"),
    ("graph", "laris.shared.graph"),
    ("scientific", "laris.shared.scientific"),
    ("scholarly", "laris.shared.scholarly"),
    ("skills", "laris.shared.skills"),
    # vault: format library and index shared, project vault client, brain server
    ("vault", "laris.shared.vault"),
    ("vault.project", "laris.client.vault.project"),
    ("vault.hooks", "laris.client.vault.hooks"),
    ("vault.knowledge", "laris.client.vault.knowledge"),
    ("vault.entities", "laris.client.vault.entities"),
    ("vault.memory", "laris.client.vault.memory"),
    ("vault.proposals", "laris.client.vault.proposals"),
    ("vault.brain", "laris.server.brain"),
    # harness: primitives shared, runtime and credentials client, policy composition server
    ("harness", "laris.client.harness"),
    ("harness.audit", "laris.shared.harness.audit"),
    ("harness.guard", "laris.shared.harness.guard"),
    ("harness.integrity", "laris.shared.harness.integrity"),
    ("harness.prefs", "laris.shared.harness.prefs"),
    ("harness.strings", "laris.shared.harness.strings"),
    ("harness.trust", "laris.shared.harness.trust"),
    ("harness.prompts", "laris.server.policy.prompts"),
    ("harness.policy", "laris.server.policy.policy"),
    ("harness.workflows", "laris.server.policy.workflows"),
    ("harness.verifier", "laris.server.policy.verifier"),
    ("agent", "laris.client.agent"),
    ("application", "laris.client.application"),
    ("learning", "laris.client.learning"),
    ("gateway", "laris.server.gateway"),
    ("serving", "laris.server.serving"),
    ("serverdata", "laris.server.serverdata"),
    ("execution", "laris.model.execution"),
    # language: representation and tokenizer shared, inference in the model block, the rest research
    ("language", "laris.shared.language"),
    ("language.inference", "laris.model.inference"),
    ("language.training", "laris.research.language.training"),
    ("language.evaluation", "laris.research.language.evaluation"),
    ("language.benchmarks", "laris.research.language.benchmarks"),
    ("corpus", "laris.research.corpus"),
    ("evaluation", "laris.research.evaluation"),
    ("orchestration", "laris.research.orchestration"),
    ("reasoning", "laris.research.reasoning"),
    ("reporting", "laris.research.reporting"),
]
RULES.sort(key=lambda r: -len(r[0]))
ROOTS = sorted({r[0].split(".")[0] for r in RULES})

# files whose package `__init__` content stays with the first listed target
SPLIT_INIT = {"vault": "laris/shared/vault", "harness": "laris/client/harness",
              "language": "laris/shared/language"}


def new_name(old: str) -> Optional[str]:
    for prefix, target in RULES:
        if old == prefix or old.startswith(prefix + "."):
            return target + old[len(prefix):]
    return None


def module_of(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")


def inventory() -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    for root in ROOTS:
        for path in sorted((SRC / root).rglob("*.py")):
            found[module_of(path)] = path
    return found


def target_path(path: Path, mod: str) -> Path:
    target = new_name(mod)
    assert target is not None
    parts = target.split(".")
    if path.name == "__init__.py":
        return SRC.joinpath(*parts, "__init__.py")
    return SRC.joinpath(*parts).with_suffix(".py")


DOTTED = re.compile(r"(?<![\w./-])((?:%s)(?:\.\w+)+)" % "|".join(ROOTS))
IMPORT = re.compile(r"^(\s*)(from|import)\s+((?:%s)(?:\.\w+)*)\b" % "|".join(ROOTS))


def rewrite_dotted(text: str, known: set, strict: bool = False) -> str:
    """Rewrite every dotted name in `text` whose longest prefix is a known module."""

    def sub(match: "re.Match[str]") -> str:
        dotted = match.group(1)
        parts = dotted.split(".")
        for end in range(len(parts), 0, -1):
            head = ".".join(parts[:end])
            if head in known and not (strict and end == 1 and parts[end:]):
                tail = parts[end:]
                return ".".join([new_name(head) or head, *tail])
        return dotted

    return DOTTED.sub(sub, text)


def rewrite_file(path: Path, known: set) -> bool:
    text = path.read_text(encoding="utf-8")
    out_lines: List[str] = []
    changed = False
    # imports: line based
    for line in text.splitlines(keepends=True):
        m = IMPORT.match(line)
        if m:
            new = rewrite_dotted(line[m.start(3):], known)
            line2 = line[: m.start(3)] + new
            changed |= line2 != line
            line = line2
        out_lines.append(line)
    text2 = "".join(out_lines)
    if path.suffix == ".py":  # strings: only STRING tokens, never variable names
        result: List[str] = []
        last = (1, 0)
        lines = text2.splitlines(keepends=True)
        tokens = list(tokenize.generate_tokens(io.StringIO(text2).readline))
        offsets = [0]
        for ln in lines:
            offsets.append(offsets[-1] + len(ln))
        pos = 0
        for tok in tokens:
            if tok.type != tokenize.STRING:
                continue
            start = offsets[tok.start[0] - 1] + tok.start[1]
            end = offsets[tok.end[0] - 1] + tok.end[1]
            new = rewrite_dotted(tok.string, known, strict=True)
            if new != tok.string:
                result.append(text2[pos:start])
                result.append(new)
                pos = end
        result.append(text2[pos:])
        del last
        text3 = "".join(result)
    else:
        text3 = rewrite_dotted(text2, known)
    if text3 != text:
        path.write_text(text3, encoding="utf-8")
        return True
    return False


def main(apply: bool) -> int:
    mods = inventory()
    known = set(mods)
    if not mods:
        print("nothing to move (already done)")
        return 1
    plan = {p: target_path(p, m) for m, p in mods.items()}
    # data files
    strings = "public_strings.yaml"
    extra = [(SRC / "harness" / strings, SRC / "laris/shared/harness" / strings)]
    if not apply:
        for src, dst in sorted(plan.items()):
            print(f"{src.relative_to(REPO)} -> {dst.relative_to(REPO)}")
        return 0
    for src, dst in list(plan.items()) + extra:
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(src)], cwd=REPO, capture_output=True
        ).returncode == 0
        if tracked:
            subprocess.run(["git", "mv", str(src), str(dst)], check=True, cwd=REPO)
        else:
            src.rename(dst)
    # package markers for every new directory
    for path in sorted((SRC / "laris").rglob("*")):
        if path.is_dir() and path.name != "__pycache__":
            init = path / "__init__.py"
            if not init.exists():
                init.write_text(f'"""{path.relative_to(SRC).as_posix().replace("/", ".")}"""\n')
    for root in ROOTS:  # leftovers: caches and empty directories
        left = SRC / root
        if left.exists():
            for p in sorted(left.rglob("*"), reverse=True):
                if p.is_file() and p.suffix == ".pyc" or p.name == "__pycache__":
                    if p.is_dir():
                        for q in p.iterdir():
                            q.unlink()
                        p.rmdir()
                    else:
                        p.unlink()
                elif p.is_dir():
                    p.rmdir()
            left.rmdir()
    targets = [SRC, REPO / "tests", REPO / "scripts", REPO / "packaging"]
    count = 0
    for base in targets:
        for path in base.rglob("*.py"):
            if path.name == "move_to_blocks.py":
                continue
            count += rewrite_file(path, known)
    print(f"rewrote {count} files")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
