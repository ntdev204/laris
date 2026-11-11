import json
import shutil
from pathlib import Path

from cli.main import main
from evaluation import suite

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "tests" / "fixtures"


def test_all_suites_pass_and_the_report_is_reproducible():
    first = suite.run(FIX, REPO, list(suite.ALL))
    second = suite.run(FIX, REPO, list(suite.ALL))
    assert suite.dumps(first) == suite.dumps(second)
    assert first["passed"] and set(first["suites"]) == set(suite.ALL)
    assert "NOT QUALIFIED" in first["model"]
    s = first["suites"]
    assert s["retrieval"]["graph"]["recall@5"] > s["retrieval"]["bm25"]["recall@5"]
    assert s["citation"]["precision"] == s["citation"]["recall"] == 1.0
    assert s["injection"]["false_positive_rate"] == 0.0 and s["injection"]["recall"] == 1.0
    assert s["leak"]["truncated"] is False and not s["leak"]["false_positive_on_unrelated_text"]
    assert all(s["vault"]["checks"].values())


def test_command_runs_the_fast_subset_and_writes_the_report(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    out = tmp_path / "reports" / "model_free.json"
    assert main(["evaluate", "suite", "--fast", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert set(data["suites"]) == set(suite.FAST) and data["passed"]
    assert main(["evaluate", "suite", "--only", "nonsense"]) == 2


def test_a_seeded_regression_makes_the_command_fail(tmp_path, monkeypatch):
    fixtures = tmp_path / "fx"
    shutil.copytree(FIX, fixtures)
    gold = json.loads((fixtures / "scholarly" / "citations.json").read_text())
    gold["gold_edges"].append(["D2", "D4"])  # an edge that does not exist
    (fixtures / "scholarly" / "citations.json").write_text(json.dumps(gold))
    monkeypatch.chdir(REPO)
    assert main(["evaluate", "suite", "--fast", "--fixtures", str(fixtures)]) == 1
