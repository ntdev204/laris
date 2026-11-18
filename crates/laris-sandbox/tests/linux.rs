//! The Linux backends against the real kernel: writes outside the allowed roots fail, protected names and hidden
//! paths hold, the network is cut, and the Landlock fallback confines writes too.
#![cfg(target_os = "linux")]
#![allow(missing_docs)]

mod support;

use laris_sandbox::{Backend, Policy, Sandbox, SandboxError};
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Output;
use support::Tmp;

fn helper() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_laris-sandbox-helper"))
}

fn run(backend: Backend, policy: Policy, cwd: &Path, script: &str) -> Output {
    let sandbox = Sandbox::with_backend(policy, backend, Some(helper())).expect("sandbox");
    let argv: Vec<OsString> = vec!["sh".into(), "-c".into(), script.into()];
    sandbox
        .command(&argv, cwd)
        .expect("command")
        .output()
        .expect("spawn")
}

fn ok(o: &Output) -> bool {
    o.status.success()
}

fn both() -> Vec<Backend> {
    let mut backends = vec![Backend::Landlock];
    if laris_sandbox::sandbox::bwrap_works() {
        backends.push(Backend::Bubblewrap);
    } else {
        eprintln!("bwrap is not usable here: only the Landlock fallback was tested");
    }
    backends
}

#[test]
fn writes_outside_the_allowed_roots_fail_and_inside_succeed() {
    for backend in both() {
        let project = Tmp::new("proj");
        let outside = Tmp::new("outside");
        let target = outside.path().join("x.txt");
        let policy = Policy::workspace([project.path().to_path_buf()]);
        let inside = run(
            backend,
            policy.clone(),
            project.path(),
            "echo hi > in.txt && cat in.txt",
        );
        assert!(ok(&inside), "{backend:?}: {inside:?}");
        assert_eq!(
            std::fs::read_to_string(project.path().join("in.txt")).unwrap(),
            "hi\n"
        );
        let script = format!("echo no > {}", target.display());
        let out = run(backend, policy, project.path(), &script);
        assert!(!ok(&out), "{backend:?} wrote outside the roots");
        assert!(!target.exists(), "{backend:?}");
    }
}

#[test]
fn a_symbolic_link_out_of_the_root_does_not_open_the_target() {
    for backend in both() {
        let project = Tmp::new("link");
        let outside = Tmp::new("linked");
        std::os::unix::fs::symlink(outside.path(), project.path().join("door")).unwrap();
        let policy = Policy::workspace([project.path().to_path_buf()]);
        let out = run(backend, policy, project.path(), "echo no > door/x.txt");
        assert!(!ok(&out), "{backend:?}");
        assert!(!outside.path().join("x.txt").exists(), "{backend:?}");
    }
}

#[test]
fn read_only_policy_writes_nothing() {
    for backend in both() {
        let project = Tmp::new("ro");
        let out = run(
            backend,
            Policy::read_only(),
            project.path(),
            "echo no > x.txt",
        );
        assert!(!ok(&out), "{backend:?}");
        assert!(!project.path().join("x.txt").exists());
    }
}

#[test]
fn the_network_is_cut() {
    let probe = "python3 -c 'import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)'";
    for backend in both() {
        let project = Tmp::new("net");
        let off = run(
            backend,
            Policy::workspace([project.path().to_path_buf()]),
            project.path(),
            probe,
        );
        assert!(!ok(&off), "{backend:?} opened an internet socket: {off:?}");
        let local = "python3 -c 'import socket; socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)'";
        let out = run(backend, Policy::read_only(), project.path(), local);
        assert!(ok(&out), "{backend:?} refused a local socket: {out:?}");
        let on = run(
            backend,
            Policy::read_only().with_network(true),
            project.path(),
            probe,
        );
        assert!(
            ok(&on),
            "{backend:?} refused a socket although the network is on: {on:?}"
        );
    }
}

#[test]
fn ptrace_is_refused() {
    for backend in both() {
        let project = Tmp::new("ptrace");
        let script = "python3 -c \"import ctypes,sys; r=ctypes.CDLL(None,use_errno=True).ptrace(0,0,0,0); sys.exit(0 if r==-1 and ctypes.get_errno()==1 else 3)\"";
        let out = run(backend, Policy::read_only(), project.path(), script);
        assert!(ok(&out), "{backend:?}: {out:?}");
    }
}

#[test]
fn bubblewrap_keeps_protected_names_read_only_and_hides_paths() {
    if !laris_sandbox::sandbox::bwrap_works() {
        eprintln!("bwrap is not usable here: skipped");
        return;
    }
    let project = Tmp::new("prot");
    std::fs::create_dir_all(project.path().join(".git")).unwrap();
    std::fs::write(project.path().join(".git/config"), "keep").unwrap();
    std::fs::create_dir_all(project.path().join(".laris")).unwrap();
    std::fs::write(project.path().join("secret.env"), "TOKEN=1").unwrap();
    std::fs::create_dir_all(project.path().join("vault")).unwrap();
    std::fs::write(project.path().join("vault/note"), "private").unwrap();
    let policy = Policy::workspace([project.path().to_path_buf()]).with_deny_read([
        project.path().join("secret.env"),
        project.path().join("vault"),
    ]);
    let writes =
        "echo x > .git/config; echo x > .git/new; echo x > .laris/rule; rm -rf .git/config; true";
    let out = run(Backend::Bubblewrap, policy.clone(), project.path(), writes);
    assert!(ok(&out));
    assert_eq!(
        std::fs::read_to_string(project.path().join(".git/config")).unwrap(),
        "keep"
    );
    assert!(!project.path().join(".git/new").exists());
    assert!(!project.path().join(".laris/rule").exists());
    let read = run(
        Backend::Bubblewrap,
        policy.clone(),
        project.path(),
        "cat secret.env",
    );
    assert!(
        !String::from_utf8_lossy(&read.stdout).contains("TOKEN"),
        "{read:?}"
    );
    let ls = run(
        Backend::Bubblewrap,
        policy,
        project.path(),
        "ls vault | wc -l",
    );
    assert_eq!(String::from_utf8_lossy(&ls.stdout).trim(), "0");
}

#[test]
fn restricted_read_hides_the_home_but_still_runs_programs() {
    if !laris_sandbox::sandbox::bwrap_works() {
        eprintln!("bwrap is not usable here: skipped");
        return;
    }
    let project = Tmp::new("only");
    let other = Tmp::new("other");
    std::fs::write(other.path().join("hidden.txt"), "no").unwrap();
    let policy = Policy::workspace([project.path().to_path_buf()])
        .with_readable_only([project.path().to_path_buf()]);
    let script = format!(
        "cat {}; echo ran",
        other.path().join("hidden.txt").display()
    );
    let out = run(Backend::Bubblewrap, policy, project.path(), &script);
    let text = String::from_utf8_lossy(&out.stdout);
    assert!(text.contains("ran") && !text.contains("no\n"), "{out:?}");
}

#[test]
fn the_fallback_cannot_hide_paths_and_says_what_it_does_not_enforce() {
    let policy = Policy::read_only().with_deny_read([PathBuf::from("/etc/shadow")]);
    let refused = Sandbox::with_backend(policy, Backend::Landlock, Some(helper()));
    assert!(matches!(refused, Err(SandboxError::Unsupported(_))));
    let fallback =
        Sandbox::with_backend(Policy::read_only(), Backend::Landlock, Some(helper())).unwrap();
    assert!(!fallback.limits().is_empty());
    let full =
        Sandbox::with_backend(Policy::read_only(), Backend::Bubblewrap, Some(helper())).unwrap();
    assert!(full.limits().is_empty());
}

#[test]
fn a_missing_helper_means_no_sandbox_not_an_unconfined_command() {
    let missing = Sandbox::with_backend(
        Policy::read_only(),
        Backend::Bubblewrap,
        Some(PathBuf::from("/nonexistent/laris-sandbox-helper")),
    )
    .unwrap();
    let project = Tmp::new("missing");
    let out = missing
        .command(
            &["sh".into(), "-c".into(), "echo ran > ran.txt".into()],
            project.path(),
        )
        .unwrap()
        .output()
        .unwrap();
    assert!(!ok(&out));
    assert!(!project.path().join("ran.txt").exists());
}

#[test]
fn the_exit_code_passes_through() {
    let project = Tmp::new("exit");
    let out = run(
        Backend::Landlock,
        Policy::read_only(),
        project.path(),
        "exit 7",
    );
    assert_eq!(out.status.code(), Some(7));
}
