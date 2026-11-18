//! Hooks: allow, block, matcher, timeout, malformed output, hostile output, environment.
#![cfg(unix)]

mod common;

use common::{args, exists, rig};
use laris_config::Settings;
use laris_policy::{HookRunner, OUTPUT_CAP, clean};
use serde_json::{Map, Value, json};
use std::time::{Duration, Instant};

fn with_hooks(name: &str, hooks: Value) -> (common::Rig, HookRunner) {
    let rig = rig(name);
    let runner = runner_in(&rig, hooks, |_| {});
    (rig, runner)
}

fn runner_in(rig: &common::Rig, hooks: Value, change: impl FnOnce(&mut Settings)) -> HookRunner {
    let mut settings = Settings {
        hooks: serde_json::from_value(hooks).expect("hooks"),
        ..Settings::default()
    };
    change(&mut settings);
    HookRunner::new(&settings, &rig.project, "s1")
}

fn one(event: &str, command: &str, timeout: u32) -> Value {
    json!({ event: [{"matcher": "", "hooks": [
        {"type": "command", "command": command, "timeout": timeout}]}]})
}

fn payload(value: Value) -> Map<String, Value> {
    args(value)
}

#[test]
fn no_hooks_means_nothing_runs() {
    let (_, runner) = with_hooks("none", json!({}));
    let out = runner.run("UserPromptSubmit", &payload(json!({"prompt": "hi"})), "");
    assert_eq!((out.ran, out.blocked), (0, false));
    assert!(!runner.has("PreToolUse"));
}

#[test]
fn a_hook_reads_the_event_as_json_and_may_add_context() {
    let (rig, runner) = with_hooks(
        "context",
        one(
            "UserPromptSubmit",
            "cat > seen.json; echo '{\"additionalContext\": \"use metric units\"}'",
            5,
        ),
    );
    let out = runner.run("UserPromptSubmit", &payload(json!({"prompt": "héllo"})), "");
    assert!(
        !out.blocked && out.ran == 1 && out.warnings.is_empty(),
        "{out:?}"
    );
    assert_eq!(out.context, ["use metric units"]);
    let seen: Value =
        serde_json::from_str(&std::fs::read_to_string(rig.project.join("seen.json")).expect("f"))
            .expect("json");
    assert_eq!(seen["hook_event_name"], "UserPromptSubmit");
    assert_eq!(seen["session_id"], "s1");
    assert_eq!(seen["prompt"], "héllo");
    assert_eq!(seen["cwd"], rig.project.to_str().expect("utf8"));
}

#[test]
fn the_context_of_the_hook_specific_form_is_read_too() {
    let (_, runner) = with_hooks(
        "context-nested",
        one(
            "SessionStart",
            "echo '{\"hookSpecificOutput\": {\"additionalContext\": \"on branch x\"}}'",
            5,
        ),
    );
    let out = runner.run("SessionStart", &Map::new(), "");
    assert_eq!(out.context, ["on branch x"]);
}

#[test]
fn exit_code_2_blocks_with_what_the_hook_wrote_on_standard_error() {
    let (_, runner) = with_hooks("exit2", one("PreToolUse", "echo 'not here' >&2; exit 2", 5));
    let out = runner.run("PreToolUse", &Map::new(), "Bash");
    assert!(out.blocked);
    assert_eq!(out.reason, "not here");
}

#[test]
fn a_json_decision_blocks() {
    let (_, runner) = with_hooks(
        "json-block",
        one(
            "PreToolUse",
            "echo '{\"decision\": \"block\", \"reason\": \"frozen\"}'",
            5,
        ),
    );
    let out = runner.run("PreToolUse", &Map::new(), "Write");
    assert!(out.blocked && out.reason == "frozen");
    let (_, bare) = with_hooks(
        "again",
        one("PreToolUse", "echo '{\"decision\": \"block\"}'", 5),
    );
    let out = bare.run("PreToolUse", &Map::new(), "Write");
    assert!(out.blocked && out.reason == "blocked by a hook");
}

#[test]
fn the_matcher_selects_tools_and_the_first_block_ends_the_run() {
    let (rig, runner) = with_hooks(
        "matcher",
        json!({"PreToolUse": [
            {"matcher": "Bash|Write", "hooks": [
                {"type": "command", "command": "touch first; exit 2"},
                {"type": "command", "command": "touch second"}]},
            {"matcher": "", "hooks": [{"type": "command", "command": "touch third"}]}]}),
    );
    let read = runner.run("PreToolUse", &Map::new(), "Read");
    assert!(!read.blocked);
    assert!(
        !exists(&rig.project.join("first")),
        "the matcher did not fit Read"
    );
    assert!(
        exists(&rig.project.join("third")),
        "an empty matcher fits every tool"
    );
    std::fs::remove_file(rig.project.join("third")).expect("clean");
    let bash = runner.run("PreToolUse", &Map::new(), "bash");
    assert!(bash.blocked, "matching ignores case");
    assert!(exists(&rig.project.join("first")));
    assert!(!exists(&rig.project.join("second")) && !exists(&rig.project.join("third")));
}

#[test]
fn a_matcher_is_the_whole_name_not_a_part_of_it() {
    let (rig, runner) = with_hooks(
        "matcher-whole",
        json!({"PreToolUse": [{"matcher": "Write", "hooks": [
            {"type": "command", "command": "touch ran"}]}]}),
    );
    runner.run("PreToolUse", &Map::new(), "WriteAll");
    assert!(!exists(&rig.project.join("ran")));
    runner.run("PreToolUse", &Map::new(), "Write");
    assert!(exists(&rig.project.join("ran")));
}

#[test]
fn a_timeout_kills_the_group_and_does_not_block() {
    let (rig, runner) = with_hooks(
        "timeout",
        json!({"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "sleep 30 & echo $! > pid; wait", "timeout": 0.5}]}]}),
    );
    let started = Instant::now();
    let out = runner.run("Stop", &Map::new(), "");
    assert!(started.elapsed() < Duration::from_secs(10));
    assert!(!out.blocked);
    assert!(
        out.warnings.iter().any(|w| w.contains("timed out")),
        "{out:?}"
    );
    let pid = std::fs::read_to_string(rig.project.join("pid")).expect("pid");
    std::thread::sleep(Duration::from_millis(200));
    assert!(
        !std::path::Path::new(&format!("/proc/{}", pid.trim())).exists(),
        "the child the hook started is gone too"
    );
}

#[test]
fn failures_and_malformed_output_warn_but_never_block() {
    for (command, fragment) in [
        ("exit 1", "exited with code 1"),
        ("echo oops >&2; exit 3", "oops"),
        ("echo 'not json'", "not a JSON object"),
        ("echo '[1, 2]'", "not a JSON object"),
        ("echo '{broken'", "not a JSON object"),
        ("exit 0 | nonexistent_command_zz", "code"),
    ] {
        let (_, runner) = with_hooks("warn", one("UserPromptSubmit", command, 5));
        let out = runner.run("UserPromptSubmit", &Map::new(), "");
        assert!(!out.blocked, "{command}");
        assert!(
            out.warnings.iter().any(|w| w.contains(fragment)),
            "{command}: {:?}",
            out.warnings
        );
    }
}

#[test]
fn warnings_and_blocks_are_kept_for_the_front_end() {
    let (_, runner) = with_hooks("notices", one("PreToolUse", "echo 'no' >&2; exit 2", 5));
    runner.run("PreToolUse", &Map::new(), "Bash");
    let notices = runner.drain();
    assert!(
        notices
            .iter()
            .any(|n| n.kind == "blocked" && n.text == "no")
    );
    assert!(runner.drain().is_empty(), "drained once");
}

#[test]
fn output_that_is_not_utf8_is_a_warning_not_a_crash() {
    let (_, runner) = with_hooks(
        "not-utf8",
        one("UserPromptSubmit", "printf '\\xff\\xfe\\x80{'", 5),
    );
    let out = runner.run("UserPromptSubmit", &Map::new(), "");
    assert!(!out.blocked && out.ran == 1 && !out.warnings.is_empty());
    let (_, runner) = with_hooks(
        "again",
        one("PreToolUse", "printf '\\xff\\xfe no' >&2; exit 2", 5),
    );
    let out = runner.run("PreToolUse", &Map::new(), "Bash");
    assert!(out.blocked && out.reason.contains("no"));
}

#[test]
fn a_flood_of_output_is_cut_and_does_not_stall() {
    let (_, runner) = with_hooks(
        "flood",
        one(
            "UserPromptSubmit",
            "head -c 200000000 /dev/zero | tr '\\0' 'a'",
            20,
        ),
    );
    let started = Instant::now();
    let out = runner.run("UserPromptSubmit", &Map::new(), "");
    assert!(started.elapsed() < Duration::from_secs(15));
    assert!(!out.blocked && !out.warnings.is_empty());
    assert!(
        out.warnings[0].len() < 400,
        "a warning quotes a few characters, not the flood"
    );
    let (_, runner) = with_hooks(
        "again",
        one(
            "PreToolUse",
            "head -c 5000000 /dev/zero | tr '\\0' 'x' >&2; exit 2",
            20,
        ),
    );
    let out = runner.run("PreToolUse", &Map::new(), "Bash");
    assert!(out.blocked && out.reason.chars().count() <= OUTPUT_CAP);
}

#[test]
fn a_hook_that_ignores_its_input_does_not_stall_the_session() {
    let (_, runner) = with_hooks("no-read", one("UserPromptSubmit", "true", 5));
    let big = payload(json!({"prompt": "x".repeat(3_000_000)}));
    let started = Instant::now();
    let out = runner.run("UserPromptSubmit", &big, "");
    assert!(out.ran == 1 && out.warnings.is_empty());
    assert!(started.elapsed() < Duration::from_secs(5));
}

#[test]
fn a_hook_that_leaves_a_child_holding_its_pipes_is_not_waited_for() {
    let (rig, runner) = with_hooks(
        "lingering",
        one("Stop", "sleep 30 & echo $! > pid; echo done", 5),
    );
    let started = Instant::now();
    let out = runner.run("Stop", &Map::new(), "");
    assert!(started.elapsed() < Duration::from_secs(8));
    assert!(!out.blocked);
    let pid = std::fs::read_to_string(rig.project.join("pid")).expect("pid");
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        !std::path::Path::new(&format!("/proc/{}", pid.trim())).exists(),
        "the lingering child was killed with its group"
    );
}

#[test]
fn control_characters_cannot_reach_the_terminal() {
    let escapes = "\u{1b}]52;c;aGk=\u{7}\u{1b}[2J\u{1b}]0;pwned\u{7}\u{9b}31m\u{8}\u{0}";
    assert_eq!(clean(escapes), "]52;c;aGk=[2J]0;pwned31m");
    assert_eq!(clean("a\tb\nc"), "a\tb\nc");
    let (_, runner) = with_hooks(
        "escapes",
        one(
            "UserPromptSubmit",
            "printf '{\"additionalContext\": \"ok\\\\u001b[2Jtext\"}'",
            5,
        ),
    );
    let out = runner.run("UserPromptSubmit", &Map::new(), "");
    assert_eq!(out.context, ["ok[2Jtext"]);
    let (_, runner) = with_hooks(
        "again",
        one(
            "PreToolUse",
            "printf '\\033]0;pwned\\007bad' >&2; exit 2",
            5,
        ),
    );
    let out = runner.run("PreToolUse", &Map::new(), "Bash");
    assert_eq!(out.reason, "]0;pwnedbad");
}

#[test]
fn hooks_run_in_the_project_with_a_clean_environment() {
    let rig = rig("env");
    // a secret in this process's environment does not reach a hook
    assert_run_under_cargo();
    let runner = runner_in(
        &rig,
        one("SessionStart", "pwd > out; env | sort >> out", 5),
        |s| {
            s.env.insert("TEAM".to_owned(), "lab".to_owned());
        },
    );
    runner.run("SessionStart", &Map::new(), "");
    let text = std::fs::read_to_string(rig.project.join("out")).expect("out");
    assert!(
        text.starts_with(rig.project.to_str().expect("utf8")),
        "{text}"
    );
    for wanted in [
        "TEAM=lab",
        "LARIS_HOOK_EVENT=SessionStart",
        "LARIS_SESSION_ID=s1",
        &format!("LARIS_PROJECT_DIR={}", rig.project.display()),
    ] {
        assert!(text.contains(wanted), "{wanted} in {text}");
    }
    assert!(
        !text.contains("CARGO"),
        "the build's own environment is not passed on: {text}"
    );
}

/// The test process has cargo's variables; the check above relies on that.
fn assert_run_under_cargo() {
    assert!(
        std::env::vars().any(|(k, _)| k.starts_with("CARGO")),
        "run under cargo"
    );
}

#[test]
fn an_unknown_event_runs_nothing() {
    let (rig, runner) = with_hooks("unknown-event", one("Stop", "touch ran", 5));
    runner.run("Whenever", &Map::new(), "");
    assert!(!exists(&rig.project.join("ran")));
}
