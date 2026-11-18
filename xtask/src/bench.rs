//! `cargo xtask bench`: the performance budgets of the system (SR-H15, T154).
//!
//! Two release programs measure the system without a model: the server benchmark (`laris-server --example server_bench`: HTTP,
//! streaming, the redactor and the evidence gate, against a scripted backend) and the retrieval benchmark
//! (`laris-retrieval --example bench`: a 10,000-note vault). Each runs `--runs` times; a figure is the median of the
//! runs. A budget is fixed from measurements: the worst run times a headroom factor, never below a floor for its unit,
//! and never above the target of the specification. The check fails when a figure is above its budget.
//!
//! ```text
//! cargo xtask bench [--runs N] [--out FILE] [--budgets FILE] [--write-budgets] [--seed-slowdown FACTOR]
//! ```
//!
//! Budgets are for the machine the figures were taken on (`reports/performance/README` of the report says which);
//! a slower runner may need `--write-budgets` on its own measurements, as the owner decides. The figures are the
//! cost of the system around a model: nothing here says anything about a model's quality or speed.

use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

const DEFAULT_REPORT: &str = "reports/performance/rust_bench.json";
const DEFAULT_BUDGETS: &str = "reports/performance/rust_budgets.json";
const HEADROOM: f64 = 3.0;
const DEFAULT_RUNS: usize = 5;

/// Targets of the specification that a budget may never exceed: (figure, limit).
const SPEC_LIMITS: &[(&str, f64)] = &[
    ("retrieval.bm25_p95_ms", 300.0),
    ("retrieval.graph_p95_ms", 300.0),
    ("retrieval.index_build_s", 30.0),
];

/// The smallest budget a unit may get: below it, scheduling noise on a shared runner is the measurement.
pub fn floor_of(key: &str) -> f64 {
    if key.ends_with("_ms") {
        2.0
    } else if key.ends_with("_s") {
        1.0
    } else {
        32.0 // megabytes
    }
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

/// A budget from the worst measured run: headroom, floor, specification limit.
pub fn budget_from(key: &str, worst: f64) -> f64 {
    let wanted = (worst * HEADROOM).max(floor_of(key));
    let limit = SPEC_LIMITS
        .iter()
        .find(|(k, _)| *k == key)
        .map_or(f64::INFINITY, |(_, l)| *l);
    round3(wanted.min(limit))
}

pub fn median(values: &mut [f64]) -> f64 {
    values.sort_by(f64::total_cmp);
    match values.len() {
        0 => 0.0,
        n if n % 2 == 1 => values[n / 2],
        n => (values[n / 2 - 1] + values[n / 2]) / 2.0,
    }
}

/// Figures per key over the runs: (median, worst).
pub type Figures = BTreeMap<String, Vec<f64>>;

fn summarise(figures: &Figures) -> BTreeMap<String, (f64, f64)> {
    figures
        .iter()
        .map(|(k, v)| {
            let mut sorted = v.clone();
            let worst = sorted.iter().copied().fold(0.0, f64::max);
            (k.clone(), (median(&mut sorted), worst))
        })
        .collect()
}

/// Judges the medians against the budgets, after a seeded slowdown. Returns the per-figure report and the problems.
pub fn judge(
    summary: &BTreeMap<String, (f64, f64)>,
    budgets: &Value,
    slowdown: f64,
) -> (Value, Vec<String>) {
    let mut problems = Vec::new();
    let mut figures = Map::new();
    for (key, (med, worst)) in summary {
        let now = med * slowdown;
        let budget = budgets["budgets"][key]["budget"].as_f64();
        let ok = match budget {
            Some(b) if now > b => {
                problems.push(format!("{key}: {now:.3} is over its budget of {b}"));
                false
            }
            None => {
                problems.push(format!("{key}: not in the budgets"));
                false
            }
            _ => true,
        };
        figures.insert(
            key.clone(),
            json!({"median": round3(*med), "worst": round3(*worst), "budget": budget, "ok": ok}),
        );
    }
    if let Some(map) = budgets["budgets"].as_object() {
        for key in map.keys().filter(|k| !summary.contains_key(*k)) {
            problems.push(format!("{key}: budget without a measured figure"));
        }
    }
    (Value::Object(figures), problems)
}

pub fn new_budgets(summary: &BTreeMap<String, (f64, f64)>, runs: usize) -> Value {
    let budgets: Map<String, Value> = summary
        .iter()
        .map(|(k, (med, worst))| {
            (
                k.clone(),
                json!({"budget": budget_from(k, *worst), "measuredMedian": round3(*med), "measuredWorst": round3(*worst)}),
            )
        })
        .collect();
    json!({
        "note": "budgets fixed from measurements (T154): the worst of the runs times the headroom, never below the floor of its unit and never above the target of the specification; `cargo xtask bench` fails when a median is over its budget",
        "headroomFactor": HEADROOM,
        "runs": runs,
        "floors": {"_ms": 2.0, "_s": 1.0, "_mb": 32.0},
        "budgets": budgets,
    })
}

fn cargo() -> String {
    std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_owned())
}

fn build(root: &Path) -> Result<(), String> {
    for (package, example) in [
        ("laris-server", "server_bench"),
        ("laris-retrieval", "bench"),
    ] {
        let status = Command::new(cargo())
            .current_dir(root)
            .args([
                "build",
                "--release",
                "--offline",
                "--locked",
                "-p",
                package,
                "--example",
                example,
            ])
            .status()
            .map_err(|e| e.to_string())?;
        if !status.success() {
            return Err(format!("{package} --example {example} did not build"));
        }
    }
    Ok(())
}

fn target_dir(root: &Path) -> PathBuf {
    std::env::var_os("CARGO_TARGET_DIR").map_or_else(|| root.join("target"), PathBuf::from)
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn execute(program: &Path, out: &Path) -> Result<Value, String> {
    let status = Command::new(program)
        .arg("--out")
        .arg(out)
        .status()
        .map_err(|e| format!("{}: {e}", program.display()))?;
    if !status.success() {
        return Err(format!("{} failed", program.display()));
    }
    read_json(out)
}

/// Runs both programs `runs` times and collects every figure.
fn measure(root: &Path, runs: usize) -> Result<Figures, String> {
    build(root)?;
    let bin = target_dir(root).join("release/examples");
    let scratch = std::env::temp_dir().join(format!("laris-bench-{}", std::process::id()));
    fs::create_dir_all(&scratch).map_err(|e| e.to_string())?;
    let mut figures = Figures::new();
    for i in 0..runs {
        eprintln!("bench: run {}/{runs}", i + 1);
        let server = execute(&bin.join("server_bench"), &scratch.join("server.json"))?;
        for (k, v) in server["figures"].as_object().into_iter().flatten() {
            if let Some(x) = v.as_f64() {
                figures.entry(k.clone()).or_default().push(x);
            }
        }
        let retrieval = execute(&bin.join("bench"), &scratch.join("retrieval.json"))?;
        for key in [
            "bm25_p95_ms",
            "graph_p95_ms",
            "index_build_s",
            "search_build_s",
        ] {
            if let Some(x) = retrieval[key].as_f64() {
                figures
                    .entry(format!("retrieval.{key}"))
                    .or_default()
                    .push(x);
            }
        }
    }
    let _ = fs::remove_dir_all(&scratch);
    Ok(figures)
}

struct Options {
    runs: usize,
    out: Option<PathBuf>,
    budgets: Option<PathBuf>,
    write_budgets: bool,
    slowdown: f64,
}

fn parse_args(args: &[String]) -> Result<Options, String> {
    let mut o = Options {
        runs: DEFAULT_RUNS,
        out: None,
        budgets: None,
        write_budgets: false,
        slowdown: 1.0,
    };
    let mut it = args.iter();
    while let Some(arg) = it.next() {
        let mut value = |name: &str| it.next().cloned().ok_or(format!("{name} needs a value"));
        match arg.as_str() {
            "--runs" => {
                let v = value("--runs")?;
                o.runs = v
                    .parse::<usize>()
                    .ok()
                    .filter(|n| (1..=50).contains(n))
                    .ok_or(format!("--runs: not a count of 1 to 50: {v}"))?;
            }
            "--out" => o.out = Some(PathBuf::from(value("--out")?)),
            "--budgets" => o.budgets = Some(PathBuf::from(value("--budgets")?)),
            "--write-budgets" => o.write_budgets = true,
            "--seed-slowdown" => {
                let v = value("--seed-slowdown")?;
                o.slowdown = v
                    .parse::<f64>()
                    .ok()
                    .filter(|f| *f >= 1.0 && f.is_finite())
                    .ok_or(format!("--seed-slowdown: not a factor of 1 or more: {v}"))?;
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
    let options = match parse_args(args) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("bench: {e}");
            return ExitCode::from(2);
        }
    };
    let figures = match measure(root, options.runs) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("bench: {e}");
            return ExitCode::FAILURE;
        }
    };
    let summary = summarise(&figures);
    let budgets_path = options
        .budgets
        .unwrap_or_else(|| root.join(DEFAULT_BUDGETS));
    if options.write_budgets {
        if let Err(e) = fs::write(&budgets_path, dump(&new_budgets(&summary, options.runs))) {
            eprintln!("bench: {}: {e}", budgets_path.display());
            return ExitCode::FAILURE;
        }
        println!("bench: budgets written to {}", budgets_path.display());
        return ExitCode::SUCCESS;
    }
    let budgets = match read_json(&budgets_path) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("bench: {e}");
            return ExitCode::FAILURE;
        }
    };
    let (report_figures, problems) = judge(&summary, &budgets, options.slowdown);
    let passed = problems.is_empty();
    let report = json!({
        "backend": "scripted backend in one process and a generated 10,000-note vault; the cost of the system around a model, never of a model",
        "model": "none: the foundation model is NOT QUALIFIED",
        "passed": passed,
        "runs": options.runs,
        "seededSlowdown": options.slowdown,
        "figures": report_figures,
        "problems": problems,
    });
    // A seeded run proves the check; it must not replace the real report.
    let target = match (&options.out, options.slowdown > 1.0) {
        (Some(p), _) => Some(p.clone()),
        (None, false) => Some(root.join(DEFAULT_REPORT)),
        (None, true) => None,
    };
    if let Some(path) = target {
        if let Err(e) = fs::write(&path, dump(&report)) {
            eprintln!("bench: {}: {e}", path.display());
            return ExitCode::FAILURE;
        }
        println!("bench: report written to {}", path.display());
    }
    for p in report["problems"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        println!("bench: FAIL {p}");
    }
    println!("bench: {}", if passed { "passed" } else { "FAILED" });
    if passed {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn summary(value: f64) -> BTreeMap<String, (f64, f64)> {
        [("server.chat_p95_ms".to_owned(), (value, value))]
            .into_iter()
            .collect()
    }

    #[test]
    fn a_budget_has_headroom_a_floor_and_a_specification_limit() {
        assert_eq!(budget_from("server.chat_p95_ms", 0.08), 2.0);
        assert_eq!(budget_from("server.chat_parallel_p95_ms", 30.0), 90.0);
        assert_eq!(budget_from("process.peak_rss_mb", 9.6), 32.0);
        assert_eq!(budget_from("retrieval.bm25_p95_ms", 200.0), 300.0);
        assert_eq!(budget_from("retrieval.index_build_s", 0.2), 1.0);
    }

    #[test]
    fn the_median_ignores_one_slow_run() {
        assert_eq!(median(&mut [1.0, 1.1, 50.0]), 1.1);
        assert_eq!(median(&mut [1.0, 2.0]), 1.5);
        assert_eq!(median(&mut []), 0.0);
    }

    #[test]
    fn a_figure_over_its_budget_a_missing_budget_and_a_stale_budget_fail() {
        let budgets = new_budgets(&summary(0.08), 5);
        assert!(judge(&summary(0.08), &budgets, 1.0).1.is_empty());
        // a seeded slowdown that passes the headroom fails
        assert!(!judge(&summary(0.08), &budgets, 30.0).1.is_empty());
        let mut other = summary(0.08);
        other.insert("server.new_ms".into(), (1.0, 1.0));
        assert!(
            judge(&other, &budgets, 1.0)
                .1
                .iter()
                .any(|p| p.contains("not in the budgets"))
        );
        let mut gone = budgets.clone();
        gone["budgets"]["server.old_ms"] = json!({"budget": 1.0});
        assert!(
            judge(&summary(0.08), &gone, 1.0)
                .1
                .iter()
                .any(|p| p.contains("without a measured figure"))
        );
    }

    #[test]
    fn arguments_are_checked() {
        assert!(parse_args(&["--runs".into(), "0".into()]).is_err());
        assert!(parse_args(&["--seed-slowdown".into(), "0.5".into()]).is_err());
        assert!(parse_args(&["--runs".into(), "3".into(), "--write-budgets".into()]).is_ok());
        assert!(parse_args(&["--bogus".into()]).is_err());
    }
}
