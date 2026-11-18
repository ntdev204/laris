//! `cargo xtask security`: the security suite of the threat model (SR-G5, T154).
//!
//! `docs/architecture/THREAT_MODEL.md` gives every threat a test id; `tests/security/suite.json` names, per id, the
//! tests that exercise it (exact test names, so a renamed or deleted test breaks the suite) and any command. The suite
//! fails when
//!
//! - a threat row has no entry, or an entry has no threat row;
//! - a named test does not exist, does not pass, or was skipped (a PostgreSQL test without a database is `not_run`,
//!   never a pass);
//! - an entry is `deferred` to a task that is already done, or to a task that does not own the row.
//!
//! An entry with a `partial` note passes but is reported as partial; a deferred entry is reported as deferred. The
//! report (`reports/security/report.json`) has no timestamp and sorted keys. Nothing here loads a model or trains.
//!
//! ```text
//! cargo xtask security [--out FILE] [--only SEC-ID] [--check-manifest] [--without-postgres]
//! ```

use regex::Regex;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

const MANIFEST: &str = "tests/security/suite.json";
const THREATS: &str = "docs/architecture/THREAT_MODEL.md";
const DEFAULT_REPORT: &str = "reports/security/report.json";
const SKIP_NOTICE: &str = "PostgreSQL test skipped";

/// One threat row: its id, the tasks that own it and its test id.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Row {
    pub threat: String,
    pub tasks: Vec<String>,
    pub test: String,
}

/// Reads the threat table of the threat model.
pub fn threat_rows(text: &str) -> Vec<Row> {
    let row =
        Regex::new(r"^\|\s*(TM-\d+)\s*\|.*\|\s*(SEC-[A-Z]+-\d+)\s*\|\s*$").expect("static regex");
    let task = Regex::new(r"T\d+").expect("static regex");
    text.lines()
        .filter_map(|line| {
            let caps = row.captures(line.trim())?;
            let cells: Vec<&str> = line.trim().trim_matches('|').split('|').collect();
            // threat, attackers, control, requirement, tasks, test: the task cell is the one before the test id.
            let tasks_cell = cells
                .get(cells.len().saturating_sub(2))
                .copied()
                .unwrap_or("");
            Some(Row {
                threat: caps[1].to_owned(),
                tasks: task
                    .find_iter(tasks_cell)
                    .map(|m| m.as_str().to_owned())
                    .collect(),
                test: caps[2].to_owned(),
            })
        })
        .collect()
}

/// Task id -> status, from the task files of the ledger.
pub fn task_statuses(root: &Path) -> BTreeMap<String, String> {
    let heading = Regex::new(r"^### (T\d+) — ").expect("static regex");
    let status = Regex::new(r"^- Status: *(\w+)").expect("static regex");
    let mut out = BTreeMap::new();
    let Ok(dir) = fs::read_dir(root.join(".claude/spec/task")) else {
        return out;
    };
    for entry in dir.flatten() {
        let Ok(text) = fs::read_to_string(entry.path()) else {
            continue;
        };
        let mut current: Option<String> = None;
        for line in text.lines() {
            if let Some(c) = heading.captures(line) {
                current = Some(c[1].to_owned());
            } else if let (Some(id), Some(c)) = (&current, status.captures(line)) {
                out.insert(id.clone(), c[1].to_owned());
            }
        }
    }
    out
}

/// Problems with the manifest itself: coverage both ways, deferral rules, shape.
pub fn manifest_problems(
    rows: &[Row],
    manifest: &Value,
    statuses: &BTreeMap<String, String>,
) -> Vec<String> {
    let mut problems = Vec::new();
    let entries = manifest["tests"].as_object().cloned().unwrap_or_default();
    let mut listed = BTreeSet::new();
    for row in rows {
        if !listed.insert(row.test.clone()) {
            problems.push(format!("{}: test id used by two threats", row.test));
        }
        let Some(entry) = entries.get(&row.test) else {
            problems.push(format!(
                "{}: threat {} has no entry in {MANIFEST}",
                row.test, row.threat
            ));
            continue;
        };
        let has = |k: &str| entry.get(k).is_some();
        if !(has("runs") || has("commands") || has("deferred")) {
            problems.push(format!("{}: the entry names no test", row.test));
        }
        if let Some(d) = entry.get("deferred") {
            let task = d["task"].as_str().unwrap_or("");
            if !row.tasks.iter().any(|t| t == task) {
                problems.push(format!(
                    "{}: deferred to {task}, which does not own {}",
                    row.test, row.threat
                ));
            }
            match statuses.get(task).map(String::as_str) {
                Some("done") => problems.push(format!(
                    "{}: deferred to {task}, which is already done: the test must exist",
                    row.test
                )),
                None => problems.push(format!("{}: deferred to unknown task {task}", row.test)),
                _ => {}
            }
            if d["reason"].as_str().is_none_or(str::is_empty) {
                problems.push(format!("{}: a deferral needs a reason", row.test));
            }
            if has("runs") || has("commands") {
                problems.push(format!("{}: deferred entries name no test", row.test));
            }
        }
        if let Some(runs) = entry.get("runs").and_then(Value::as_array) {
            for run in runs {
                let ok = run["package"].is_string()
                    && run["target"].is_string()
                    && run["tests"]
                        .as_array()
                        .is_some_and(|t| !t.is_empty() && t.iter().all(Value::is_string));
                if !ok {
                    problems.push(format!(
                        "{}: a run needs package, target and tests",
                        row.test
                    ));
                }
            }
        }
    }
    for id in entries.keys() {
        if !listed.contains(id) {
            problems.push(format!("{id}: entry without a threat row"));
        }
    }
    problems
}

/// Sums the `test result:` lines of one cargo test output: (passed, failed).
pub fn result_counts(output: &str) -> Option<(u64, u64)> {
    let mut seen = false;
    let (mut passed, mut failed) = (0, 0);
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
                "passed" => passed += n,
                "failed" => failed += n,
                _ => {}
            }
        }
    }
    seen.then_some((passed, failed))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Outcome {
    Passed,
    Failed,
    NotRun,
}

fn cargo() -> String {
    std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_owned())
}

/// Runs the exact tests of one run entry.
fn run_tests(root: &Path, run: &Value, postgres: bool) -> (Outcome, String) {
    let package = run["package"].as_str().unwrap_or("");
    let target = run["target"].as_str().unwrap_or("");
    let names: Vec<&str> = run["tests"]
        .as_array()
        .map(|a| a.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();
    let needs_postgres = run["needs"].as_str() == Some("postgres");
    let label = format!("{package}::{target} ({} tests)", names.len());
    if needs_postgres && !postgres {
        return (
            Outcome::NotRun,
            format!("{label}: needs PostgreSQL (LARIS_TEST_PG_DSN)"),
        );
    }
    eprintln!("security: {package} {target}");
    let out = Command::new(cargo())
        .current_dir(root)
        .args(["test", "--quiet", "-p", package, "--test", target, "--"])
        .args(["--exact", "--test-threads=1"])
        .args(&names)
        .output();
    let Ok(out) = out else {
        return (Outcome::Failed, format!("{label}: cargo did not start"));
    };
    let text = format!(
        "{}\n{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    if needs_postgres && text.contains(SKIP_NOTICE) {
        return (
            Outcome::NotRun,
            format!("{label}: the database tests were skipped"),
        );
    }
    match result_counts(&text) {
        Some((passed, 0)) if out.status.success() && passed == names.len() as u64 => {
            (Outcome::Passed, label)
        }
        Some((passed, failed)) => (
            Outcome::Failed,
            format!(
                "{label}: {passed} passed, {failed} failed of {} named (a missing name shows as fewer passed)",
                names.len()
            ),
        ),
        None => (Outcome::Failed, format!("{label}: the target did not run")),
    }
}

fn run_command(root: &Path, argv: &[&str]) -> (Outcome, String) {
    let label = argv.join(" ");
    let Some((program, args)) = argv.split_first() else {
        return (Outcome::Failed, "empty command".to_owned());
    };
    let program = if *program == "cargo" {
        cargo()
    } else {
        (*program).to_owned()
    };
    eprintln!("security: {label}");
    match Command::new(program).current_dir(root).args(args).output() {
        Ok(o) if o.status.success() => (Outcome::Passed, label),
        Ok(o) => (
            Outcome::Failed,
            format!("{label}: exit {}", o.status.code().unwrap_or(-1)),
        ),
        Err(e) => (Outcome::NotRun, format!("{label}: {e}")),
    }
}

/// One entry's verdict: `passed`, `partial`, `deferred`, `failed` or `not_run`, and what ran.
fn judge_entry(root: &Path, entry: &Value, postgres: bool) -> (&'static str, Vec<String>) {
    if entry.get("deferred").is_some() {
        return ("deferred", Vec::new());
    }
    let mut outcomes = Vec::new();
    for run in entry["runs"].as_array().into_iter().flatten() {
        outcomes.push(run_tests(root, run, postgres));
    }
    for cmd in entry["commands"].as_array().into_iter().flatten() {
        let argv: Vec<&str> = cmd
            .as_array()
            .map(|a| a.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        outcomes.push(run_command(root, &argv));
    }
    let notes: Vec<String> = outcomes.iter().map(|(_, n)| n.clone()).collect();
    let status = if outcomes.iter().any(|(o, _)| *o == Outcome::Failed) {
        "failed"
    } else if outcomes.iter().any(|(o, _)| *o == Outcome::NotRun) {
        "not_run"
    } else if entry.get("partial").is_some() {
        "partial"
    } else {
        "passed"
    };
    (status, notes)
}

struct Options {
    out: Option<PathBuf>,
    only: Option<String>,
    check_manifest: bool,
    without_postgres: bool,
}

fn parse_args(args: &[String]) -> Result<Options, String> {
    let mut o = Options {
        out: None,
        only: None,
        check_manifest: false,
        without_postgres: false,
    };
    let mut it = args.iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--out" => o.out = Some(PathBuf::from(it.next().ok_or("--out needs a value")?)),
            "--only" => o.only = Some(it.next().ok_or("--only needs a value")?.clone()),
            "--check-manifest" => o.check_manifest = true,
            "--without-postgres" => o.without_postgres = true,
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
            eprintln!("security: {e}");
            return ExitCode::from(2);
        }
    };
    let read = |rel: &str| fs::read_to_string(root.join(rel)).map_err(|e| format!("{rel}: {e}"));
    let loaded = read(THREATS).and_then(|t| {
        let m = read(MANIFEST)?;
        let m: Value = serde_json::from_str(&m).map_err(|e| format!("{MANIFEST}: {e}"))?;
        Ok((threat_rows(&t), m))
    });
    let (rows, manifest) = match loaded {
        Ok(v) => v,
        Err(e) => {
            eprintln!("security: {e}");
            return ExitCode::FAILURE;
        }
    };
    let statuses = task_statuses(root);
    let mut problems = manifest_problems(&rows, &manifest, &statuses);
    if rows.is_empty() {
        problems.push(format!("{THREATS}: no threat rows found"));
    }
    if options.check_manifest {
        for p in &problems {
            println!("security: FAIL {p}");
        }
        println!(
            "security: manifest {} ({} threats)",
            if problems.is_empty() {
                "complete"
            } else {
                "INCOMPLETE"
            },
            rows.len()
        );
        return if problems.is_empty() {
            ExitCode::SUCCESS
        } else {
            ExitCode::FAILURE
        };
    }
    let postgres = std::env::var("LARIS_TEST_PG_DSN").is_ok_and(|v| !v.trim().is_empty());
    let mut results = Map::new();
    let mut counts: BTreeMap<&str, u64> = BTreeMap::new();
    let entries = manifest["tests"].as_object().cloned().unwrap_or_default();
    for row in &rows {
        if options.only.as_ref().is_some_and(|o| o != &row.test) {
            continue;
        }
        let Some(entry) = entries.get(&row.test) else {
            continue;
        };
        let (status, notes) = judge_entry(root, entry, postgres);
        *counts.entry(status).or_default() += 1;
        let mut item = json!({
            "threat": row.threat,
            "status": status,
            "owners": row.tasks,
            "ran": notes,
        });
        if let Some(d) = entry.get("deferred") {
            item["deferredTo"] = d.clone();
        }
        if let Some(p) = entry.get("partial") {
            item["partial"] = p.clone();
        }
        if let Some(p) = entry.get("platform") {
            item["platform"] = p.clone();
        }
        if let Some(p) = entry.get("image_check") {
            item["imageCheck"] = p.clone();
        }
        results.insert(row.test.clone(), item);
    }
    let failed = counts.get("failed").copied().unwrap_or(0);
    let not_run = counts.get("not_run").copied().unwrap_or(0);
    let allowed_not_run = options.without_postgres;
    let passed = problems.is_empty() && failed == 0 && (not_run == 0 || allowed_not_run);
    let complete = passed
        && counts.get("deferred").copied().unwrap_or(0) == 0
        && counts.get("partial").copied().unwrap_or(0) == 0
        && not_run == 0
        && options.only.is_none();
    let report = json!({
        "model": "none: the suite runs the workspace tests; the foundation model is NOT QUALIFIED",
        "passed": passed,
        "complete": complete,
        "threats": rows.len(),
        "counts": counts,
        "problems": problems,
        "results": results,
        "notRun": [
            "docker/verify-images.sh and docker/smoke_test.sh (they need built images; the owner or T153's smoke run does it)",
            "the macOS and Windows sandbox backends (their own platforms)",
        ],
    });
    if options.only.is_none() {
        let target = options.out.unwrap_or_else(|| root.join(DEFAULT_REPORT));
        if let Some(dir) = target.parent() {
            let _ = fs::create_dir_all(dir);
        }
        if let Err(e) = fs::write(&target, dump(&report)) {
            eprintln!("security: {}: {e}", target.display());
            return ExitCode::FAILURE;
        }
        println!("security: report written to {}", target.display());
    }
    for p in report["problems"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        println!("security: FAIL {p}");
    }
    for (id, item) in &results {
        let status = item["status"].as_str().unwrap_or("");
        if matches!(status, "failed" | "not_run") {
            println!("security: {status} {id}");
            for n in item["ran"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
            {
                println!("security:   {n}");
            }
        }
    }
    println!(
        "security: {} ({} threats: {})",
        if passed { "passed" } else { "FAILED" },
        rows.len(),
        counts
            .iter()
            .map(|(k, v)| format!("{v} {k}"))
            .collect::<Vec<_>>()
            .join(", ")
    );
    if passed {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TABLE: &str = "\
| TM-01 | Leak | X8 | Control | SR-S4 | T146 | SEC-LEAK-01 |
| TM-02 | Other | X8, X2 | Control two | SR-S4, SR-S5 | T146, T153 | SEC-DEP-01 |
| not a row |
";

    fn statuses() -> BTreeMap<String, String> {
        [("T146", "done"), ("T164", "pending"), ("T153", "pending")]
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect()
    }

    fn manifest() -> Value {
        json!({"tests": {
            "SEC-LEAK-01": {"runs": [{"package": "p", "target": "t", "tests": ["a"]}]},
            "SEC-DEP-01": {"deferred": {"task": "T153", "reason": "later"}},
        }})
    }

    #[test]
    fn rows_carry_their_tasks_and_test_ids() {
        let rows = threat_rows(TABLE);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[1].tasks, vec!["T146", "T153"]);
        assert_eq!(rows[1].test, "SEC-DEP-01");
    }

    #[test]
    fn a_complete_manifest_has_no_problems() {
        assert!(manifest_problems(&threat_rows(TABLE), &manifest(), &statuses()).is_empty());
    }

    #[test]
    fn a_threat_without_an_entry_and_an_entry_without_a_threat_fail() {
        let rows = threat_rows(TABLE);
        let mut m = manifest();
        m["tests"].as_object_mut().unwrap().remove("SEC-LEAK-01");
        assert!(
            manifest_problems(&rows, &m, &statuses())
                .iter()
                .any(|p| p.starts_with("SEC-LEAK-01: threat TM-01 has no entry"))
        );
        let mut m = manifest();
        m["tests"]["SEC-EXTRA-01"] = json!({"runs": []});
        assert!(
            manifest_problems(&rows, &m, &statuses())
                .iter()
                .any(|p| p.contains("SEC-EXTRA-01: entry without a threat row"))
        );
    }

    #[test]
    fn a_deferral_to_a_finished_or_foreign_task_fails() {
        let rows = threat_rows(TABLE);
        let mut done = statuses();
        done.insert("T153".into(), "done".into());
        assert!(
            manifest_problems(&rows, &manifest(), &done)
                .iter()
                .any(|p| p.contains("already done"))
        );
        let mut m = manifest();
        m["tests"]["SEC-DEP-01"]["deferred"]["task"] = json!("T164");
        assert!(
            manifest_problems(&rows, &m, &statuses())
                .iter()
                .any(|p| p.contains("does not own"))
        );
    }

    #[test]
    fn counts_need_a_result_line() {
        assert_eq!(
            result_counts(
                "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out"
            ),
            Some((3, 0))
        );
        assert_eq!(result_counts("error[E0432]: unresolved import"), None);
    }

    #[test]
    fn arguments_are_checked() {
        assert!(parse_args(&["--only".into()]).is_err());
        assert!(parse_args(&["--bogus".into()]).is_err());
        assert!(parse_args(&["--check-manifest".into(), "--without-postgres".into()]).is_ok());
    }
}
