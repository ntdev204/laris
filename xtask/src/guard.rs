//! No-training guard (SR-G3): the Rust workspace and CI never run or authorize training.
//!
//! Scans `crates/`, `xtask/` and `.github/` for training entry points, optimizer steps and the
//! training-authorization variables. Training happens only when the owner runs it by hand.

use regex::Regex;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const AUTH_VARS: [&str; 2] = [
    "LARIS_TRAINING_AUTHORIZED",
    "LARIS_TOKENIZER_TRAINING_AUTHORIZED",
];
const PATTERN: &str = r"LanguageEncoderTrainer|run_training|profile_memory|train_tokenizer|train_language_encoder|fit_offline|LARIS_TRAINING_AUTHORIZED|LARIS_TOKENIZER_TRAINING_AUTHORIZED|\.backward\(|(optimizer|optim|opt|scaler)\w*\.step\(";
const SCANNED: [&str; 3] = ["crates", "xtask", ".github"];
const EXTENSIONS: [&str; 5] = ["rs", "toml", "yml", "yaml", "sh"];

fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect(&path, out);
        } else if path
            .extension()
            .is_some_and(|e| EXTENSIONS.iter().any(|x| e == *x))
        {
            out.push(path);
        }
    }
}

/// Findings (`file:line: match`) under `root`, skipping this guard's own source.
pub fn scan(root: &Path) -> Vec<String> {
    let pattern = Regex::new(PATTERN).expect("static regex");
    let mut files = Vec::new();
    for dir in SCANNED {
        collect(&root.join(dir), &mut files);
    }
    files.sort();
    let mut findings = Vec::new();
    for path in files {
        if path.ends_with("xtask/src/guard.rs") {
            continue;
        }
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        let rel = path
            .strip_prefix(root)
            .unwrap_or(&path)
            .display()
            .to_string();
        for (n, line) in text.lines().enumerate() {
            if let Some(m) = pattern.find(line) {
                findings.push(format!("{rel}:{}: {}", n + 1, m.as_str()));
            }
        }
    }
    findings
}

/// Run the guard under `root`; exit code 0 when nothing trains or authorizes training.
pub fn run(root: &Path) -> ExitCode {
    for var in AUTH_VARS {
        if env::var_os(var).is_some_and(|v| !v.is_empty()) {
            println!("[FAIL] {var} is set; checks never run with training authorized.");
            return ExitCode::from(2);
        }
    }
    let findings = scan(root);
    for finding in &findings {
        println!("[FAIL] {finding}");
    }
    if findings.is_empty() {
        println!("[PASS] no training call or authorization in crates/, xtask/ or .github/.");
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seeded(body: &str) -> Vec<String> {
        let dir = env::temp_dir().join(format!("laris-guard-{}", body.len()));
        let crate_dir = dir.join("crates").join("c");
        fs::create_dir_all(&crate_dir).expect("temp dir");
        fs::write(crate_dir.join("lib.rs"), body).expect("temp file");
        let found = scan(&dir);
        fs::remove_dir_all(&dir).ok();
        found
    }

    #[test]
    fn clean_source_passes() {
        assert!(seeded("pub fn ok() {}\n").is_empty());
    }

    #[test]
    fn seeded_training_call_fails() {
        assert_eq!(seeded("fn f() { run_training(); }\n").len(), 1);
    }

    #[test]
    fn seeded_optimizer_step_fails() {
        assert_eq!(seeded("fn f() { optimizer.step(); }\n").len(), 1);
    }
}
