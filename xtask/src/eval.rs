//! `cargo xtask eval`: the model-free evaluation runner (SR-H15, T140).
//!
//! One command replays the golden fixtures, the translated Agentic scenarios, the evidence checks, the leak and
//! injection tests and the vault round trips, measures retrieval on the fixture vault and compares everything with
//! `reports/model_free/baseline.json`. Nothing here loads a model, trains, fits or profiles anything: the suites are
//! the workspace's own test targets and a scripted model plays the model, so the result says nothing about the
//! quality of a trained model (the foundation model is NOT QUALIFIED).
//!
//! ```text
//! cargo xtask eval [--out FILE] [--baseline FILE] [--write-baseline] [--seed-regression PERCENT]
//! ```
//!
//! The report has no timestamp, no duration and sorted keys, so two runs of the same code give the same bytes. A
//! figure that is worse than its baseline by the baseline's `tolerancePercent` or more fails the run, and so does
//! any failed test. `--seed-regression P` makes every measured figure P percent worse before the comparison: it is
//! how the runner is shown to catch a regression, and it never writes the default report.

use laris_retrieval::{GraphConfig, GraphRetriever, NoteSearch, evaluate};
use laris_vault::VaultIndex;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

/// Report text that says what the numbers are not.
const MODEL: &str = "none: model-free suites; the foundation model is NOT QUALIFIED";
const DEFAULT_REPORT: &str = "reports/model_free/rust_report.json";
const DEFAULT_BASELINE: &str = "reports/model_free/baseline.json";
/// Tolerance used only when a new baseline is written; afterwards the file is the authority.
const NEW_BASELINE_TOLERANCE: f64 = 20.0;
const EPSILON: f64 = 1e-9;

/// A suite is a name and the test targets (package, target) that make it up.
type Suite = (&'static str, &'static [(&'static str, &'static str)]);

const SUITES: &[Suite] = &[
    (
        "golden",
        &[
            ("laris-protocol", "fixtures"),
            ("laris-protocol", "core"),
            ("laris-vault", "golden"),
            ("laris-vault", "writer_golden"),
            ("laris-retrieval", "golden"),
            ("laris-store", "store"),
        ],
    ),
    (
        "agentic",
        &[("laris-core", "agentic"), ("laris-core", "log")],
    ),
    ("evidence", &[("laris-evidence", "gate")]),
    ("leak", &[("laris-policy", "redact")]),
    (
        "injection",
        &[
            ("laris-policy", "shield"),
            ("laris-policy", "hooks"),
            ("laris-policy", "trust"),
        ],
    ),
    (
        "vault",
        &[("laris-vault", "vault_fs"), ("laris-vault", "writer_fs")],
    ),
    ("retrieval", &[("laris-retrieval", "behaviour")]),
    (
        "sandbox",
        &[
            ("laris-sandbox", "linux"),
            ("laris-sandbox", "pyenv"),
            ("laris-tools", "sandboxed_bash"),
        ],
    ),
    (
        "prompt",
        &[("laris-core", "prompt"), ("laris-policy", "prompted")],
    ),
    (
        "permissions",
        &[
            ("laris-policy", "gate"),
            ("laris-policy", "modes"),
            ("laris-policy", "rules"),
            ("laris-tools", "tools"),
            ("laris-tools", "registry"),
        ],
    ),
];

/// Counts from one `cargo test` run.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Counts {
    pub passed: u64,
    pub failed: u64,
    pub ignored: u64,
}

/// Sums every `test result:` line of a cargo test output. A run with no such line (a build error) counts as one
/// failure, so a suite that did not run cannot pass.
pub fn parse_counts(output: &str) -> Counts {
    let mut total = Counts::default();
    let mut seen = false;
    for line in output.lines() {
        let Some(rest) = line.trim().strip_prefix("test result:") else {
            continue;
        };
        seen = true;
        for part in rest.split(';') {
            let part = part
                .trim()
                .trim_start_matches("ok.")
                .trim_start_matches("FAILED.");
            let mut words = part.split_whitespace();
            let (Some(n), Some(label)) = (words.next(), words.next()) else {
                continue;
            };
            let Ok(n) = n.parse::<u64>() else { continue };
            match label {
                "passed" => total.passed += n,
                "failed" => total.failed += n,
                "ignored" => total.ignored += n,
                _ => {}
            }
        }
    }
    if !seen {
        total.failed += 1;
    }
    total
}

/// How much worse `now` is than `base`, in percent, for a figure where more is better. Zero when there is no baseline
/// to lose.
pub fn worse_percent(base: f64, now: f64) -> f64 {
    if base <= 0.0 {
        0.0
    } else {
        (base - now) / base * 100.0
    }
}

/// True when the figure lost `tolerance` percent or more.
pub fn is_regression(base: f64, now: f64, tolerance: f64) -> bool {
    worse_percent(base, now) >= tolerance - EPSILON
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

fn run_target(root: &Path, package: &str, target: &str) -> Counts {
    let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_owned());
    // One test thread: some suites change the working folder, and a reproducible run must not depend on timing.
    let out = Command::new(cargo)
        .current_dir(root)
        .args(["test", "--quiet", "-p", package, "--test", target, "--"])
        .arg("--test-threads=1")
        .output();
    match out {
        Ok(o) => {
            let text = format!(
                "{}\n{}",
                String::from_utf8_lossy(&o.stdout),
                String::from_utf8_lossy(&o.stderr)
            );
            let counts = parse_counts(&text);
            if o.status.success() {
                counts
            } else {
                Counts {
                    failed: counts.failed.max(1),
                    ..counts
                }
            }
        }
        Err(_) => Counts {
            failed: 1,
            ..Counts::default()
        },
    }
}

fn qrels(path: &Path) -> Result<BTreeMap<String, BTreeSet<String>>, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let value: Value = serde_json::from_str(&text).map_err(|e| format!("qrels: {e}"))?;
    let object = value.as_object().ok_or("qrels is not an object")?;
    Ok(object
        .iter()
        .map(|(q, v)| {
            let relevant = v
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            (q.clone(), relevant)
        })
        .collect())
}

/// Retrieval metrics on the fixture vault: `retrieval.bm25.recall@5` and so on.
fn retrieval_metrics(root: &Path) -> Result<BTreeMap<String, f64>, String> {
    let base = root.join("tests/fixtures/retrieval");
    let queries = qrels(&base.join("qrels.json"))?;
    let index =
        VaultIndex::build(&base.join("vault"), None).map_err(|e| format!("vault: {e:?}"))?;
    let search = NoteSearch::new(&index, &[]);
    let graph = GraphRetriever::new(&index, &[], GraphConfig::default());
    let by_bm25 = evaluate(
        &queries,
        |q| search.search(q, 10).into_iter().map(|h| h.path).collect(),
        5,
    );
    let by_graph = evaluate(
        &queries,
        |q| graph.retrieve(q, 10).into_iter().map(|r| r.path).collect(),
        5,
    );
    let mut out = BTreeMap::new();
    for (name, set) in [("bm25", by_bm25), ("graph", by_graph)] {
        for (key, value) in set {
            out.insert(format!("retrieval.{name}.{key}"), value);
        }
    }
    Ok(out)
}

/// What one run measured: passed test counts per suite and the retrieval figures. Both are "more is better".
struct Measured {
    suites: BTreeMap<String, (Counts, BTreeMap<String, Counts>)>,
    metrics: BTreeMap<String, f64>,
}

fn measure(root: &Path) -> Result<Measured, String> {
    let mut suites = BTreeMap::new();
    for (name, targets) in SUITES {
        let mut sum = Counts::default();
        let mut parts = BTreeMap::new();
        for (package, target) in *targets {
            eprintln!("eval: {name}: {package} {target}");
            let c = run_target(root, package, target);
            sum.passed += c.passed;
            sum.failed += c.failed;
            sum.ignored += c.ignored;
            parts.insert(format!("{package}::{target}"), c);
        }
        suites.insert((*name).to_owned(), (sum, parts));
    }
    Ok(Measured {
        suites,
        metrics: retrieval_metrics(root)?,
    })
}

/// A figure of the run after any seeded regression.
fn seeded(value: f64, percent: f64) -> f64 {
    value * (1.0 - percent / 100.0)
}

/// Compares a measurement with the baseline. Returns the report and whether the run passed.
fn judge(m: &Measured, baseline: &Value, seed: f64) -> (Value, bool) {
    let tolerance = baseline["tolerancePercent"]
        .as_f64()
        .unwrap_or(NEW_BASELINE_TOLERANCE);
    let mut passed = true;
    let mut problems: Vec<String> = Vec::new();
    let mut suites = Map::new();
    for (name, (sum, parts)) in &m.suites {
        let base = baseline["suites"][name]["passed"].as_f64();
        let now = seeded(sum.passed as f64, seed);
        let mut ok = sum.failed == 0;
        if !ok {
            problems.push(format!("suite {name}: {} test(s) failed", sum.failed));
        }
        match base {
            Some(b) if is_regression(b, now, tolerance) => {
                ok = false;
                problems.push(format!(
                    "suite {name}: {now:.1} passed against a baseline of {b} ({:.1} percent worse)",
                    worse_percent(b, now)
                ));
            }
            None => {
                ok = false;
                problems.push(format!("suite {name}: not in the baseline"));
            }
            _ => {}
        }
        passed &= ok;
        let targets: Map<String, Value> = parts
            .iter()
            .map(|(k, c)| (k.clone(), json!({"passed": c.passed, "failed": c.failed})))
            .collect();
        suites.insert(
            name.clone(),
            json!({"passed": sum.passed, "failed": sum.failed, "ok": ok, "targets": targets}),
        );
    }
    let mut metrics = Map::new();
    for (key, value) in &m.metrics {
        let now = seeded(*value, seed);
        let base = baseline["metrics"][key].as_f64();
        let mut ok = true;
        match base {
            Some(b) if is_regression(b, now, tolerance) => {
                ok = false;
                problems.push(format!(
                    "metric {key}: {now:.4} against a baseline of {b} ({:.1} percent worse)",
                    worse_percent(b, now)
                ));
            }
            None => {
                ok = false;
                problems.push(format!("metric {key}: not in the baseline"));
            }
            _ => {}
        }
        passed &= ok;
        metrics.insert(key.clone(), json!({"value": round4(*value), "ok": ok}));
    }
    let report = json!({
        "model": MODEL,
        "passed": passed,
        "tolerancePercent": tolerance,
        "seededRegressionPercent": seed,
        "suites": suites,
        "metrics": metrics,
        "problems": problems,
        "notRun": [
            "benchmarks (budgets are fixed from measurements in T154)",
            "any trained model: scripted model only, so no scientific capability is shown"
        ],
    });
    (report, passed)
}

fn new_baseline(m: &Measured) -> Value {
    let suites: Map<String, Value> = m
        .suites
        .iter()
        .map(|(k, (c, _))| (k.clone(), json!({"passed": c.passed})))
        .collect();
    let metrics: Map<String, Value> = m
        .metrics
        .iter()
        .map(|(k, v)| (k.clone(), json!(round4(*v))))
        .collect();
    json!({
        "note": "figures of the model-free evaluation; a figure that loses tolerancePercent or more fails `cargo xtask eval`",
        "tolerancePercent": NEW_BASELINE_TOLERANCE,
        "suites": suites,
        "metrics": metrics,
    })
}

struct Options {
    out: Option<PathBuf>,
    baseline: PathBuf,
    write_baseline: bool,
    seed: f64,
}

fn parse_args(args: &[String], root: &Path) -> Result<Options, String> {
    let mut o = Options {
        out: None,
        baseline: root.join(DEFAULT_BASELINE),
        write_baseline: false,
        seed: 0.0,
    };
    let mut it = args.iter();
    while let Some(arg) = it.next() {
        let mut value = |name: &str| it.next().cloned().ok_or(format!("{name} needs a value"));
        match arg.as_str() {
            "--out" => o.out = Some(PathBuf::from(value("--out")?)),
            "--baseline" => o.baseline = PathBuf::from(value("--baseline")?),
            "--write-baseline" => o.write_baseline = true,
            "--seed-regression" => {
                let v = value("--seed-regression")?;
                o.seed = v
                    .parse::<f64>()
                    .ok()
                    .filter(|p| (0.0..=100.0).contains(p))
                    .ok_or(format!("--seed-regression: not a percentage: {v}"))?;
            }
            other => return Err(format!("unknown argument {other}")),
        }
    }
    Ok(o)
}

fn dump(value: &Value) -> String {
    let mut text = serde_json::to_string_pretty(value).unwrap_or_default();
    text.push('\n');
    text
}

pub fn run(root: &Path, args: &[String]) -> ExitCode {
    let options = match parse_args(args, root) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("eval: {e}");
            return ExitCode::from(2);
        }
    };
    let measured = match measure(root) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("eval: {e}");
            return ExitCode::FAILURE;
        }
    };
    if options.write_baseline {
        let text = dump(&new_baseline(&measured));
        if let Err(e) = fs::write(&options.baseline, text) {
            eprintln!("eval: {}: {e}", options.baseline.display());
            return ExitCode::FAILURE;
        }
        println!("eval: baseline written to {}", options.baseline.display());
        return ExitCode::SUCCESS;
    }
    let baseline: Value = match fs::read_to_string(&options.baseline)
        .map_err(|e| e.to_string())
        .and_then(|t| serde_json::from_str(&t).map_err(|e| e.to_string()))
    {
        Ok(b) => b,
        Err(e) => {
            eprintln!("eval: baseline {}: {e}", options.baseline.display());
            return ExitCode::FAILURE;
        }
    };
    let (report, passed) = judge(&measured, &baseline, options.seed);
    // A seeded run proves the runner; it must not replace the real report.
    let target = match (&options.out, options.seed > 0.0) {
        (Some(p), _) => Some(p.clone()),
        (None, false) => Some(root.join(DEFAULT_REPORT)),
        (None, true) => None,
    };
    if let Some(path) = target {
        if let Err(e) = fs::write(&path, dump(&report)) {
            eprintln!("eval: {}: {e}", path.display());
            return ExitCode::FAILURE;
        }
        println!("eval: report written to {}", path.display());
    }
    if let Some(list) = report["problems"].as_array() {
        for p in list.iter().filter_map(Value::as_str) {
            println!("eval: FAIL {p}");
        }
    }
    println!("eval: {}", if passed { "passed" } else { "FAILED" });
    if passed {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn measured(passed: u64, recall: f64) -> Measured {
        let counts = Counts {
            passed,
            failed: 0,
            ignored: 0,
        };
        let mut suites = BTreeMap::new();
        suites.insert("golden".to_owned(), (counts, BTreeMap::new()));
        let mut metrics = BTreeMap::new();
        metrics.insert("retrieval.bm25.recall@5".to_owned(), recall);
        Measured { suites, metrics }
    }

    fn baseline() -> Value {
        json!({
            "tolerancePercent": 20.0,
            "suites": {"golden": {"passed": 100}},
            "metrics": {"retrieval.bm25.recall@5": 0.5},
        })
    }

    #[test]
    fn counts_are_summed_over_result_lines() {
        let out = "running 2 tests\ntest result: ok. 2 passed; 0 failed; 1 ignored; 0 measured\n\
                   test result: FAILED. 3 passed; 1 failed; 0 ignored; 0 measured\n";
        assert_eq!(
            parse_counts(out),
            Counts {
                passed: 5,
                failed: 1,
                ignored: 1
            }
        );
    }

    #[test]
    fn a_run_without_a_result_line_is_a_failure() {
        assert_eq!(parse_counts("error[E0432]: unresolved import").failed, 1);
    }

    #[test]
    fn regression_threshold_is_inclusive() {
        assert!(is_regression(100.0, 80.0, 20.0));
        assert!(!is_regression(100.0, 80.5, 20.0));
        assert!(!is_regression(100.0, 120.0, 20.0));
        assert!(!is_regression(0.0, 0.0, 20.0));
    }

    #[test]
    fn the_unmodified_run_passes_and_a_seeded_twenty_percent_fails() {
        let m = measured(100, 0.5);
        assert!(judge(&m, &baseline(), 0.0).1);
        let (report, passed) = judge(&m, &baseline(), 20.0);
        assert!(!passed);
        assert_eq!(report["suites"]["golden"]["ok"], json!(false));
        assert_eq!(
            report["metrics"]["retrieval.bm25.recall@5"]["ok"],
            json!(false)
        );
        assert!(judge(&m, &baseline(), 19.0).1);
    }

    #[test]
    fn a_failed_test_a_lost_test_and_an_unknown_figure_fail() {
        let mut m = measured(100, 0.5);
        m.suites.get_mut("golden").unwrap().0.failed = 1;
        assert!(!judge(&m, &baseline(), 0.0).1);
        assert!(!judge(&measured(79, 0.5), &baseline(), 0.0).1);
        assert!(!judge(&measured(100, 0.3), &baseline(), 0.0).1);
        let mut extra = measured(100, 0.5);
        extra.metrics.insert("retrieval.new".to_owned(), 1.0);
        assert!(!judge(&extra, &baseline(), 0.0).1);
    }

    #[test]
    fn the_report_is_the_same_bytes_each_time() {
        let m = measured(100, 0.5);
        assert_eq!(
            dump(&judge(&m, &baseline(), 0.0).0),
            dump(&judge(&m, &baseline(), 0.0).0)
        );
    }

    #[test]
    fn arguments_are_checked() {
        let root = Path::new("/x");
        assert!(parse_args(&["--seed-regression".into(), "120".into()], root).is_err());
        assert!(parse_args(&["--seed-regression".into(), "20".into()], root).is_ok());
        assert!(parse_args(&["--bogus".into()], root).is_err());
        assert!(parse_args(&["--out".into()], root).is_err());
    }
}
