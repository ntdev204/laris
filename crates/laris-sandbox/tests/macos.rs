//! macOS backend tests (T135b). They run only on macOS: `cargo test -p laris-sandbox --test macos`.
//! They have never been run: the Seatbelt backend was written on Linux and tested as text only.
#![cfg(target_os = "macos")]
#![allow(missing_docs)]

mod support;

use laris_sandbox::{Backend, Policy, Sandbox, sandbox::os};
use std::path::Path;
use support::Tmp;

/// Runs `/bin/sh -c <script>` in `cwd` under `policy`; returns the exit code.
fn run(policy: Policy, cwd: &Path, script: &str) -> i32 {
    let sandbox = Sandbox::with_backend(policy, Backend::Seatbelt, None).expect("sandbox");
    let mut cmd = sandbox
        .command(&[os("/bin/sh"), os("-c"), os(script)], cwd)
        .expect("command");
    cmd.status().expect("spawn").code().expect("code")
}

#[test]
fn a_write_inside_the_root_works_and_one_outside_fails() {
    let (inside, outside) = (Tmp::new("mac-in"), Tmp::new("mac-out"));
    let policy = || Policy::workspace([inside.path().to_path_buf()]);
    let ok = inside.path().join("a.txt");
    let bad = outside.path().join("b.txt");
    assert_eq!(
        run(
            policy(),
            inside.path(),
            &format!("echo x > '{}'", ok.display())
        ),
        0
    );
    assert!(ok.is_file());
    assert_ne!(
        run(
            policy(),
            inside.path(),
            &format!("echo x > '{}'", bad.display())
        ),
        0
    );
    assert!(!bad.exists());
}

#[test]
fn protected_names_stay_read_only() {
    let root = Tmp::new("mac-protect");
    let git = root.path().join(".git");
    std::fs::create_dir(&git).expect("dir");
    let target = git.join("config");
    let policy = Policy::workspace([root.path().to_path_buf()]);
    assert_ne!(
        run(
            policy,
            root.path(),
            &format!("echo x > '{}'", target.display())
        ),
        0
    );
    assert!(!target.exists());
}

#[test]
fn the_exit_code_is_the_commands() {
    let root = Tmp::new("mac-exit");
    let policy = Policy::workspace([root.path().to_path_buf()]);
    assert_eq!(run(policy, root.path(), "exit 7"), 7);
}

#[test]
fn hidden_paths_cannot_be_read() {
    let root = Tmp::new("mac-hide");
    let secret = root.path().join("secret.txt");
    std::fs::write(&secret, "s").expect("file");
    let policy = Policy::workspace([root.path().to_path_buf()]).with_deny_read([secret.clone()]);
    assert_ne!(
        run(policy, root.path(), &format!("cat '{}'", secret.display())),
        0
    );
}
