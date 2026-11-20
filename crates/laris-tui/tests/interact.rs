//! Approvals, the login form, history search, completion and the diff block through the interface (T158, SR-C1,
//! SR-C2). The golden scenarios `approval`, `refusal`, `login`, `login_trust` and `completion` are replayed in
//! `render.rs`; here the keys and the screens are checked one by one.

#![allow(missing_docs)]

mod common;

use common::play;
use laris_config::settings::Ui;
use laris_protocol::Command;
use laris_protocol::Event;
use laris_protocol::events::{Decision, LoginReason, Scope, Trigger};
use laris_tui::width::str_width;
use laris_tui::{App, Input, Item, Key};
use serde_json::{Map, Value, json};

const WIDTHS: [usize; 2] = [60, 100];

fn app() -> App {
    App::new(&Ui::default())
}

fn feed(app: &mut App, event: Event) {
    app.update(Input::Event(event));
}

fn key(app: &mut App, k: Key) -> Vec<Command> {
    app.update(Input::Key(k))
}

fn type_text(app: &mut App, text: &str) {
    for c in text.chars() {
        key(app, Key::Char(c));
    }
}

fn request(scopes: &[&str], diff: &str) -> Event {
    Event::PermissionRequest {
        id: "p1".into(),
        tool: "Write".into(),
        arguments: json!({"path": "a.txt"})
            .as_object()
            .cloned()
            .unwrap_or_default(),
        reason: "writes a file".into(),
        rule: "Write(a.txt)".into(),
        diff: diff.into(),
        scopes: scopes.iter().map(|s| (*s).to_owned()).collect(),
    }
}

const DIFF: &str = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1,2 @@\n-old\n+new\n+more";

fn response(commands: &[Command]) -> (Decision, Scope, bool) {
    match commands {
        [
            Command::PermissionResponse {
                decision,
                scope,
                remember,
                ..
            },
        ] => (*decision, *scope, *remember),
        other => panic!("expected one permission_response, got {other:?}"),
    }
}

// -- approvals -------------------------------------------------------------------------------

#[test]
fn an_approval_shows_the_call_the_diff_and_the_choices_in_place_of_the_input_box() {
    for width in WIDTHS {
        let mut a = app();
        feed(
            &mut a,
            request(&["once", "session", "project", "everywhere"], DIFF),
        );
        let screen = a.screen_text(width);
        for want in [
            "Allow Write?",
            "path: \"a.txt\"",
            "writes a file",
            "rule: Write(a.txt)",
            "+2 −1",
            "-old",
            "+new",
            "❯ 1. Yes, this once",
            "2. Yes, for this session",
            "3. Yes, for this project",
            "4. Yes, everywhere",
            "5. No",
            "esc deny",
        ] {
            assert!(
                screen.contains(want),
                "{want:?} missing at {width}:\n{screen}"
            );
        }
        assert!(
            !screen.contains("Type a message"),
            "no input box while asked:\n{screen}"
        );
        assert!(screen.lines().all(|l| str_width(l) <= width), "{screen}");
        assert!(a.layout(width).cursor.is_none());
    }
}

#[test]
fn the_keys_answer_an_approval() {
    let ask = |scopes: &[&str]| {
        let mut a = app();
        feed(&mut a, request(scopes, DIFF));
        a
    };
    let all = ["once", "session", "project", "everywhere"];
    // Enter takes the highlighted choice: once
    let mut a = ask(&all);
    assert_eq!(
        response(&key(&mut a, Key::Enter)),
        (Decision::Allow, Scope::Once, false)
    );
    assert!(a.approval().is_none());
    // y is once, n and Esc and Ctrl+C refuse
    let mut a = ask(&all);
    assert_eq!(
        response(&key(&mut a, Key::Char('y'))),
        (Decision::Allow, Scope::Once, false)
    );
    for refusing in [Key::Char('n'), Key::Esc, Key::CtrlC] {
        let mut a = ask(&all);
        assert_eq!(
            response(&key(&mut a, refusing)).0,
            Decision::Deny,
            "{refusing:?}"
        );
    }
    // arrows then Enter: the wider scopes remember
    let mut a = ask(&all);
    key(&mut a, Key::Down);
    key(&mut a, Key::Down);
    assert_eq!(
        response(&key(&mut a, Key::Enter)),
        (Decision::Allow, Scope::Project, true)
    );
    // a digit answers at once
    let mut a = ask(&all);
    assert_eq!(
        response(&key(&mut a, Key::Char('4'))),
        (Decision::Allow, Scope::Everywhere, true)
    );
    // only the scopes the core offers are offered
    let mut a = ask(&["once"]);
    assert_eq!(a.approval().map(|p| p.choices.len()), Some(2));
    assert!(key(&mut a, Key::Char('4')).is_empty(), "no fourth choice");
    assert!(a.approval().is_some());
    // other keys change nothing and cannot type into the hidden input box
    assert!(key(&mut a, Key::Char('x')).is_empty());
    assert_eq!(a.input_text(), "");
    // Ctrl+D does not leave while a call waits
    assert!(key(&mut a, Key::CtrlD).is_empty());
    assert!(!a.should_quit());
}

#[test]
fn an_answered_approval_leaves_its_diff_and_the_answer_in_the_conversation() {
    let mut a = app();
    feed(&mut a, request(&["once"], DIFF));
    key(&mut a, Key::Char('n'));
    let items = a.items();
    assert!(
        items
            .iter()
            .any(|i| matches!(i, Item::Diff(d) if d == DIFF))
    );
    let screen = a.screen_text(80);
    assert!(screen.contains("Write: No"), "{screen}");
    assert!(screen.contains("+new"), "{screen}");
    assert!(
        screen.contains("Type a message"),
        "the input box is back:\n{screen}"
    );
}

#[test]
fn a_long_diff_is_cut_with_a_count_and_every_row_fits() {
    let mut diff = String::from("--- a\n+++ b\n@@ -1,40 +1,40 @@\n");
    for i in 0..40 {
        diff.push_str(&format!("+line {i} {}\n", "x".repeat(90)));
    }
    let mut a = app();
    feed(&mut a, request(&["once"], &diff));
    for width in [30, 60, 100] {
        let screen = a.screen_text(width);
        assert!(screen.contains("more lines"), "{screen}");
        assert!(
            screen.lines().all(|l| str_width(l) <= width),
            "{width}:\n{screen}"
        );
    }
}

#[test]
fn control_characters_in_a_request_cannot_reach_the_terminal() {
    let mut a = app();
    let mut arguments = Map::new();
    arguments.insert("path".into(), Value::String("a\x1b[31m.txt".into()));
    feed(
        &mut a,
        Event::PermissionRequest {
            id: "p".into(),
            tool: "Wri\x1bte".into(),
            arguments,
            reason: "bad\x07 reason".into(),
            rule: "r\x1b".into(),
            diff: "+\x1b[2Jevil".into(),
            scopes: vec!["once".into()],
        },
    );
    let screen = a.screen_text(80);
    assert!(
        !screen.chars().any(|c| c.is_control() && c != '\n'),
        "{screen:?}"
    );
}

// -- login -----------------------------------------------------------------------------------

#[test]
fn the_login_form_never_shows_or_keeps_the_key() {
    let mut a = app();
    feed(
        &mut a,
        Event::LoginRequired {
            reason: LoginReason::NoKey,
            server: "https://laris.example".into(),
            fingerprint: String::new(),
            message: String::new(),
        },
    );
    type_text(&mut a, "lk_secret_key");
    for width in WIDTHS {
        let screen = a.screen_text(width);
        assert!(
            screen.contains("Sign in to https://laris.example"),
            "{screen}"
        );
        assert!(screen.contains(&"•".repeat(13)), "{screen}");
        assert!(
            !screen.contains("lk_secret"),
            "the key is on screen:\n{screen}"
        );
    }
    assert!(
        !format!("{a:?}").contains("lk_secret"),
        "the key is in the Debug text"
    );
    assert_eq!(
        a.input_text(),
        "",
        "the key does not go into the chat input"
    );
    let sent = key(&mut a, Key::Enter);
    assert!(
        matches!(&sent[..], [Command::Login { key, .. }] if key == "lk_secret_key"),
        "{sent:?}"
    );
    // sent: the field is empty and the form waits for the answer
    assert_eq!(a.sign_in().map(laris_tui::SignIn::typed), Some(0));
    assert!(a.screen_text(80).contains("Checking the key"));
    assert!(key(&mut a, Key::Char('x')).is_empty());
    assert_eq!(a.sign_in().map(laris_tui::SignIn::typed), Some(0));
    // a refused key opens the form again, with the reason
    feed(
        &mut a,
        Event::LoginRequired {
            reason: LoginReason::Rejected,
            server: "https://laris.example".into(),
            fingerprint: String::new(),
            message: String::new(),
        },
    );
    let screen = a.screen_text(80);
    assert!(screen.contains("did not accept this key"), "{screen}");
    assert!(!a.sign_in().is_some_and(|f| f.waiting));
    // pasting a key works the same and is masked too
    a.update(Input::Paste("lk_pasted".into()));
    assert!(!a.screen_text(80).contains("lk_pasted"));
}

#[test]
fn the_login_form_closes_when_the_session_is_ready_and_chat_goes_on() {
    let played = play("login", 80, false).unwrap();
    assert!(played.app.sign_in().is_none());
    assert!(played.snapshots.last().unwrap().screen.contains("Hi."));
    // the first screens are the form
    assert!(
        played.snapshots[0]
            .screen
            .contains("Sign in to https://laris.example")
    );
    assert!(
        played.snapshots[1]
            .screen
            .contains("did not accept this key")
    );
}

#[test]
fn a_certificate_fingerprint_is_confirmed_with_y_and_refused_with_n() {
    let play_to_trust = || {
        let mut a = app();
        feed(
            &mut a,
            Event::LoginRequired {
                reason: LoginReason::UntrustedCertificate,
                server: "https://laris.internal:8443".into(),
                fingerprint: "SHA256:AB:CD:EF".into(),
                message: String::new(),
            },
        );
        a
    };
    let mut a = play_to_trust();
    assert!(a.screen_text(80).contains("SHA256:AB:CD:EF"));
    let sent = key(&mut a, Key::Char('y'));
    assert!(
        matches!(&sent[..], [Command::Login { trust: true, .. }]),
        "{sent:?}"
    );
    let mut a = play_to_trust();
    assert!(matches!(
        &key(&mut a, Key::Char('n'))[..],
        [Command::Shutdown {}]
    ));
    assert!(a.should_quit());
}

#[test]
fn esc_and_ctrl_c_leave_the_login_form() {
    for leave in [Key::Esc, Key::CtrlC, Key::CtrlD] {
        let mut a = app();
        feed(
            &mut a,
            Event::LoginRequired {
                reason: LoginReason::NoKey,
                server: "s".into(),
                fingerprint: String::new(),
                message: String::new(),
            },
        );
        assert!(matches!(&key(&mut a, leave)[..], [Command::Shutdown {}]));
        assert!(a.should_quit());
    }
}

// -- history search --------------------------------------------------------------------------

#[test]
fn ctrl_r_searches_the_history_and_enter_takes_the_match() {
    let mut a = app();
    for line in ["first question", "run the tests", "second question"] {
        type_text(&mut a, line);
        key(&mut a, Key::Enter);
        feed(
            &mut a,
            Event::Done {
                status: "completed".into(),
                answer: String::new(),
            },
        );
    }
    key(&mut a, Key::CtrlR);
    assert!(a.screen_text(80).contains("history search:"));
    // empty query: the newest
    assert_eq!(a.search().and_then(|s| s.found), Some(2));
    type_text(&mut a, "tests");
    let screen = a.screen_text(80);
    assert!(screen.contains("history search: tests"), "{screen}");
    assert!(
        screen.contains("run the tests"),
        "the match is shown in the box:\n{screen}"
    );
    assert_eq!(a.input_text(), "", "the box is only previewed until Enter");
    key(&mut a, Key::Enter);
    assert_eq!(a.input_text(), "run the tests");
    assert!(a.search().is_none());
    // Ctrl+R again goes to an older match; Esc leaves the box as it was
    a.clear_input();
    key(&mut a, Key::CtrlR);
    type_text(&mut a, "question");
    assert_eq!(a.search().and_then(|s| s.found), Some(2));
    key(&mut a, Key::CtrlR);
    assert_eq!(a.search().and_then(|s| s.found), Some(0));
    key(&mut a, Key::Esc);
    assert_eq!(a.input_text(), "");
    // no match says so; Enter then changes nothing
    key(&mut a, Key::CtrlR);
    type_text(&mut a, "zzz");
    assert!(a.screen_text(80).contains("no match"));
    key(&mut a, Key::Enter);
    assert_eq!(a.input_text(), "");
}

#[test]
fn ctrl_r_with_nothing_sent_does_nothing() {
    let mut a = app();
    assert!(key(&mut a, Key::CtrlR).is_empty());
    assert!(a.search().is_none());
}

// -- completion ------------------------------------------------------------------------------

fn completion(id: &str, items: &[(&str, &str)]) -> Event {
    Event::Completion {
        id: id.into(),
        items: items
            .iter()
            .map(|(v, d)| laris_protocol::events::CompletionItem {
                value: (*v).into(),
                description: (*d).into(),
            })
            .collect(),
    }
}

#[test]
fn tab_asks_for_completions_of_a_slash_word_and_of_an_at_word() {
    let mut a = app();
    type_text(&mut a, "/he");
    let sent = key(&mut a, Key::Tab);
    assert!(
        matches!(&sent[..], [Command::Complete { trigger: Trigger::Slash, text, .. }] if text == "he"),
        "{sent:?}"
    );
    a.clear_input();
    type_text(&mut a, "read @src/ma");
    let sent = key(&mut a, Key::Tab);
    assert!(
        matches!(&sent[..], [Command::Complete { trigger: Trigger::At, text, .. }] if text == "src/ma"),
        "{sent:?}"
    );
    // a slash that is not the first word, and an ordinary word, ask nothing
    a.clear_input();
    type_text(&mut a, "see /he");
    assert!(key(&mut a, Key::Tab).is_empty());
    a.clear_input();
    type_text(&mut a, "word");
    assert!(key(&mut a, Key::Tab).is_empty());
}

#[test]
fn one_candidate_is_inserted_and_several_open_a_menu() {
    let mut a = app();
    type_text(&mut a, "/he");
    let id = match &key(&mut a, Key::Tab)[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion(&id, &[("help", "list commands")]));
    assert_eq!(a.input_text(), "/help ");
    // several
    a.clear_input();
    type_text(&mut a, "look at @sr");
    let id = match &key(&mut a, Key::Tab)[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(
        &mut a,
        completion(&id, &[("src/", "folder"), ("srv.py", "")]),
    );
    let screen = a.screen_text(80);
    assert!(
        screen.contains("❯ src/") && screen.contains("folder") && screen.contains("srv.py"),
        "{screen}"
    );
    assert_eq!(
        a.input_text(),
        "look at @sr",
        "the text is not changed until a choice"
    );
    key(&mut a, Key::Tab);
    assert_eq!(a.menu().map(|m| m.selected), Some(1));
    key(&mut a, Key::Up);
    key(&mut a, Key::Enter);
    // a folder keeps the word open for the next part of the path
    assert_eq!(a.input_text(), "look at @src/");
    assert!(a.menu().is_none());
}

#[test]
fn a_menu_closes_on_esc_and_on_any_other_key_which_still_types() {
    let mut a = app();
    type_text(&mut a, "/");
    let id = match &key(&mut a, Key::Tab)[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion(&id, &[("help", ""), ("mode", "")]));
    key(&mut a, Key::Esc);
    assert!(a.menu().is_none());
    assert_eq!(a.input_text(), "/");
    // reopen and type on
    let id = match &key(&mut a, Key::Tab)[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion(&id, &[("help", ""), ("mode", "")]));
    let sent = key(&mut a, Key::Char('m'));
    assert!(
        matches!(&sent[..], [Command::Complete { text, .. }] if text == "m"),
        "{sent:?}"
    );
    assert_eq!(a.input_text(), "/m");
}

#[test]
fn suggestions_follow_each_character_typed() {
    let mut a = app();
    // `/` alone already asks, and the answer opens the menu without a Tab
    let sent = key(&mut a, Key::Char('/'));
    let id = match &sent[..] {
        [
            Command::Complete {
                id,
                trigger: Trigger::Slash,
                text,
            },
        ] if text.is_empty() => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(
        &mut a,
        completion(&id, &[("help", "list"), ("mode", "mode")]),
    );
    assert_eq!(a.menu().map(|m| m.items.len()), Some(2));
    assert_eq!(
        a.input_text(),
        "/",
        "the text is not changed by suggestions"
    );
    // each character narrows: a new request, and the menu follows its answer
    let sent = key(&mut a, Key::Char('m'));
    let id = match &sent[..] {
        [Command::Complete { id, text, .. }] if text == "m" => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion(&id, &[("mode", "mode")]));
    assert_eq!(a.menu().map(|m| m.items.len()), Some(1));
    assert!(a.screen_text(80).contains("❯ mode"));
    // Enter takes the highlighted suggestion; a second Enter sends it
    key(&mut a, Key::Enter);
    assert_eq!(a.input_text(), "/mode ");
    assert!(a.menu().is_none());
    // no match closes the menu without a message; an ordinary word asks nothing
    a.clear_input();
    let sent = key(&mut a, Key::Char('/'));
    let id = match &sent[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion(&id, &[("help", "")]));
    let sent = key(&mut a, Key::Char('z'));
    let id = match &sent[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion(&id, &[]));
    assert!(a.menu().is_none());
    assert!(!a.screen_text(80).contains("nothing matches"));
    a.clear_input();
    assert!(key(&mut a, Key::Char('w')).is_empty());
    // Backspace back to nothing closes the menu
    a.clear_input();
    key(&mut a, Key::Char('/'));
    assert!(key(&mut a, Key::Backspace).is_empty());
    assert!(a.menu().is_none());
}

#[test]
fn nothing_to_complete_says_so_and_a_stale_answer_is_ignored() {
    let mut a = app();
    type_text(&mut a, "/zz");
    let id = match &key(&mut a, Key::Tab)[..] {
        [Command::Complete { id, .. }] => id.clone(),
        other => panic!("{other:?}"),
    };
    feed(&mut a, completion("other", &[("x", "")]));
    assert_eq!(
        a.input_text(),
        "/zz",
        "an answer to another request changes nothing"
    );
    feed(&mut a, completion(&id, &[]));
    assert!(a.screen_text(80).contains("nothing matches"));
    assert_eq!(a.input_text(), "/zz");
}

// -- local commands --------------------------------------------------------------------------

#[test]
fn exit_and_quit_leave_and_clear_empties_the_view_only() {
    for word in ["/exit", "/quit"] {
        let mut a = app();
        type_text(&mut a, word);
        assert!(matches!(
            &key(&mut a, Key::Enter)[..],
            [Command::Shutdown {}]
        ));
        assert!(a.should_quit());
    }
    let mut a = app();
    type_text(&mut a, "hello");
    key(&mut a, Key::Enter);
    type_text(&mut a, "/clear");
    assert!(
        key(&mut a, Key::Enter).is_empty(),
        "nothing goes to the core"
    );
    assert!(a.take_clear());
    assert!(!a.take_clear(), "only once");
    assert!(!a.screen_text(80).contains("> hello"));
    assert!(a.screen_text(80).contains("Screen cleared"));
}

#[test]
fn other_slash_commands_go_to_the_core_with_their_arguments() {
    let mut a = app();
    type_text(&mut a, "/mode  plan ");
    let sent = key(&mut a, Key::Enter);
    assert!(
        matches!(&sent[..], [Command::Slash { name, args }] if name == "mode" && args == "plan"),
        "{sent:?}"
    );
}

#[test]
fn a_scenario_can_be_replayed_at_every_width_with_the_overlays() {
    for name in ["approval", "refusal", "completion", "login", "login_trust"] {
        for width in [20, 33, 60, 100, 160] {
            let played = play(name, width, false).unwrap_or_else(|e| panic!("{name}: {e}"));
            for snap in &played.snapshots {
                assert!(
                    snap.screen.lines().all(|l| str_width(l) <= width),
                    "{name} @ {width} step {}:\n{}",
                    snap.step,
                    snap.screen
                );
            }
        }
    }
}

#[test]
fn a_message_typed_while_the_agent_works_waits_below_the_conversation_until_it_starts() {
    let mut a = app();
    type_text(&mut a, "first");
    key(&mut a, Key::Enter);
    type_text(&mut a, "second  one");
    let sent = key(&mut a, Key::Enter);
    assert!(matches!(&sent[..], [Command::UserMessage { .. }]));
    let screen = a.screen_text(80);
    assert!(
        screen.contains("> second  one (queued)") || screen.contains("> second one (queued)"),
        "{screen}"
    );
    assert_eq!(
        a.items()
            .iter()
            .filter(|i| matches!(i, Item::User(_)))
            .count(),
        1
    );
    // the core taking the first message says nothing about the second
    feed(&mut a, status_started("first", 1));
    assert!(a.screen_text(80).contains("(queued)"));
    // the answer to the first, then the second starts (spaces are not compared)
    feed(
        &mut a,
        Event::Done {
            status: "completed".into(),
            answer: "ok".into(),
        },
    );
    assert!(a.running(), "a message is waiting, so work goes on");
    feed(&mut a, status_started("second one", 0));
    let screen = a.screen_text(80);
    assert!(!screen.contains("(queued)"), "{screen}");
    assert!(screen.contains("> second  one"), "{screen}");
    // a failed command leaves nothing running when nothing waits
    feed(
        &mut a,
        Event::Done {
            status: "completed".into(),
            answer: "ok".into(),
        },
    );
    assert!(!a.running());
}

fn status_started(text: &str, count: u64) -> Event {
    Event::Status {
        kind: "queued".into(),
        data: json!({"count": count, "started": text})
            .as_object()
            .cloned()
            .unwrap(),
    }
}
