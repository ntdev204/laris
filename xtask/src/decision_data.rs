//! `cargo xtask decision-data`: builds or checks the decision dataset of the main brain (T168, ADR-024 9.1).
//!
//! ```text
//! cargo xtask decision-data --config FILE --out DIR [--log FILE]... [--date YYYY-MM-DD]
//! cargo xtask decision-data --config FILE --verify DIR
//! ```
//!
//! `FILE` is JSON with `rules` (the `RuleSettings` of the rule decider) and `split` (`validation_pct`, `heldout_pct`
//! and an optional `withheld_advisor`); nothing is defaulted. The dataset holds the examples of the given decision
//! logs, the counterfactual scenario examples and the sealed held-out split. Nothing here fits, trains or scores a
//! model: the command reads logs and writes examples. Output belongs outside Git (`data/`).

use laris_brain::dataset::{
    Excluded, SplitSettings, from_log, scenario_examples, verify as verify_dir, write,
};
use laris_brain::decide::RuleSettings;
use laris_vault::brain::{Level, sha256_hex};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

pub(crate) struct Config {
    pub(crate) rules: RuleSettings,
    pub(crate) split: SplitSettings,
}

pub(crate) fn read_config(path: &Path) -> Result<Config, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
    let r = v.get("rules").ok_or("config: `rules` is missing")?;
    let s = v.get("split").ok_or("config: `split` is missing")?;
    let u = |o: &Value, k: &str| {
        o.get(k)
            .and_then(Value::as_u64)
            .ok_or(format!("config: `{k}` is missing or not a whole number"))
    };
    let level = r
        .get("required_level")
        .and_then(Value::as_str)
        .and_then(Level::parse)
        .ok_or("config: `required_level` is not a certainty level")?;
    Ok(Config {
        rules: RuleSettings {
            required_level: level,
            min_coverage: r
                .get("min_coverage")
                .and_then(Value::as_f64)
                .ok_or("config: `min_coverage` is missing")?,
            max_retrievals: u(r, "max_retrievals")? as u32,
            max_acquisitions: u(r, "max_acquisitions")? as u32,
            max_advisor_asks: u(r, "max_advisor_asks")? as u32,
            max_repeats: u(r, "max_repeats")? as u32,
        },
        split: SplitSettings {
            validation_pct: u(s, "validation_pct")?,
            heldout_pct: u(s, "heldout_pct")?,
            withheld_advisor: s
                .get("withheld_advisor")
                .and_then(Value::as_str)
                .map(str::to_owned),
        },
    })
}

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1).cloned())
}

fn run_inner(args: &[String]) -> Result<ExitCode, String> {
    let config = read_config(Path::new(
        &flag(args, "--config").ok_or("--config FILE is required")?,
    ))?;
    if let Some(dir) = flag(args, "--verify") {
        let problems = verify_dir(Path::new(&dir), &config.split).map_err(|e| e.to_string())?;
        if problems.is_empty() {
            println!("[PASS] {dir}: files, ids, splits and seal agree.");
            return Ok(ExitCode::SUCCESS);
        }
        problems.iter().for_each(|p| eprintln!("[FAIL] {p}"));
        return Ok(ExitCode::FAILURE);
    }
    let out = PathBuf::from(flag(args, "--out").ok_or("--out DIR is required")?);
    let date = flag(args, "--date").ok_or("--date YYYY-MM-DD is required")?;
    let mut examples = scenario_examples(&config.rules);
    let mut inputs = Vec::new();
    let mut left_out: BTreeMap<Excluded, usize> = BTreeMap::new();
    for (i, a) in args.iter().enumerate() {
        if a != "--log" {
            continue;
        }
        let path = args.get(i + 1).ok_or("--log needs a file")?;
        let text = fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
        let (found, excluded) = from_log(&text, path);
        inputs.push((path.clone(), sha256_hex(text.as_bytes())));
        examples.extend(found);
        for (why, n) in excluded {
            *left_out.entry(why).or_insert(0) += n;
        }
    }
    let manifest = write(&out, &examples, &config.split, &inputs, &left_out, &date)
        .map_err(|e| e.to_string())?;
    println!(
        "wrote {} examples to {}; manifest and seal are next to them",
        examples.len(),
        out.display()
    );
    println!("{}", manifest.0["splits"]);
    Ok(ExitCode::SUCCESS)
}

/// Runs the command.
pub fn run(args: &[String]) -> ExitCode {
    match run_inner(args) {
        Ok(code) => code,
        Err(message) => {
            eprintln!("decision-data: {message}");
            ExitCode::from(2)
        }
    }
}
