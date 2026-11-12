"""T20: brain text is covered by the leak detector under a memory budget; adversarial copies
of it are blocked, in whole answers and in streams. Transformations that destroy the words
(encoding, translation, paraphrase) are outside what a shingle detector can see (threat model).
"""

import re
import sys
from pathlib import Path

from laris.shared.config.loader import load_runtime_config
from laris.shared.harness.guard import Guard, InjectionScanner, LeakDetector, SecretRedactor
from laris.shared.harness.strings import StringCatalogue

REPO = Path(__file__).resolve().parents[3]
BRAIN = sorted((REPO / ".laris" / "brain").rglob("*.md"))
TEXTS = [p.read_text(encoding="utf-8") for p in BRAIN]
CFG = load_runtime_config(REPO).security


def paragraphs(min_words=25):
    out = []
    for text in TEXTS:
        body = text.split("---", 2)[-1]
        for para in re.split(r"\n\s*\n", body):
            if len(para.split()) >= min_words and not para.lstrip().startswith(("|", "```")):
                out.append(para.strip())
    return out


def detector(budget=None):
    cfg = CFG.model_copy(update={"leak_max_shingles": budget}) if budget else CFG
    return LeakDetector(cfg, TEXTS)


def test_real_brain_fits_the_memory_budget():
    d = detector()
    assert not d.truncated and 0 < d.size < CFG.leak_max_shingles
    assert sys.getsizeof(d._shingles) < 20 * 1024 * 1024  # well under 20 MB


def test_budget_caps_the_detector_and_reports_it():
    d = detector(budget=1000)
    assert d.truncated and d.size == 1000


def test_adversarial_extraction_variants_are_all_caught():
    d, paras = detector(), paragraphs()
    assert len(paras) >= 5
    for para in paras[:25]:
        words = para.split()
        variants = {
            "verbatim": para,
            "upper": para.upper(),
            "one word per line": "\n".join(words),
            "punctuation between words": " , ".join(words),
            "bulleted": "\n".join(f"- {w}" for w in words),
            "markdown emphasis": " ".join(f"**{w}**" for w in words),
            "quoted in prose": f'The text says: "{para}" and that is all.',
            "window of 12 words": " ".join(words[5:17]),
        }
        for name, text in variants.items():
            assert d.leaked(text), (name, para[:60])


def test_unrelated_text_is_not_flagged():
    d = detector()
    assert not d.leaked("Perovskite cells reach a power conversion efficiency of 25 percent.")
    assert not d.leaked("Hãy tóm tắt bài báo này thành ba ý chính cho tôi.")


def test_streamed_leak_is_blocked_even_when_split_into_tiny_chunks():
    path = REPO / "src" / "laris" / "shared" / "harness" / "public_strings.yaml"
    strings = StringCatalogue.load(path)
    guard = Guard(
        CFG,
        strings,
        SecretRedactor(CFG, strings, REPO, {}),
        detector(),
        InjectionScanner(CFG),
    )
    para = paragraphs()[0]
    stream = guard.stream()
    emitted = []
    for i in range(0, len(para), 3):
        emitted += stream.feed(para[i : i + 3])
    emitted += stream.finish()
    assert stream.blocked and guard.hits.get("leak")
    assert para[:80] not in "".join(emitted)
