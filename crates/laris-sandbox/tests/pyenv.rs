//! The Python environment: built on first use, repaired, rebuilt on a settings change, built once under two
//! sessions, and a failed build leaves nothing behind. Every test uses its own home, never `~/.laris`.
#![allow(missing_docs)]

mod support;

use laris_config::settings::Sandbox as Settings;
use laris_sandbox::pyenv::{ensure, ensure_with};
use std::ffi::OsStr;
use std::process::Command;
use support::Tmp;

fn settings() -> Settings {
    Settings {
        python: "3.12".into(),
        ..Settings::default()
    }
}

fn runs(env: &laris_sandbox::PythonEnv) -> bool {
    Command::new(env.python())
        .args(["-c", "import sys; print(sys.prefix)"])
        .output()
        .is_ok_and(|o| {
            o.status.success()
                && String::from_utf8_lossy(&o.stdout).trim() == env.dir.to_string_lossy()
        })
}

#[test]
fn built_on_first_use_and_reused_after() {
    let home = Tmp::new("py-first");
    let first = ensure(home.path(), &settings()).expect("build");
    assert!(first.built && runs(&first));
    assert_eq!(first.dir, home.path().join(".venv"));
    let second = ensure(home.path(), &settings()).expect("reuse");
    assert!(!second.built && runs(&second));
}

#[test]
fn a_broken_environment_is_repaired() {
    let home = Tmp::new("py-repair");
    let env = ensure(home.path(), &settings()).expect("build");
    std::fs::remove_file(env.python()).expect("break the interpreter");
    let fixed = ensure(home.path(), &settings()).expect("repair");
    assert!(fixed.built && runs(&fixed));
    // an interrupted build has no marker
    std::fs::remove_file(fixed.dir.join(".laris-env")).expect("remove marker");
    let again = ensure(home.path(), &settings()).expect("repair again");
    assert!(again.built && runs(&again));
}

#[test]
fn changed_settings_rebuild_the_environment() {
    let home = Tmp::new("py-change");
    let first = ensure(home.path(), &settings()).expect("build");
    std::fs::write(first.dir.join("stale.txt"), "x").expect("stale file");
    let other = Settings {
        python: "3.12".into(),
        index_url: "https://example.invalid/simple".into(),
        ..Settings::default()
    };
    let second = ensure(home.path(), &other).expect("rebuild");
    assert!(second.built && !second.dir.join("stale.txt").exists());
}

#[test]
fn two_sessions_build_it_once() {
    let home = Tmp::new("py-two");
    let path = home.path().to_path_buf();
    let handles: Vec<_> = (0..2)
        .map(|_| {
            let path = path.clone();
            std::thread::spawn(move || ensure(&path, &settings()).expect("ensure"))
        })
        .collect();
    let results: Vec<_> = handles
        .into_iter()
        .map(|h| h.join().expect("thread"))
        .collect();
    assert_eq!(results.iter().filter(|r| r.built).count(), 1, "{results:?}");
    assert!(results.iter().all(runs));
}

#[test]
fn a_failed_build_leaves_no_environment() {
    let home = Tmp::new("py-fail");
    let err =
        ensure_with(OsStr::new("/nonexistent/uv"), home.path(), &settings()).expect_err("no uv");
    assert!(err.to_string().contains("uv"), "{err}");
    assert!(!home.path().join(".venv").exists());
    let bad = Settings {
        python: "0.0.1".into(),
        ..Settings::default()
    };
    let err = ensure(home.path(), &bad).expect_err("no such python");
    assert!(err.to_string().contains("uv venv"), "{err}");
    assert!(!home.path().join(".venv").exists());
}

#[test]
fn the_environment_is_outside_the_sandbox_write_roots() {
    // the sandbox writes only to the project, so the interpreter folder in the home is read-only to a command
    use laris_sandbox::{Backend, Policy, Sandbox};
    let home = Tmp::new("py-ro");
    let project = Tmp::new("py-project");
    let env = ensure(home.path(), &settings()).expect("build");
    let sandbox = Sandbox::with_backend(
        Policy::workspace([project.path().to_path_buf()]),
        Backend::Landlock,
        Some(std::path::PathBuf::from(env!(
            "CARGO_BIN_EXE_laris-sandbox-helper"
        ))),
    )
    .expect("sandbox");
    let script = format!("echo x > {}/poison.txt", env.dir.display());
    let out = sandbox
        .command(&["sh".into(), "-c".into(), script.into()], project.path())
        .expect("command")
        .output()
        .expect("run");
    assert!(!out.status.success());
    assert!(!env.dir.join("poison.txt").exists());
}
