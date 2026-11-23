"""The prompt filter of the evaluation profile (T286): the stage every prompt passes before
retrieval, the router and the model.

Deterministic and model-free. Per prompt (the question and its options; never the gold answer):

1. **Normalise** the text handed on: Unicode form, zero-width characters dropped, odd spaces made
   plain, runs of spaces and blank lines folded, a few LaTeX spellings made one. Every change is
   counted under the rule that made it.
2. **Fold** a matching view (NFKC, case folded, look-alike letters mapped, whitespace folded); the
   rules below read only this view, which is never handed on.
3. **Injection**: the rules of the owner's policy (`.laris/prefilter.toml`, kinds named in the
   configuration) and the profile's own rules; the first that matches stops the prompt.
4. **Scope** (SR-H10 and the profile): empty or symbol-only text, a bare URL, greetings, help and
   version requests of the policy, chit-chat and creative writing stop at once; gibberish and the
   soft rules (advice, opinion, translation, travel) stop only when the prompt carries no STEM
   signal (no options, no mathematical symbol, no STEM word, no quantity with a unit).
5. **Fields**: language, quantities (value and unit), units, chemical formulas, element names and
   named constants. The fields cross-check the model's solver formalisation (`crosscheck`); they
   are never a formalisation of their own and never an answer.

The outcome is `pass`, `pass_fields` (something was extracted) or `stop` with a named rule and a
reason. All rules and thresholds are in the configuration (`configs/prompt-filter.json`).
"""

from __future__ import annotations

import math
import re
import tomllib
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PASS = "pass"
PASS_FIELDS = "pass_fields"
STOP = "stop"


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str  # canonical: numerator atoms joined by `*`, then `/` and the denominator's

    def as_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "unit": self.unit}


@dataclass
class Screen:
    """The filter's outcome for one prompt. `question` and `options` are the normalised text."""

    status: str
    question: str
    options: List[str]
    rule: Optional[str] = None
    reason: Optional[str] = None
    changes: Dict[str, int] = field(default_factory=dict)
    language: str = "und"
    quantities: List[Quantity] = field(default_factory=list)
    entities: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def stopped(self) -> bool:
        return self.status == STOP

    def record(self) -> Dict[str, Any]:
        """What a run record keeps: rules, counts and the language, never the prompt's text."""
        return {
            "status": self.status,
            "rule": self.rule,
            "changes": dict(self.changes),
            "language": self.language,
            "quantities": len(self.quantities),
            "entities": {k: len(v) for k, v in self.entities.items()},
        }


def load(path: Path, root: Path) -> "PromptFilter":
    import json

    return PromptFilter(json.loads(path.read_text(encoding="utf-8")), root)


class PromptFilter:
    """The filter built from its configuration; `root` resolves the policy file."""

    def __init__(self, cfg: Dict[str, Any], root: Path) -> None:
        self.cfg = cfg
        norm = cfg["normalise"]
        self._zero = {ord(c): None for c in norm["zero_width"]}
        self._spaces = {ord(c): " " for c in norm["spaces"]}
        self._confusables = {ord(k): v for k, v in norm.get("confusables", {}).items()}
        self._latex = [
            (r["rule"], re.compile(r["pattern"]), r["replacement"]) for r in norm["latex"]
        ]
        inj = cfg["injection"]
        self._injection = self._policy(root, inj["policy_file"], inj["policy_kinds"]) + [
            (f"injection:{r['id']}", re.compile(r["pattern"], re.I | re.S)) for r in inj["rules"]
        ]
        scope = cfg["scope"]
        self._scope_policy = self._policy(root, scope["policy_file"], scope["policy_kinds"])
        self._hard = [
            (f"out_of_scope:{r['id']}", re.compile(r["pattern"], re.I | re.S))
            for r in scope["hard"]
        ]
        self._soft = [
            (f"out_of_scope:{r['id']}", re.compile(r["pattern"], re.I | re.S))
            for r in scope["soft"]
        ]
        self._only_url = re.compile(scope["only_url"], re.I)
        self._no_content = re.compile(scope["no_content"])
        signal = scope["stem_signal"]
        self._symbols = re.compile(signal["symbols"])
        words = sorted(signal["words"], key=len, reverse=True)
        self._stem_words = re.compile(
            r"(?<![\w])(" + "|".join(re.escape(w) for w in words) + r")", re.I
        )
        lang = cfg["language"]
        self._scripts = {k: re.compile(v) for k, v in lang["scripts"].items()}
        self._vi = re.compile(lang["vietnamese_marks"], re.I)
        self._stopwords = {k: set(v) for k, v in lang["stopwords"].items()}
        ext = cfg["extract"]
        self._exclude_after = set(ext["exclude_after_words"])
        atoms = list(ext["units"]) + list(ext["unit_words"])
        self._unit_words = dict(ext["unit_words"])
        self._units = set(ext["units"])
        self._multipliers = {k: int(v) for k, v in ext.get("multipliers", {}).items()}
        self._unit_atom = re.compile(
            r"(" + "|".join(re.escape(a) for a in sorted(atoms, key=len, reverse=True)) + r")"
            r"(?:(?![A-Za-zΩμ°])|(?=(?:of|is|and|at|pressure)\b))(?:\s*\^\s*\(?([-−]?\d+)\)?|([²³¹⁻]+))?"
        )
        ent = cfg["entities"]
        self._elements = set(ent["elements"])
        self._element_names = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in ent["element_names"]) + r")\b", re.I
        )
        self._constants = dict(ent["constants"])
        self._constant_names = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in self._constants) + r")", re.I
        )
        self._min_formula = int(ent["min_formula_symbols"])

    @staticmethod
    def _policy(root: Path, name: str, kinds: Iterable[str]) -> List[Tuple[str, re.Pattern]]:
        """The owner's Prefilter rules of the given kinds, read (never changed) from the policy."""
        data = tomllib.loads((root / name).read_text(encoding="utf-8"))
        wanted = set(kinds)
        out = []
        for rule in data.get("rule", []):
            if rule["kind"] in wanted:
                pattern = rule["pattern"]
                flags = re.S
                if pattern.startswith("(?i)"):
                    pattern, flags = pattern[4:], flags | re.I
                out.append((f"policy:{rule['id']}", re.compile(pattern, flags)))
        return out

    # -- normalisation -------------------------------------------------------------------------

    def normalise(self, text: str, changes: Counter) -> str:
        """The text handed on, with each change counted under its rule."""
        norm = self.cfg["normalise"]
        out = unicodedata.normalize(norm["unicode_form"], text)
        if out != text:
            changes["unicode_form"] += 1
        dropped = out.translate(self._zero)
        if dropped != out:
            changes["zero_width"] += len(out) - len(dropped)
        out = dropped
        spaced = out.translate(self._spaces)
        if spaced != out:
            changes["odd_spaces"] += sum(1 for a, b in zip(out, spaced) if a != b)
        out = spaced
        folded = re.sub(r"[ ]{2,}", " ", out)
        folded = re.sub(r"[ ]+\n", "\n", folded)
        limit = int(norm["max_blank_lines"])
        folded = re.sub(r"\n{%d,}" % (limit + 2), "\n" * (limit + 1), folded)
        stripped = folded.strip()
        if stripped != out:
            changes["whitespace"] += 1
        out = stripped
        for rule, pattern, replacement in self._latex:
            out, count = pattern.subn(replacement, out)
            if count:
                changes[rule] += count
        return out

    def fold(self, text: str) -> str:
        """The matching view: NFKC, case folded, look-alikes mapped, whitespace folded."""
        out = unicodedata.normalize("NFKC", text).translate(self._zero).translate(self._spaces)
        out = out.casefold().translate(self._confusables)
        out = re.sub(r"[ ]{2,}", " ", out)
        return out.strip()

    def despace(self, text: str) -> str:
        """Letters spelt one by one (`i g n o r e  a l l`) joined into words, for matching only:
        a single space separates letters, two or more separate words."""
        least = int(self.cfg["normalise"]["despace_min_letters"])
        out = unicodedata.normalize("NFKC", text).translate(self._zero).translate(self._spaces)
        out = out.casefold().translate(self._confusables)

        def join(match: re.Match) -> str:
            return match.group(0).replace(" ", "")

        pattern = re.compile(r"(?<!\S)(?:\w ){%d,}\w(?!\S)" % (least - 1))
        chunks = [pattern.sub(join, chunk) for chunk in re.split(r" {2,}", out)]
        return " ".join(chunks).strip()

    # -- language ------------------------------------------------------------------------------

    def language(self, folded: str) -> str:
        lang = self.cfg["language"]
        letters = [c for c in folded if c.isalpha()]
        if len(letters) < int(lang["min_letters"]):
            return "und"
        for name, pattern in self._scripts.items():
            if len(pattern.findall(folded)) >= max(2, len(letters) // 10):
                return name
        if len(self._vi.findall(folded)) / len(letters) >= float(lang["vietnamese_min_share"]):
            return "vi"
        words = re.findall(r"[^\W\d_]+", folded)
        if not words:
            return "und"
        best, share = "und", 0.0
        for code, stop in self._stopwords.items():
            s = sum(1 for w in words if w in stop) / len(words)
            if s > share:
                best, share = code, s
        return best if share >= float(lang["min_stopword_share"]) else "und"

    # -- scope ---------------------------------------------------------------------------------

    def stem_signal(self, folded: str, options: List[str], quantities: List[Quantity]) -> bool:
        if options:
            return True
        if self._symbols.search(folded) or self._stem_words.search(folded):
            return True
        return any(q.unit for q in quantities)

    def gibberish(self, folded: str) -> bool:
        g = self.cfg["scope"]["gibberish"]
        tokens = re.findall(r"[^\W\d_]+", folded)
        if len(tokens) < int(g["min_tokens"]):
            return False
        run_max = int(g["max_consonant_run"])

        def odd(token: str) -> bool:
            runs = re.findall(r"[bcdfghjklmnpqrstvwxz]+", token)
            longest = max((len(r) for r in runs), default=0)
            no_vowel = len(token) >= 4 and not re.search(r"[aeiouy]", token)
            return longest > run_max or no_vowel

        ascii_tokens = [t for t in tokens if t.isascii()]
        if not ascii_tokens:
            return False
        return sum(1 for t in ascii_tokens if odd(t)) / len(ascii_tokens) >= float(g["min_share"])

    # -- fields --------------------------------------------------------------------------------

    @staticmethod
    def extraction_view(text: str) -> str:
        """LaTeX markup read as plain symbols, for the extraction of quantities only."""
        out = text.replace("$", " ")
        out = re.sub(
            r"\\(?:mathrm|text|textrm|mathit|operatorname|rm|mbox)\s*\{([^{}]*)\}", r" \1 ", out
        )
        out = re.sub(r"\^\s*\{?\s*\\circ\s*\}?|\\circ|\\degree", "°", out)
        out = re.sub(r"\\times|\\cdot", " × ", out)
        out = out.replace("\\%", "%").replace("\\mu", "μ").replace("\\Omega", "Ω")
        out = re.sub(r"\\AA|\\mathring\s*\{?A\}?", "Å", out)
        out = re.sub(r"\\[,;:! ]|~", " ", out)
        out = re.sub(r"\^\s*\{\s*([^{}]*)\s*\}", r"^\1", out)
        out = re.sub(r"_\s*\{\s*([^{}]*)\s*\}", r"\1", out)
        out = out.replace("{", " ").replace("}", " ").replace("−", "-")
        out = re.sub(r"(\d)\s*,\s*(\d{3})(?!\d)", r"\1\2", out)
        out = re.sub(r"°\s*K\b", "K", out)
        out = re.sub(r"(?<=\d)A°", "Å", out)
        out = re.sub(r"°\s+([CF])\b", r"°\1", out)
        out = re.sub(r"μ\s+(?=[A-Za-z])", "μ", out)
        out = re.sub(r"(^|[\s(=])-\s+(?=\d)", r"\1-", out)
        return re.sub(r"[ \t]+", " ", out)

    _NUMBER = re.compile(
        r"(?:(?<![\w.^])|(?<=[a-z]{3}))(?<!\^-)(?<![A-Za-z]-)(-?(?:\d+(?:\.\d*)?|\.\d+))"
        r"(?:\s*(?:×|x|\*)\s*10\s*(?:\^\s*\(?(-?\d+)\)?|-\^\s*(\d+))|[eE](-?\d+)(?![\w]))?"
    )

    def quantities(self, text: str) -> List[Quantity]:
        """Numbers given in `text` with the unit that follows each (canonical form)."""
        view = self.extraction_view(text)
        out: List[Quantity] = []
        consumed = 0
        for m in self._NUMBER.finditer(view):
            if m.start() < consumed:
                continue  # the denominator of a fraction already read
            if m.group(1).startswith("-") and m.start() and view[m.start() - 1].isalpha():
                continue  # a name such as carbon-14
            before = view[: m.start()].rstrip()
            word = re.search(r"([A-Za-z]+)\.?\s*\(?$", before)
            if word and word.group(1).lower() in self._exclude_after:
                continue
            if before.endswith("^"):
                continue
            value = float(m.group(1))
            exponent = m.group(2) or (f"-{m.group(3)}" if m.group(3) else None) or m.group(4)
            if exponent:
                value *= 10.0 ** int(exponent)
            rest = view[m.end() :]
            if re.match(r"[A-Z][a-z]?(?:_|\d|[A-Z(])", rest):
                continue  # a coefficient glued to a chemical formula (2H_2O, 5O_2)
            fraction = re.match(r"\s*/\s*(\d+(?:\.\d+)?)(?![\d.])", rest)
            if fraction and not exponent and float(fraction.group(1)) != 0:
                value /= float(fraction.group(1))
                consumed = m.end() + fraction.end()
                rest = rest[fraction.end() :]
            scale = re.match(r"\s*(%s)\b" % "|".join(self._multipliers), rest, re.I)
            if scale:
                value *= 10.0 ** self._multipliers[scale.group(1).lower()]
                rest = rest[scale.end() :]
            if not exponent and m.group(1) == "10":
                power = re.match(r"\s*\^\s*\(?(-?\d+)\)?", rest)
                if power:
                    value = 10.0 ** int(power.group(1))
                    rest = rest[power.end() :]
            if re.match(r"[A-Za-z]{2,}", rest) and not self._unit_atom.match(rest):
                continue  # a number glued to a word: part of a name
            out.append(Quantity(value, self.unit_after(rest)))
        return out

    def unit_after(self, rest: str) -> str:
        """The unit at the start of `rest` (`5-kg`, `m/s^2`, `J mol^-1 K^-1`), canonical."""
        limit = int(self.cfg["extract"]["max_tokens_after"])
        pos, sign, atoms = 0, 1, []
        m = re.match(r"\s*-?\s*", rest)
        pos = m.end() if m else 0
        while len(atoms) < limit:
            atom = self._unit_atom.match(rest, pos)
            if not atom:
                break
            name = atom.group(1)
            if name == "in" and re.match(r"\s*[\w(]", rest[atom.end() :]):
                break
            symbol = self._unit_words.get(name.lower(), self._unit_words.get(name, name))
            power = 1
            if atom.group(2):
                power = int(atom.group(2).replace("−", "-"))
            elif atom.group(3):
                sup = atom.group(3).translate(str.maketrans("²³¹⁻", "231-"))
                power = int(sup) if sup.lstrip("-") else 1
            atoms.append((symbol, sign * power))
            pos = atom.end()
            sep = re.match(r"\s*(/|per\b|·|\*|×(?!\s*10))\s*|\s+(?=[A-Za-zμΩ°%Å])", rest[pos:])
            if not sep:
                break
            token = (sep.group(1) or "").strip()
            if token in ("/", "per"):
                sign = -1
            nxt = self._unit_atom.match(rest, pos + sep.end())
            if not nxt:
                break
            pos += sep.end()
        return canonical_unit(atoms)

    def entities(self, text: str) -> Dict[str, List[str]]:
        view = re.sub(
            r"\\mathrm\s*\{([^{}]*)\}|_\{?(\d+)\}?", lambda m: m.group(1) or m.group(2), text
        )
        formulas = []
        for token in re.findall(r"(?<![A-Za-z])((?:[A-Z][a-z]?\d*){1,12})(?![a-z])", view):
            parts = re.findall(r"([A-Z][a-z]?)(\d*)", token)
            if not all(p[0] in self._elements for p in parts):
                continue
            if len(parts) >= self._min_formula or any(p[1] for p in parts):
                formulas.append(token)
        names = [m.group(1).lower() for m in self._element_names.finditer(text)]
        constants = [
            self._constants[m.group(1).lower()] for m in self._constant_names.finditer(text)
        ]
        return {"formulas": formulas, "elements": names, "constants": constants}

    # -- the stage -----------------------------------------------------------------------------

    def screen(self, item: Dict[str, Any]) -> Screen:
        """The outcome for one item (`question`, `options`); any other key is ignored."""
        changes: Counter = Counter()
        question = self.normalise(str(item.get("question") or ""), changes)
        options = [self.normalise(str(o), changes) for o in item.get("options") or []]
        whole = "\n".join([question] + options)
        folded = self.fold(whole)
        screen = Screen(PASS, question, options, changes=dict(changes))
        screen.language = self.language(self.fold(question))

        views = [folded]
        raw = "\n".join(
            [str(item.get("question") or "")] + [str(o) for o in item.get("options") or []]
        )
        despaced = self.despace(raw)
        if despaced != folded:
            views.append(despaced)
        for rule, pattern in self._injection:
            if any(pattern.search(view) for view in views):
                return self._stop(
                    screen, rule, "an instruction aimed at the system, not a question"
                )
        if len(folded) < int(self.cfg["scope"]["min_chars"]):
            return self._stop(screen, "out_of_scope:empty", "no question")
        if self._no_content.match(folded):
            return self._stop(screen, "out_of_scope:no_content", "no letters or digits")
        if self._only_url.match(folded):
            return self._stop(screen, "out_of_scope:only_url", "a link, not a question")
        if not options:
            asked = self.fold(question)
            for rule, pattern in self._scope_policy + self._hard:
                if pattern.search(asked):
                    return self._stop(screen, rule, "not a STEM question")

        screen.quantities = self.quantities(question)
        screen.entities = self.entities(question)
        if not self.stem_signal(folded, options, screen.quantities):
            if self.gibberish(folded):
                return self._stop(screen, "out_of_scope:gibberish", "no readable words")
            for rule, pattern in self._soft:
                if pattern.search(folded):
                    return self._stop(screen, rule, "not a STEM question and no STEM signal")
        if screen.quantities or any(screen.entities.values()):
            screen.status = PASS_FIELDS
        return screen

    @staticmethod
    def _stop(screen: Screen, rule: str, reason: str) -> Screen:
        screen.status, screen.rule, screen.reason = STOP, rule, reason
        return screen


# -- units -------------------------------------------------------------------------------------


def canonical_unit(atoms: List[Tuple[str, int]]) -> str:
    """`[("J", 1), ("mol", -1), ("K", -1)]` -> `J/mol*K`; `[("m", 2)]` -> `m^2`."""
    powers: Dict[str, int] = {}
    for symbol, power in atoms:
        powers[symbol] = powers.get(symbol, 0) + power

    def part(items: List[Tuple[str, int]]) -> str:
        return "*".join(s if abs(p) == 1 else f"{s}^{abs(p)}" for s, p in items)

    num = [(s, p) for s, p in powers.items() if p > 0]
    den = [(s, p) for s, p in powers.items() if p < 0]
    if not num and not den:
        return ""
    text = part(num) if num else "1"
    return text + ("/" + part(den) if den else "")


def unit_powers(text: str) -> Tuple[Tuple[str, int], ...]:
    """A unit string in any of the plain forms (`J/mol*K`, `J/(mol K)`, `J mol^-1 K^-1`,
    `m·s⁻²`) as sorted (symbol, power) pairs, so two spellings of one unit compare equal."""
    text = text.replace("(", " ").replace(")", " ").replace("·", "*").replace("−", "-")
    text = text.translate(str.maketrans("²³¹⁻", "231-"))
    text = re.sub(r"([A-Za-zμΩ°%Å])(-?\d)\b", r"\1^\2", text)
    powers: Dict[str, int] = {}
    for index, segment in enumerate(text.split("/")):
        sign = 1 if index == 0 else -1
        for atom in re.split(r"[*\s]+", segment.strip()):
            if not atom or atom == "1":
                continue
            name, _, power = atom.partition("^")
            p = int(power) if power else 1
            powers[name] = powers.get(name, 0) + sign * p
    return tuple(sorted((k, v) for k, v in powers.items() if v))


# -- the cross-check of a formalisation --------------------------------------------------------

_FORMAL_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)")


def formalisation_numbers(problem: Dict[str, Any]) -> List[float]:
    """The numbers a solver call writes: in its expression text and its substitutions."""
    found: List[float] = []

    def walk(value: Any, key: str = "") -> None:
        if key in (
            "operation",
            "variable",
            "variables",
            "domain",
            "direction",
            "unit",
            "target_unit",
        ):
            return
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            found.append(float(value))
        elif isinstance(value, str):
            found.extend(float(x) for x in _FORMAL_NUMBER.findall(value))
        elif isinstance(value, dict):
            if "constant" in value:
                return
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for key, value in problem.items():
        walk(value, key)
    return found


def crosscheck(
    problem: Dict[str, Any], quantities: List[Quantity], cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """Whether each number of the model's solver call is grounded in the prompt: equal to a given
    quantity, to one scaled by a unit prefix or a time factor, or one of the configured free values.
    Also how many given quantities the call used. Read only as a check, never as an answer."""
    tol = float(cfg["rel_tol"])
    free = [float(v) for v in cfg["free_values"]]
    scales = [10.0**e for e in cfg["scale_exponents"]] + [float(f) for f in cfg["scale_factors"]]
    scales += [1.0 / s for s in cfg["scale_factors"]]
    given = [abs(q.value) for q in quantities]

    def close(a: float, b: float) -> bool:
        return math.isclose(a, b, rel_tol=tol, abs_tol=1e-300)

    numbers = formalisation_numbers(problem)
    grounded, used = 0, set()
    for number in numbers:
        x = abs(number)
        hit = None
        for index, g in enumerate(given):
            if close(x, g) or any(close(x, g * s) for s in scales):
                hit = index
                break
        if hit is not None:
            used.add(hit)
            grounded += 1
        elif any(close(x, f) for f in free) or x == 0.0:
            grounded += 1
    return {
        "numbers": len(numbers),
        "ungrounded": len(numbers) - grounded,
        "quantities": len(given),
        "quantities_used": len(used),
    }


# -- measurement against a labelled fixture ----------------------------------------------------


def stop_scores(pairs: List[Tuple[str, Screen]]) -> Dict[str, Any]:
    """Precision and recall of `stop` over (label, outcome) pairs; a label is `pass`,
    `stop:injection` or `stop:out_of_scope`. A stop counts as right for its class only when the
    rule's family (`injection`/`policy` of an injection kind, `out_of_scope`/`policy` of a scope
    kind) matches the label's."""
    tp = fp = fn = tn = family_right = 0
    by_rule: Counter = Counter()
    for label, screen in pairs:
        want = label.startswith("stop")
        if screen.stopped:
            by_rule[screen.rule or ""] += 1
        if want and screen.stopped:
            tp += 1
            family_right += int(_family(screen.rule or "") == label.split(":", 1)[1])
        elif screen.stopped:
            fp += 1
        elif want:
            fn += 1
        else:
            tn += 1
    return {
        "items": len(pairs),
        "true_stop": tp,
        "false_stop": fp,
        "missed_stop": fn,
        "true_pass": tn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "stop_class_right": family_right,
        "rules": dict(sorted(by_rule.items())),
    }


_SCOPE_POLICY = ("policy:greeting", "policy:help", "policy:version")


def _family(rule: str) -> str:
    if rule.startswith("out_of_scope:") or rule in _SCOPE_POLICY:
        return "out_of_scope"
    return "injection"


def quantity_scores(
    pairs: List[Tuple[List[Dict[str, Any]], List[Quantity]]], rel_tol: float = 1e-6
) -> Dict[str, Any]:
    """Precision and recall of extracted values against labelled ones (one-to-one, by value
    within `rel_tol`), and how many matched values also carry the labelled unit (compared by
    `unit_powers`, so `J/mol*K` equals `J mol^-1 K^-1`)."""
    labelled = found = matched = unit_right = 0
    for expected, got in pairs:
        labelled += len(expected)
        found += len(got)
        free = list(got)
        waiting = list(expected)
        for same_unit in (True, False):  # pair equal units first, then values alone
            for want in list(waiting):
                for index, q in enumerate(free):
                    unit_ok = unit_powers(q.unit) == unit_powers(str(want["unit"]))
                    if same_unit and not unit_ok:
                        continue
                    if math.isclose(q.value, float(want["value"]), rel_tol=rel_tol, abs_tol=1e-300):
                        matched += 1
                        unit_right += int(unit_ok)
                        del free[index]
                        waiting.remove(want)
                        break
    return {
        "items": len(pairs),
        "labelled": labelled,
        "extracted": found,
        "matched": matched,
        "precision": matched / found if found else 0.0,
        "recall": matched / labelled if labelled else 0.0,
        "unit_right_of_matched": unit_right,
    }
