import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "benchmark_vault.py"
spec = importlib.util.spec_from_file_location("benchmark_vault", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_small_run_reports_every_figure():
    result = bench.measure(200)
    assert result["notes"] == 200
    assert set(bench.TARGETS) <= set(result)
    assert result["search_p95_ms"] >= result["search_median_ms"] >= 0


def test_regression_over_twenty_percent_fails_and_target_misses_always_fail():
    budgets = {"budgets": {"full_index_s": 10.0, "incremental_s": 0.5}}
    ok = {"full_index_s": 11.9, "incremental_s": 0.5, "peak_rss_mb": 100, "search_p95_ms": 10}
    assert bench.violations(ok, budgets) == []
    slow = dict(ok, full_index_s=12.1)
    assert any("full_index_s" in p and "20 percent" in p for p in bench.violations(slow, budgets))
    miss = dict(ok, peak_rss_mb=600)
    assert any("spec target" in p for p in bench.violations(miss, {}))


def test_recorded_budgets_meet_the_spec_targets():
    import json

    data = json.loads((SCRIPT.parent.parent / "reports/performance/budgets.json").read_text())
    for name, limit in bench.TARGETS.items():
        assert data["budgets"][name] <= limit
    assert data["notes"] == 10000
