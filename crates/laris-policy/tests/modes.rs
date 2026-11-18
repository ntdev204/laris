//! Modes and precedence: what each mode lets through, deny wins, bypass is bounded, answers are kept.

mod common;

use common::{args, permissions, rig};
use laris_config::settings::{PermissionMode, Permissions};
use laris_policy::{Remember, Verdict, mode_name};
use serde_json::json;

fn write() -> serde_json::Map<String, serde_json::Value> {
    args(json!({"path": "src/a.py", "content": "x"}))
}

#[test]
fn the_default_mode_asks_for_changes_and_lets_reads_through() {
    let r = rig("default");
    let e = r.engine();
    assert_eq!(e.decide("Write", &write(), true).verdict, Verdict::Ask);
    assert_eq!(
        e.decide("Bash", &args(json!({"command": "make"})), true)
            .verdict,
        Verdict::Ask
    );
    assert_eq!(
        e.decide("Read", &args(json!({"path": "a"})), false).verdict,
        Verdict::Allow
    );
}

#[test]
fn accept_edits_lets_edits_through_and_still_asks_for_the_rest() {
    let r = rig("accept-edits");
    let e = r.engine();
    e.set_mode(PermissionMode::AcceptEdits).expect("mode");
    assert_eq!(e.decide("Write", &write(), true).verdict, Verdict::Allow);
    assert_eq!(e.decide("Edit", &write(), true).verdict, Verdict::Allow);
    assert_eq!(
        e.decide("Bash", &args(json!({"command": "make"})), true)
            .verdict,
        Verdict::Ask
    );
    assert_eq!(
        e.decide("save_memory", &args(json!({"text": "x"})), true)
            .verdict,
        Verdict::Ask
    );
}

#[test]
fn plan_mode_is_read_only_and_no_rule_changes_that() {
    let r = rig("plan");
    let e = r.engine_with(permissions(&["Write", "Bash"], &[], &[]), false);
    e.set_mode(PermissionMode::Plan).expect("mode");
    let refused = e.decide("Write", &write(), true);
    assert_eq!(refused.verdict, Verdict::Deny);
    assert!(refused.reason.contains("read-only"));
    assert_eq!(
        e.decide("Bash", &args(json!({"command": "ls"})), true)
            .verdict,
        Verdict::Deny
    );
    assert_eq!(
        e.decide("Read", &args(json!({"path": "a"})), false).verdict,
        Verdict::Allow
    );
}

#[test]
fn bypass_needs_the_policy_and_never_beats_deny_or_ask() {
    let r = rig("bypass");
    let refused = r.engine();
    assert!(refused.set_mode(PermissionMode::Bypass).is_err());
    assert_ne!(refused.mode(), PermissionMode::Bypass);

    let e = r.engine_with(permissions(&[], &["Bash(rm:*)"], &["Write(src/**)"]), true);
    e.set_mode(PermissionMode::Bypass).expect("allowed here");
    assert_eq!(e.decide("Write", &write(), true).verdict, Verdict::Deny);
    assert_eq!(
        e.decide(
            "Write",
            &args(json!({"path": "docs/a.md", "content": "x"})),
            true
        )
        .verdict,
        Verdict::Allow
    );
    assert_eq!(
        e.decide("Bash", &args(json!({"command": "rm -rf x"})), true)
            .verdict,
        Verdict::Ask
    );
    assert_eq!(
        e.decide("Bash", &args(json!({"command": "ls"})), true)
            .verdict,
        Verdict::Allow
    );
}

#[test]
fn bypass_in_the_settings_is_ignored_without_the_policy() {
    let r = rig("bypass-setting");
    let wants = Permissions {
        default_mode: PermissionMode::Bypass,
        ..Permissions::default()
    };
    let without = r.engine_with(wants.clone(), false);
    assert_eq!(without.mode(), PermissionMode::Default);
    assert_eq!(
        without.decide("Write", &write(), true).verdict,
        Verdict::Ask
    );
    let with = r.engine_with(wants, true);
    assert_eq!(with.mode(), PermissionMode::Bypass);
}

#[test]
fn deny_wins_over_ask_and_allow() {
    let r = rig("precedence");
    let e = r.engine_with(
        permissions(&["Write"], &["Write(src/**)"], &["Write(src/secret/**)"]),
        false,
    );
    let at = |path: &str| e.decide("Write", &args(json!({"path": path, "content": "x"})), true);
    let denied = at("src/secret/k");
    assert_eq!(denied.verdict, Verdict::Deny);
    assert_eq!(denied.rule.as_deref(), Some("Write(src/secret/**)"));
    assert!(denied.reason.contains("denied by rule"));
    assert_eq!(at("src/a.py").verdict, Verdict::Ask);
    assert_eq!(at("docs/a.md").verdict, Verdict::Allow);
}

#[test]
fn deny_holds_in_every_mode_and_against_session_and_project_allows() {
    let r = rig("deny-always");
    let e = r.engine_with(permissions(&[], &[], &["Write(secret/**)"]), true);
    e.remember("Write", Remember::Session).expect("session");
    e.remember("Write", Remember::Project).expect("project");
    for mode in [
        PermissionMode::Default,
        PermissionMode::AcceptEdits,
        PermissionMode::Plan,
        PermissionMode::Bypass,
    ] {
        e.set_mode(mode).expect("mode");
        let d = e.decide(
            "Write",
            &args(json!({"path": "secret/k", "content": "x"})),
            true,
        );
        assert_eq!(d.verdict, Verdict::Deny, "{}", mode_name(mode));
    }
}

#[test]
fn a_session_deny_rule_blocks_a_tool_for_one_run() {
    let r = rig("session-deny");
    let e = r.engine();
    e.deny_for_session("Bash");
    assert_eq!(
        e.decide("Bash", &args(json!({"command": "ls"})), true)
            .verdict,
        Verdict::Deny
    );
}

#[test]
fn saved_project_rules_apply_and_a_damaged_file_is_ignored() {
    let r = rig("project-rules");
    let e = r.engine();
    e.state().add_allow("Write(docs/**)").expect("save");
    let docs = args(json!({"path": "docs/a.md", "content": "x"}));
    assert_eq!(e.decide("Write", &docs, true).verdict, Verdict::Allow);
    std::fs::write(e.state().path(), "{not json").expect("damage");
    assert_eq!(e.decide("Write", &docs, true).verdict, Verdict::Ask);
    // and the state can be written again over the damage
    e.state().add_allow("Write(docs/**)").expect("save again");
    assert_eq!(e.decide("Write", &docs, true).verdict, Verdict::Allow);
}

#[test]
fn the_mode_follows_the_settings_until_one_is_chosen() {
    let r = rig("mode-follows");
    let e = r.engine();
    assert_eq!(e.mode(), PermissionMode::Default);
    e.set_permissions(Permissions {
        default_mode: PermissionMode::AcceptEdits,
        ..Permissions::default()
    });
    assert_eq!(e.mode(), PermissionMode::AcceptEdits);
    e.set_mode(PermissionMode::Plan).expect("mode");
    e.set_permissions(Permissions::default());
    assert_eq!(
        e.mode(),
        PermissionMode::Plan,
        "a choice of the session wins"
    );
}

#[test]
fn cycling_the_modes() {
    let r = rig("cycle");
    let e = r.engine();
    let seen: Vec<_> = (0..4).map(|_| mode_name(e.cycle())).collect();
    assert_eq!(seen, ["acceptEdits", "plan", "default", "acceptEdits"]);
    let allowed = r.engine_with(Permissions::default(), true);
    let seen: Vec<_> = (0..4).map(|_| mode_name(allowed.cycle())).collect();
    assert_eq!(seen, ["acceptEdits", "plan", "bypass", "default"]);
}

#[test]
fn answers_are_kept_for_the_session_the_folder_or_everywhere() {
    let r = rig("remember");
    let call = args(json!({"command": "git status -s"}));
    let e = r.engine();
    assert_eq!(e.decide("Bash", &call, true).verdict, Verdict::Ask);

    e.remember("bash(git status:*)", Remember::Session)
        .expect("session");
    assert_eq!(e.decide("Bash", &call, true).verdict, Verdict::Allow);
    // a fresh engine of the same folder has forgotten the session answer
    assert_eq!(r.engine().decide("Bash", &call, true).verdict, Verdict::Ask);

    e.remember("bash(git status:*)", Remember::Project)
        .expect("project");
    assert_eq!(
        r.engine().decide("Bash", &call, true).verdict,
        Verdict::Allow
    );
    assert!(
        r.home
            .join("projects")
            .read_dir()
            .expect("projects")
            .next()
            .is_some(),
        "kept in the home, not in the project"
    );
    assert!(!r.project.join(".laris").exists());

    let other = r.engine();
    let swap = args(json!({"command": "make test"}));
    assert_eq!(other.decide("Bash", &swap, true).verdict, Verdict::Ask);
    other
        .remember("bash(make:*)", Remember::Everywhere)
        .expect("settings");
    let saved: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(r.settings_file()).expect("file"))
            .expect("json");
    assert_eq!(saved["permissions"]["allow"], json!(["bash(make:*)"]));
    assert_eq!(other.decide("Bash", &swap, true).verdict, Verdict::Allow);
}

#[test]
fn saving_an_answer_twice_keeps_one_rule_and_other_settings_survive() {
    let r = rig("remember-twice");
    std::fs::write(
        r.settings_file(),
        r#"{"model": "m1", "permissions": {"deny": ["Bash(rm:*)"]}}"#,
    )
    .expect("settings");
    let e = r.engine();
    e.remember("read", Remember::Everywhere).expect("first");
    e.remember("read", Remember::Everywhere).expect("second");
    let saved: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(r.settings_file()).expect("file"))
            .expect("json");
    assert_eq!(saved["permissions"]["allow"], json!(["read"]));
    assert_eq!(saved["permissions"]["deny"], json!(["Bash(rm:*)"]));
    assert_eq!(saved["model"], "m1");
}

#[test]
fn a_bad_rule_or_a_missing_settings_file_is_refused() {
    let r = rig("remember-bad");
    let e = r.engine();
    assert!(e.remember("((", Remember::Session).is_err());
    let nowhere = laris_policy::Engine::new(
        Permissions::default(),
        r.scope(),
        laris_policy::ProjectState::new(&r.home, &r.project),
        None,
        false,
    );
    assert!(nowhere.remember("read", Remember::Everywhere).is_err());
}

#[test]
fn a_summary_names_the_mode_and_the_rules() {
    let r = rig("describe");
    let e = r.engine_with(permissions(&["Read"], &[], &["Bash(rm:*)"]), false);
    let text = e.describe();
    assert!(text.contains("mode: default (bypass not allowed)"));
    assert!(text.contains("deny: Bash(rm:*)"));
    assert!(text.contains("ask: (none)"));
    assert!(text.contains("allow: Read"));
}
