//! Windows backend tests (T135). They run only on Windows: `cargo test -p laris-sandbox --test windows`.
//! They have never been run: the backend was written on Linux and checked with `cargo check --target`.
#![cfg(windows)]
#![allow(missing_docs)]

mod support;

use laris_sandbox::{Backend, Policy, Sandbox, sandbox::os};
use std::path::Path;
use support::Tmp;

fn helper() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_BIN_EXE_laris-sandbox-helper"))
}

/// Runs `cmd /c <script>` in `cwd` under `policy`; returns the exit code.
fn run(policy: Policy, cwd: &Path, script: &str) -> i32 {
    let sandbox =
        Sandbox::with_backend(policy, Backend::RestrictedToken, Some(helper())).expect("sandbox");
    let mut cmd = sandbox
        .command(&[os("cmd"), os("/c"), os(script)], cwd)
        .expect("command");
    cmd.status().expect("spawn").code().expect("code")
}

fn workspace(root: &Path) -> Policy {
    Policy::workspace([root.to_path_buf()]).with_network(true)
}

#[test]
fn a_write_inside_the_root_works_and_one_outside_fails() {
    let (inside, outside) = (Tmp::new("win-in"), Tmp::new("win-out"));
    let ok = inside.path().join("a.txt");
    let bad = outside.path().join("b.txt");
    assert_eq!(
        run(
            workspace(inside.path()),
            inside.path(),
            &format!("echo x> \"{}\"", ok.display())
        ),
        0
    );
    assert!(ok.is_file());
    assert_ne!(
        run(
            workspace(inside.path()),
            inside.path(),
            &format!("echo x> \"{}\"", bad.display())
        ),
        0
    );
    assert!(!bad.exists());
}

#[test]
fn protected_names_stay_read_only() {
    let root = Tmp::new("win-protect");
    let git = root.path().join(".git");
    std::fs::create_dir(&git).expect("dir");
    let target = git.join("config");
    assert_ne!(
        run(
            workspace(root.path()),
            root.path(),
            &format!("echo x> \"{}\"", target.display())
        ),
        0
    );
    assert!(!target.exists());
}

#[test]
fn the_exit_code_is_the_commands() {
    let root = Tmp::new("win-exit");
    assert_eq!(run(workspace(root.path()), root.path(), "exit 7"), 7);
}

#[test]
fn a_policy_the_backend_cannot_enforce_is_refused() {
    let root = Tmp::new("win-refuse");
    let no_network = Policy::workspace([root.path().to_path_buf()]);
    assert!(Sandbox::with_backend(no_network, Backend::RestrictedToken, Some(helper())).is_err());
    let hidden = workspace(root.path()).with_deny_read([root.path().join("secret")]);
    assert!(Sandbox::with_backend(hidden, Backend::RestrictedToken, Some(helper())).is_err());
}
