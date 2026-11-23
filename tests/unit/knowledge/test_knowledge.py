"""T277: OpenStax CNXML and MathML become Source text and quotable statements; formulas the solver
can read get a verified solver link; CODATA lines become claims; nothing is invented. The XML is
written for the test (no book or benchmark text)."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from laris.model.solver import SolverSettings
from laris.model.solver.engine import solve
from laris.research.knowledge import build, mathml
from laris.research.knowledge.cnxml import Reader, sentences

M = 'xmlns:m="http://www.w3.org/1998/Math/MathML"'


def math(inner: str) -> ET.Element:
    return ET.fromstring(f"<m:math {M}>{inner}</m:math>")


@pytest.mark.parametrize(
    "inner, text, form",
    [
        (
            "<m:mi>v</m:mi><m:mo>=</m:mo><m:msub><m:mi>v</m:mi><m:mn>0</m:mn></m:msub><m:mo>+</m:mo>"
            "<m:mi>a</m:mi><m:mi>t</m:mi>",
            "v = v_0 + at",
            "v = v_0+a*t",
        ),
        (
            "<m:mi>E</m:mi><m:mo>=</m:mo><m:mi>m</m:mi><m:msup><m:mi>c</m:mi><m:mn>2</m:mn></m:msup>",
            "E = mc^2",
            "E = m*(c)**(2)",
        ),
        (
            "<m:mi>T</m:mi><m:mo>=</m:mo><m:mn>2</m:mn><m:mi>π</m:mi><m:msqrt><m:mfrac><m:mi>L</m:mi>"
            "<m:mi>g</m:mi></m:mfrac></m:msqrt>",
            "T = 2πsqrt(L/g)",
            None,
        ),
        (
            "<m:mi>ω</m:mi><m:mo>=</m:mo><m:mfrac><m:mrow><m:mn>2</m:mn><m:mi>π</m:mi></m:mrow>"
            "<m:mi>T</m:mi></m:mfrac>",
            "ω = (2π)/T",
            None,
        ),
    ],
)
def test_mathml_is_written_as_one_line_and_read_strictly(inner, text, form):
    node = math(inner)
    assert mathml.as_text(node) == text
    if form is not None:
        assert mathml.solver_form(node) == form


def test_words_inside_a_formula_keep_their_spaces():
    node = math(
        "<m:mi>u</m:mi><m:mo>&lt;</m:mo><m:mi>a</m:mi><m:mtext>or</m:mtext>"
        "<m:mi>u</m:mi><m:mo>&gt;</m:mo><m:mi>b</m:mi>"
    )
    assert mathml.as_text(node) == "u < a or u > b"


def test_greek_and_pi_are_names_the_solver_reads():
    form = mathml.solver_form(
        math(
            "<m:mi>ω</m:mi><m:mo>=</m:mo><m:mfrac><m:mrow><m:mn>2</m:mn><m:mi>π</m:mi></m:mrow>"
            "<m:mi>T</m:mi></m:mfrac>"
        )
    )
    assert form == "omega = ((2*pi)/(T))"
    out = solve(
        {"operation": "solve", "expression": form, "variable": "omega", "domain": "complex"},
        SolverSettings(isolate=False),
    )
    assert build.usable(out)


def test_a_result_with_a_failed_check_or_no_check_is_not_linked():
    assert not build.usable({"status": "proposal", "answer": ["x"], "checks": []})
    assert not build.usable(
        {
            "status": "proposal",
            "answer": ["x"],
            "checks": [{"route": "substitution", "passed": False}],
        }
    )
    assert not build.usable(
        {
            "status": "proposal",
            "answer": "Intersection({x}, Reals)",
            "checks": [{"route": "substitution", "passed": True}],
        }
    )
    assert build.usable({"status": "verified", "answer": "1", "checks": []})


@pytest.mark.parametrize(
    "inner",
    [
        # a vector, an integral, an inequality, two equals signs, nothing but numbers
        "<m:mover><m:mi>F</m:mi><m:mo>→</m:mo></m:mover><m:mo>=</m:mo><m:mi>m</m:mi>"
        "<m:mover><m:mi>a</m:mi><m:mo>→</m:mo></m:mover>",
        "<m:mi>W</m:mi><m:mo>=</m:mo><m:mo>∫</m:mo><m:mi>F</m:mi><m:mi>d</m:mi><m:mi>x</m:mi>",
        "<m:mi>x</m:mi><m:mo>≤</m:mo><m:mn>3</m:mn>",
        "<m:mi>a</m:mi><m:mo>=</m:mo><m:mi>b</m:mi><m:mo>=</m:mo><m:mi>c</m:mi>",
        "<m:mn>2</m:mn><m:mo>=</m:mo><m:mn>2</m:mn>",
    ],
)
def test_formulas_outside_the_subset_get_no_solver_form(inner):
    assert mathml.solver_form(math(inner)) is None


MODULE = f"""<document xmlns="http://cnx.rice.edu/cnxml" {M}>
<title>Motion Along a Line</title>
<metadata xmlns:md="http://cnx.rice.edu/mdml"><md:title>Motion Along a Line</md:title></metadata>
<content>
<para id="p1">A body moves along a line. Its <term>velocity</term> changes when a force acts.</para>
<note id="n1"><title>Final Velocity</title>
<para id="p2">For constant acceleration the final velocity is</para>
<equation id="e1"><m:math><m:mi>v</m:mi><m:mo>=</m:mo><m:msub><m:mi>v</m:mi><m:mn>0</m:mn></m:msub>
<m:mo>+</m:mo><m:mi>a</m:mi><m:mi>t</m:mi></m:math></equation></note>
<exercise id="x1"><problem>
<para>A car starts from rest and reaches 20 m/s. Find its acceleration.</para></problem>
<solution><para>The acceleration is 4 m/s squared.</para></solution></exercise>
<section class="key-equations"><title>Key Equations</title>
<table id="t1"><tgroup cols="2"><tbody><row><entry>Average speed</entry>
<entry><m:math><m:mi>s</m:mi><m:mo>=</m:mo><m:mfrac><m:mi>d</m:mi><m:mi>t</m:mi></m:mfrac></m:math></entry>
</row></tbody></tgroup></table></section>
<section class="key-concepts"><title>Key Concepts</title>
<list id="l1"><item>Velocity is the rate of change of position with time.</item></list></section>
<section class="review-problems"><title>Problems</title>
<para>How far does a train travel in two hours?</para></section>
</content>
<glossary><definition id="d1"><term>velocity</term>
<meaning>rate of change of position with time</meaning></definition></glossary>
</document>"""

READER = Reader(["exercise", "solution", "problem"], ["review-problems"])


def test_a_module_keeps_knowledge_and_leaves_exercises_out():
    module = READER.module("m1", MODULE, 1200)
    assert module.title == "Motion Along a Line"
    assert "Final Velocity" in module.text and "v = v_0 + at" in module.text
    assert "velocity: rate of change of position with time" in module.text
    for dropped in ("car starts from rest", "4 m/s squared", "train travel"):
        assert dropped not in module.text
    kinds = {s.kind: s for s in module.statements}
    assert kinds["definition"].text == "velocity: rate of change of position with time"
    assert kinds["key-concept"].text == "Velocity is the rate of change of position with time."
    assert kinds["key-equation"].text == "Average speed | s = d/t"
    assert kinds["key-equation"].formula == "s = ((d)/(t))"
    assert kinds["law"].text.startswith("Final Velocity For constant acceleration")
    assert kinds["law"].formula == "v = v_0+a*t"
    folded = " ".join(module.text.split())
    assert all(s.text in folded for s in module.statements), "every statement is a quote"


def test_sentences_do_not_split_after_an_abbreviation():
    text = "Forces add as vectors, e.g. two pushes. Mass is not weight at all here."
    assert sentences(text) == [
        "Forces add as vectors, e.g. two pushes.",
        "Mass is not weight at all here.",
    ]


def test_large_text_is_cut_at_block_boundaries():
    text = "\n\n".join(f"block {i} " + "x" * 40 for i in range(10)) + "\n"
    parts = build.split_parts(text, 120)
    assert len(parts) > 1 and all(len(p.encode()) <= 120 for p in parts)
    assert "".join(p.replace("\n", "") for p in parts) == text.replace("\n", "")


def test_solver_links_calls_whose_checks_passed_and_reuses_them():
    calls = []

    def call(problem):
        calls.append(problem)
        return solve(problem, SolverSettings(isolate=False))

    links = build.SolverLinks(call, "tool:test")
    first = links.formula("v = v_0+a*t")
    assert first and links.formula("v = v_0+a*t") == first and len(calls) == 1
    run = links.sources[first]
    assert run["kind"] == "tool_run" and run["command"].startswith("solve_stem ")
    # a symbolic solve: substitution checked, completeness not checkable: a proposal, kept as one
    assert json.loads(run["text"])["result"]["status"] == "proposal"
    assert links.linked == {"proposal": 1}
    # the left side used on the right, a left side that is not one name, nothing to solve
    assert links.formula("x = x+1") is None
    assert links.formula("a+b = c") is None
    assert links.formula(None) is None
    assert build.SolverLinks(None, "tool:test").formula("v = v_0+a*t") is None


def test_a_solver_failure_leaves_the_formula_unlinked():
    def call(problem):
        raise RuntimeError("timed out")

    assert build.SolverLinks(call, "tool:test").formula("v = v_0+a*t") is None


def test_codata_lines_quote_the_table_and_refuse_a_changed_file(tmp_path: Path):
    table = tmp_path / "allascii.txt"
    table.write_text(
        "  Quantity    Value    Uncertainty    Unit\n"
        + "-" * 40
        + "\n"
        + "speed of light in vacuum".ljust(60)
        + "299 792 458".ljust(25)
        + "(exact)".ljust(25)
        + "m s^-1\n",
        encoding="utf-8",
    )
    config = {
        "codata": {
            "identifier": "https://example.org/allascii.txt",
            "registry": "fixture",
            "licence": "public",
        },
        "build": {"proposer": "tool:test"},
    }
    links = build.SolverLinks(lambda p: solve(p, SolverSettings(isolate=False)), "tool:test")
    with pytest.raises(ValueError):
        build.codata_lines(config, table, "0" * 64, links)
    sources, claims, counts = build.codata_lines(
        config, table, build.sha256(table.read_bytes()), links
    )
    assert counts == {"constants": 1}
    assert claims[0]["statement"] == "speed of light in vacuum 299 792 458 (exact) m s^-1"
    assert " ".join(sources[0]["text"].split()).count(claims[0]["quote"]) == 1
    assert "Licence: public" in sources[0]["text"]


def test_titles_avoid_the_characters_a_note_name_cannot_hold():
    assert (
        build.safe_title("OpenStax m1 Forces: Newton's [Laws] / #1")
        == "OpenStax m1 Forces Newton's Laws 1"
    )


def test_blocks_sharing_a_benchmark_sequence_are_left_out_alone_or_across_a_boundary():
    from laris.research.stem import leakage

    item = {"id": "fixture/1", "question": "alpha beta gamma delta epsilon", "options": []}
    grams = set(leakage.item_index([item], 3))

    def overlaps(text):
        return not grams.isdisjoint(leakage.ngrams(text, 3))

    blocks = ["one two alpha beta gamma", "zeta eta", "three alpha beta", "gamma four", "five six"]
    kept, left_out = build.decontaminate(blocks, overlaps)
    # the first holds a sequence itself; the third and fourth make one only together
    assert kept == ["zeta eta", "three alpha beta", "five six"] and left_out == 2
    assert not overlaps("\n\n".join(kept))
    # across three blocks: the middle one is shorter than the sequence
    kept, left_out = build.decontaminate(["x alpha", "beta", "gamma y", "z"], overlaps, span=3)
    assert kept == ["x alpha", "beta", "z"] and left_out == 1
    links = build.SolverLinks(
        lambda p: solve(p, SolverSettings(isolate=False)), "tool:test", lambda t: "v_0" in t
    )
    assert links.formula("v = v_0+a*t") is None, "a run whose text overlaps is not linked"


def test_whole_exercise_modules_are_left_out_by_title(tmp_path: Path):
    repo, commit = "osbooks-fixture", "c" * 40
    folder = tmp_path / "data" / "raw" / "openstax" / f"{repo}@{commit[:12]}"
    (folder / "collections").mkdir(parents=True)
    (folder / "collections" / "book.collection.xml").write_text(
        '<col:collection xmlns:col="http://cnx.rice.edu/collxml" xmlns:md="http://cnx.rice.edu/mdml">'
        "<col:metadata><md:title>Fixture Book</md:title></col:metadata><col:content>"
        '<col:module document="m1"/><col:module document="m2"/></col:content></col:collection>',
        encoding="utf-8",
    )
    for mid, title in (
        ("m1", "Motion Along a Line"),
        ("m2", "Practice Tests (1-4) and Final Exams"),
    ):
        (folder / "modules" / mid).mkdir(parents=True)
        (folder / "modules" / mid / "index.cnxml").write_text(
            MODULE.replace("Motion Along a Line", title), encoding="utf-8"
        )
    rels = {f"modules/{m}/index.cnxml": "0" * 64 for m in ("m1", "m2")}
    provenance = {
        "files": {str(folder.relative_to(tmp_path)): rels},
        "books": [
            {
                "repo": repo,
                "commit": commit,
                "title": "Fixture Book",
                "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            }
        ],
    }
    config = {
        "data_dir": "data",
        "catalogue_registry": "fixture",
        "source_part_bytes": 90000,
        "openstax": [{"repo": repo, "commit": commit, "collections": ["book"]}],
        "build": {
            "proposer": "tool:test",
            "dropped_elements": ["exercise"],
            "dropped_classes": ["review-problems"],
            "max_statement_bytes": 1200,
            "module_titles_left_out": ["Practice Tests"],
        },
    }
    sources, claims, counts = build.openstax_lines(
        config, tmp_path, provenance, build.SolverLinks(None, "tool:test")
    )
    assert counts["modules"] == 1 and len(sources) == 1
    assert counts["modules_left_out_by_title"] == ["m2 Practice Tests (1-4) and Final Exams"]
    assert sources[0]["text"].startswith('Source: OpenStax, Fixture Book, module 1: "Motion')
    assert "Licence: https://creativecommons.org/licenses/by/4.0/" in sources[0]["text"]
    assert claims and all(c["source"] == sources[0]["title"] for c in claims)
