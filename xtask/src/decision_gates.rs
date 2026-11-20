//! `cargo xtask decision-gates`: measures the held-out gates N1 to N8 of the decision network (T171, ADR-024 8).
//!
//! ```text
//! cargo xtask decision-gates --dataset DIR --dataset-config FILE --net FILE --gates FILE --out REPORT.json
//!                            [--scores-out FILE] [--parity FILE]
//! ```
//!
//! It verifies the dataset seal, reads the sealed held-out split (and the withheld-advisor split when the dataset has
//! one), scores the exported network and the rule decider on it and writes the report. `--scores-out` writes the Rust
//! score of every held-out example for `scripts/decision_net_parity.py` (gate N6), whose result is passed back with
//! `--parity`. Nothing here fits, trains or tunes: it reads a network and scores. Exit status 0 when every gate
//! passes, 1 otherwise; a pass is a measurement, the promotion is the owner's decision.

use laris_brain::dataset::{Split, read_split, verify};
use laris_brain::decide::RuleDecider;
use laris_brain::gates::{Inputs, Limits, Status, evaluate, states};
use laris_brain::network::{Network, NetworkChooser};
use laris_vault::brain::sha256_hex;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::ExitCode;

use crate::decision_data::read_config;

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1).cloned())
}

fn need(args: &[String], name: &str) -> Result<String, String> {
    flag(args, name).ok_or(format!("{name} is required"))
}

fn json_file(path: &str) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    serde_json::from_str(&text).map_err(|e| format!("{path}: {e}"))
}

fn limits(path: &str) -> Result<Limits, String> {
    let v = json_file(path)?;
    let f = |k: &str| {
        v.get(k)
            .and_then(Value::as_f64)
            .ok_or(format!("{path}: `{k}` is missing or not a number"))
    };
    let u = |k: &str| {
        v.get(k)
            .and_then(Value::as_u64)
            .ok_or(format!("{path}: `{k}` is missing or not a whole number"))
    };
    Ok(Limits {
        min_gain_points: f("min_gain_points")?,
        confidence_pct: f("confidence_pct")?,
        bootstrap_resamples: u("bootstrap_resamples")? as usize,
        bootstrap_seed: u("bootstrap_seed")?,
        max_unsupported_rate: f("max_unsupported_rate")?,
        max_ece: f("max_ece")?,
        ece_bins: u("ece_bins")? as usize,
        min_abstain_recall: f("min_abstain_recall")?,
        max_overabstain_margin_points: f("max_overabstain_margin_points")?,
        max_parity_diff: f("max_parity_diff")?,
        max_p95_ms: f("max_p95_ms")?,
        latency_repeats: u("latency_repeats")? as usize,
    })
}

fn cpu_model() -> String {
    fs::read_to_string("/proc/cpuinfo")
        .ok()
        .and_then(|t| {
            t.lines()
                .find(|l| l.starts_with("model name"))
                .and_then(|l| l.split(':').nth(1))
                .map(|m| m.trim().to_owned())
        })
        .unwrap_or_else(|| "unknown".to_owned())
}

fn digest(path: &str) -> Result<String, String> {
    fs::read(path)
        .map(|b| sha256_hex(&b))
        .map_err(|e| format!("{path}: {e}"))
}

fn run_inner(args: &[String]) -> Result<ExitCode, String> {
    let dataset = need(args, "--dataset")?;
    let config_path = need(args, "--dataset-config")?;
    let net_path = need(args, "--net")?;
    let gates_path = need(args, "--gates")?;
    let out = need(args, "--out")?;
    let config = read_config(Path::new(&config_path))?;
    let limits = limits(&gates_path)?;
    let dir = Path::new(&dataset);

    let problems = verify(dir, &config.split).map_err(|e| e.to_string())?;
    if !problems.is_empty() {
        return Err(format!(
            "the dataset seal does not hold, nothing was measured: {}",
            problems.join("; ")
        ));
    }
    let manifest = json_file(&format!("{dataset}/manifest.json"))?;
    let net_text = fs::read_to_string(&net_path).map_err(|e| format!("{net_path}: {e}"))?;
    let network = Network::from_json(&net_text).map_err(|e| e.to_string())?;
    let rules = RuleDecider::new(config.rules);
    let mut chooser = NetworkChooser::new(network, rules);

    let heldout_examples = read_split(dir, Split::Heldout).map_err(|e| e.to_string())?;
    let heldout = states(&heldout_examples)?;
    let unseen = if manifest["files"]
        .get("heldout-unseen-advisor.jsonl")
        .is_some()
    {
        let examples = read_split(dir, Split::UnseenAdvisor).map_err(|e| e.to_string())?;
        Some(states(&examples)?)
    } else {
        None
    };
    let parity = match flag(args, "--parity") {
        Some(path) => Some(
            json_file(&path)?
                .get("max_abs_diff")
                .and_then(Value::as_f64)
                .ok_or(format!("{path}: `max_abs_diff` is missing"))?,
        ),
        None => None,
    };

    if let Some(path) = flag(args, "--scores-out") {
        let mut scores: BTreeMap<String, f64> = BTreeMap::new();
        for e in &heldout_examples {
            let p = chooser
                .scores(&e.signals)
                .into_iter()
                .find(|(a, _)| *a == e.action)
                .map(|(_, p)| p)
                .ok_or(format!("{}: the action is not a legal candidate", e.id()))?;
            scores.insert(e.id(), p);
        }
        fs::write(&path, json!(scores).to_string()).map_err(|e| format!("{path}: {e}"))?;
        println!("wrote {} scores to {path}", scores.len());
    }

    let report = evaluate(
        &Inputs {
            heldout: &heldout,
            unseen_advisor: unseen.as_deref(),
            parity_max_diff: parity,
        },
        &mut chooser,
        &rules,
        &limits,
    );
    let scenario_share = manifest["splits"]["heldout"]["scenario_share"].clone();
    let promotable = report.all_pass();
    let document = json!({
        "task": "T171",
        "status": if promotable { "all gates pass" } else { "NOT PROMOTED" },
        "qualified": false,
        "dataset": {
            "path": dataset,
            "date": manifest["date"],
            "heldout_sha256": manifest["files"]["heldout.jsonl"]["sha256"],
            "heldout_examples": heldout_examples.len(),
            "heldout_states": heldout.len(),
            "scenario_share": scenario_share,
            "manifest_sha256": digest(&format!("{dataset}/manifest.json"))?,
        },
        "network": {"path": net_path, "sha256": sha256_hex(net_text.as_bytes())},
        "gates_config": {"path": gates_path, "sha256": digest(&gates_path)?},
        "dataset_config": {"path": config_path, "sha256": digest(&config_path)?},
        "machine": {"cpu": cpu_model()},
        "gates": report.gates.iter().map(|g| g.to_json()).collect::<Vec<_>>(),
        "read_this": "Every held-out example is a scenario example: the labels come from a hand-made oracle, so a gate \
                      measures agreement with that oracle, not decision quality in the world. The network is NOT \
                      QUALIFIED; the rule decider stays in charge unless the owner promotes the network.",
    });
    fs::write(
        &out,
        serde_json::to_string_pretty(&document).map_err(|e| e.to_string())? + "\n",
    )
    .map_err(|e| format!("{out}: {e}"))?;
    for g in &report.gates {
        println!("[{}] {}", g.status.as_str(), g.id);
    }
    println!("report: {out}");
    println!(
        "{}",
        if promotable {
            "every gate passed (the owner decides the promotion)"
        } else {
            "not every gate passed: the rule decider stays in charge"
        }
    );
    let failed = report.gates.iter().any(|g| g.status == Status::Fail);
    Ok(if promotable && !failed {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    })
}

/// Runs the command.
pub fn run(args: &[String]) -> ExitCode {
    match run_inner(args) {
        Ok(code) => code,
        Err(message) => {
            eprintln!("decision-gates: {message}");
            ExitCode::from(2)
        }
    }
}
