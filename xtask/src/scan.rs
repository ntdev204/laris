//! Hardcoded endpoint and secret scan (SR-L1): no source of the Rust workspace carries a server address or a
//! credential. Endpoints, limits and keys come from configuration and the environment.
//!
//! Scans the non-test sources under `crates/*/src` and `xtask/src` (`.rs`) and the catalogue files
//! (`crates/*/catalogue/*.json`). Comment lines are skipped; a line that must carry a literal on purpose
//! says `scan:allow` and why. Test sources (`tests/`) may hold example addresses.

use regex::Regex;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const ENDPOINT: &str = r"https?://[A-Za-z0-9\[]|\b(\d{1,3}\.){3}\d{1,3}\b";
const SECRET: &str = r#"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._-]{20,}|(?i)(password|secret|api_?key|token)\w*\s*[:=]\s*"[^"]{6,}""#;
const ALLOW: &str = "scan:allow";

fn collect(dir: &Path, wanted_ext: &str, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect(&path, wanted_ext, out);
        } else if path.extension().is_some_and(|e| e == wanted_ext) {
            out.push(path);
        }
    }
}

fn sources(root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    collect(&root.join("xtask/src"), "rs", &mut files);
    if let Ok(crates) = fs::read_dir(root.join("crates")) {
        for krate in crates.flatten() {
            collect(&krate.path().join("src"), "rs", &mut files);
            collect(&krate.path().join("catalogue"), "json", &mut files);
        }
    }
    files.sort();
    files
}

/// Findings (`file:line: kind: match`) under `root`, skipping this scan's own source.
pub fn scan(root: &Path) -> Vec<String> {
    let endpoint = Regex::new(ENDPOINT).expect("static regex");
    let secret = Regex::new(SECRET).expect("static regex");
    let mut findings = Vec::new();
    for path in sources(root) {
        if path.ends_with("xtask/src/scan.rs") {
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
            if line.trim_start().starts_with("//") || line.contains(ALLOW) {
                continue;
            }
            for (kind, re) in [("endpoint", &endpoint), ("secret", &secret)] {
                if let Some(m) = re.find(line) {
                    findings.push(format!("{rel}:{}: {kind}: {}", n + 1, m.as_str()));
                }
            }
        }
    }
    findings
}

/// Run the scan under `root`; exit code 0 when nothing is found.
pub fn run(root: &Path) -> ExitCode {
    let findings = scan(root);
    for finding in &findings {
        println!("[FAIL] {finding}");
    }
    if findings.is_empty() {
        println!(
            "[PASS] no hardcoded endpoint or secret in crates/*/src, crates/*/catalogue or xtask/src."
        );
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seeded(name: &str, body: &str) -> Vec<String> {
        let dir = env_dir(name);
        let src = dir.join("crates").join("c").join("src");
        fs::create_dir_all(&src).expect("temp dir");
        fs::write(src.join("lib.rs"), body).expect("temp file");
        let found = scan(&dir);
        fs::remove_dir_all(&dir).ok();
        found
    }

    fn env_dir(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("laris-scan-{name}-{}", std::process::id()))
    }

    #[test]
    fn clean_source_passes() {
        assert!(
            seeded(
                "clean",
                "pub const SCHEME: &str = \"https://\";\nfn f() {}\n"
            )
            .is_empty()
        );
    }

    #[test]
    fn comments_and_allowed_lines_pass() {
        let body = "// see https://example.org/doc\nconst A: &str = \"http://localhost\"; // scan:allow test double\n";
        assert!(seeded("allow", body).is_empty());
    }

    #[test]
    fn seeded_endpoint_fails() {
        assert_eq!(
            seeded("url", "const U: &str = \"https://api.example.org/v1\";\n").len(),
            1
        );
    }

    #[test]
    fn seeded_ip_address_fails() {
        assert_eq!(
            seeded("ip", "const H: &str = \"10.0.0.7:8080\";\n").len(),
            1
        );
    }

    #[test]
    fn seeded_secrets_fail() {
        assert_eq!(
            seeded("key", "const K: &str = \"sk-abcdefghijklmnopqrstuvwx\";\n").len(),
            1
        );
        assert_eq!(
            seeded("assign", "let password = \"hunter2hunter2\";\n").len(),
            1
        );
        assert_eq!(
            seeded(
                "pem",
                "const P: &str = \"-----BEGIN RSA PRIVATE KEY-----\";\n"
            )
            .len(),
            1
        );
    }

    #[test]
    fn catalogue_files_are_scanned() {
        let dir = env_dir("catalogue");
        let cat = dir.join("crates").join("c").join("catalogue");
        fs::create_dir_all(&cat).expect("temp dir");
        fs::write(
            cat.join("en.json"),
            "{\"a\": \"see https://host.example/x\"}\n",
        )
        .expect("temp file");
        let found = scan(&dir);
        fs::remove_dir_all(&dir).ok();
        assert_eq!(found.len(), 1);
    }
}
