//! `laris replay`: a recorded core scenario through the terminal interface, from the compiled binary (T157).

#![allow(missing_docs)]

use std::process::Command;

fn laris(args: &[&str], envs: &[(&str, &str)]) -> std::process::Output {
    // every call has its own home: two tests of this file run at once and would race on `settings.json`
    static CALLS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let n = CALLS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let home = std::env::temp_dir().join(format!("laris-cli-t157-{}-{n}", std::process::id()));
    std::fs::create_dir_all(&home).unwrap();
    Command::new(env!("CARGO_BIN_EXE_laris"))
        .args(args)
        .env_clear()
        .env("PATH", std::env::var("PATH").unwrap_or_default())
        .env("HOME", &home)
        .env("LARIS_HOME", home.join(".laris"))
        .envs(envs.iter().copied())
        .current_dir(&home)
        .output()
        .expect("run laris")
}

fn scenario(name: &str) -> String {
    format!(
        "{}/../../tests/golden/ink_scenarios/{name}.json",
        env!("CARGO_MANIFEST_DIR")
    )
}

#[test]
fn a_recorded_chat_is_shown_through_the_interface_at_the_width_asked() {
    for width in ["60", "100"] {
        let out = laris(&["replay", &scenario("basic_chat"), "--width", width], &[]);
        assert_eq!(
            out.status.code(),
            Some(0),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        let screen = String::from_utf8(out.stdout).unwrap();
        assert!(screen.contains("● Found 2 passages."), "{screen}");
        assert!(screen.contains("> hello"));
        let limit: usize = width.parse().unwrap();
        assert!(
            screen
                .lines()
                .all(|l| laris_tui::width::str_width(l) <= limit)
        );
        assert!(!screen.contains('\x1b'), "no colour unless asked");
    }
    let width_from_env = laris(&["replay", &scenario("basic_chat")], &[("COLUMNS", "40")]);
    let screen = String::from_utf8(width_from_env.stdout).unwrap();
    assert!(
        screen.lines().all(|l| laris_tui::width::str_width(l) <= 40),
        "{screen}"
    );
}

#[test]
fn colour_and_steps_are_opt_in_and_a_bad_file_is_a_usage_error() {
    let out = laris(
        &["replay", &scenario("interrupt"), "--color", "--steps"],
        &[],
    );
    let screen = String::from_utf8(out.stdout).unwrap();
    assert!(screen.contains("──── step 3 ────") && screen.contains("Second answer."));
    let out = laris(&["replay", &scenario("interrupt"), "--color"], &[]);
    assert!(String::from_utf8(out.stdout).unwrap().contains('\x1b'));

    for args in [
        vec!["replay"],
        vec!["replay", "/nonexistent/scenario.json"],
        vec!["replay", "--bogus"],
        vec!["replay", "a.json", "b.json"],
    ] {
        let out = laris(&args, &[]);
        assert_eq!(out.status.code(), Some(2), "{args:?}");
        assert!(!out.stderr.is_empty());
    }
}
