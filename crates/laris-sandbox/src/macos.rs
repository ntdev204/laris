//! The Seatbelt profile for a `Policy` (macOS).
//!
//! The base and network profiles are forked from codex (`codex-rs/sandboxing/src/seatbelt_*_policy.sbpl`, Apache-2.0,
//! commit `aa5f492031f7edb75a40973d19eda8efb9512c61`); the generator is LARIS's own and much smaller than codex's.
//! The profile text is built and tested on every platform, but it has **not been run** on macOS (no macOS machine).

use crate::policy::Policy;
use std::ffi::OsString;
use std::path::Path;

/// `sandbox-exec` is taken from `/usr/bin` only, never from `PATH`, so a planted binary is not run.
pub const SANDBOX_EXEC: &str = "/usr/bin/sandbox-exec";

const BASE: &str = include_str!("macos/seatbelt_base_policy.sbpl");
const NETWORK: &str = include_str!("macos/seatbelt_network_policy.sbpl");

/// The profile text and the `-D` parameters it refers to.
#[must_use]
pub fn profile(policy: &Policy) -> (String, Vec<(String, String)>) {
    let mut text = String::from(BASE);
    let mut params = Vec::new();
    text.push_str("\n(allow file-read*)\n");
    let mut grants = Vec::new();
    for (i, root) in policy.writable.iter().enumerate() {
        let key = format!("WRITABLE_ROOT_{i}");
        params.push((key.clone(), canonical(root)));
        let mut rule = format!("(subpath (param \"{key}\"))");
        for (j, name) in policy.protected_names.iter().enumerate() {
            let pkey = format!("PROTECTED_{i}_{j}");
            params.push((pkey.clone(), canonical(&root.join(name))));
            rule = format!("(require-all {rule} (require-not (subpath (param \"{pkey}\"))))");
        }
        grants.push(rule);
    }
    if !grants.is_empty() {
        text.push_str(&format!("(allow file-write*\n  {})\n", grants.join("\n  ")));
    }
    for (i, path) in policy.deny_read.iter().enumerate() {
        let key = format!("DENY_READ_{i}");
        params.push((key.clone(), canonical(path)));
        text.push_str(&format!("(deny file-read* (subpath (param \"{key}\")))\n"));
    }
    if policy.network {
        text.push_str("(allow network-outbound)\n(allow network-inbound)\n(allow network-bind)\n");
        text.push_str(NETWORK);
    }
    (text, params)
}

/// `sandbox-exec` arguments that run `argv` under the policy.
#[must_use]
pub fn sandbox_exec_args(policy: &Policy, argv: &[OsString]) -> Vec<OsString> {
    let (text, params) = profile(policy);
    let mut args = vec![OsString::from("-p"), OsString::from(text)];
    args.extend(
        params
            .into_iter()
            .map(|(k, v)| OsString::from(format!("-D{k}={v}"))),
    );
    args.push("--".into());
    args.extend(argv.iter().cloned());
    args
}

fn canonical(path: &Path) -> String {
    path.canonicalize()
        .unwrap_or_else(|_| path.to_path_buf())
        .to_string_lossy()
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn writes_are_limited_and_protected_names_excluded() {
        let policy = Policy::workspace([PathBuf::from("/work")]);
        let (text, params) = profile(&policy);
        assert!(text.contains("(deny default)"));
        assert!(text.contains("(allow file-write*"));
        assert!(text.contains("(require-not (subpath (param \"PROTECTED_0_0\")))"));
        assert!(
            params
                .iter()
                .any(|(k, v)| k == "WRITABLE_ROOT_0" && v == "/work")
        );
        assert!(
            params
                .iter()
                .any(|(k, v)| k == "PROTECTED_0_1" && v == "/work/.laris")
        );
        assert!(!text.contains("(allow network-outbound)"));
    }

    #[test]
    fn network_and_hidden_paths_follow_the_policy() {
        let policy = Policy::read_only()
            .with_network(true)
            .with_deny_read([PathBuf::from("/secret")]);
        let (text, _) = profile(&policy);
        assert!(text.contains("(allow network-outbound)"));
        assert!(text.contains("(deny file-read* (subpath (param \"DENY_READ_0\")))"));
        assert!(!text.contains("(allow file-write*"));
    }

    #[test]
    fn command_line_ends_with_the_command() {
        let args = sandbox_exec_args(&Policy::read_only(), &["ls".into()]);
        assert_eq!(args[0], "-p");
        assert_eq!(args[args.len() - 2], "--");
        assert_eq!(args[args.len() - 1], "ls");
    }
}
