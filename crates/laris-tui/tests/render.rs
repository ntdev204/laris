//! Render tests at 60 and 100 columns, and the chat and interrupt scenarios through the interface (T157, SR-C1).
//! The recorded scenarios are the ones translated in T124; a screen is checked as text, and the snapshots under
//! `tests/snapshots/` are what the owner reviews (`LARIS_UPDATE_SNAPSHOTS=1` rewrites them).

#![allow(missing_docs)]

mod common;

use common::{SCENARIOS, play};
use laris_config::settings::Ui;
use laris_protocol::Command;
use laris_protocol::events::Mode;
use laris_tui::replay::replay;
use laris_tui::width::str_width;
use laris_tui::{App, Input, Key, Theme, ansi};

const WIDTHS: [usize; 2] = [60, 100];

fn snapshot(name: &str, width: usize, played: &laris_tui::replay::Replayed) -> String {
    played
        .snapshots
        .iter()
        .map(|s| format!("──── step {} ────\n{}", s.step, s.screen))
        .collect::<Vec<_>>()
        .join("")
        + &format!("──── {name} @ {width} ────\n")
}

fn check_snapshot(name: &str, width: usize, text: &str) {
    let path = format!(
        "{}/tests/snapshots/{name}_{width}.txt",
        env!("CARGO_MANIFEST_DIR")
    );
    if std::env::var_os("LARIS_UPDATE_SNAPSHOTS").is_some() {
        std::fs::create_dir_all(format!("{}/tests/snapshots", env!("CARGO_MANIFEST_DIR"))).unwrap();
        std::fs::write(&path, text).unwrap();
        return;
    }
    let want = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("{path}: {e}; run with LARIS_UPDATE_SNAPSHOTS=1"));
    assert_eq!(
        text, want,
        "the screen of {name} at {width} columns changed ({path})"
    );
}

#[test]
fn the_chat_scenario_passes_through_the_interface_at_both_widths() {
    for width in WIDTHS {
        let played = play("basic_chat", width, false).expect("the scenario replays");
        // the user's message went out as the scenario expects
        let sent: Vec<&Command> = played.snapshots.iter().flat_map(|s| &s.commands).collect();
        assert!(matches!(sent[..], [Command::UserMessage { text, .. }] if text == "hello"));
        let screen = &played.snapshots.last().unwrap().screen;
        for want in [
            "> hello",
            "● Hi, this is bold and code.",
            "● search_papers(query: \"graphs\")",
            "⎿ 2 results",
            "● Found 2 passages.",
            "│ for i in range(3):",
            "│     print(i)  # count",
            "laris-base",
            "context 19%",
        ] {
            assert!(
                screen.contains(want),
                "{want:?} missing at {width}:\n{screen}"
            );
        }
        assert!(
            !screen.contains("**") && !screen.contains('`'),
            "markers are gone:\n{screen}"
        );
        assert!(!played.app.running());
        check_snapshot("basic_chat", width, &snapshot("basic_chat", width, &played));
    }
}

#[test]
fn the_interrupt_scenario_passes_through_the_interface_at_both_widths() {
    for width in WIDTHS {
        let played = play("interrupt", width, false).expect("the scenario replays");
        let commands: Vec<&Command> = played.snapshots.iter().flat_map(|s| &s.commands).collect();
        assert!(matches!(
            commands[..],
            [
                Command::UserMessage { .. },
                Command::Interrupt {},
                Command::UserMessage { .. }
            ]
        ));
        let running = &played.snapshots[1].screen;
        assert!(
            running.contains("Let me think") && running.contains("esc to interrupt"),
            "{running}"
        );
        let after = &played.snapshots[2].screen;
        assert!(
            after.contains("Interrupted") && !after.contains("esc to interrupt"),
            "{after}"
        );
        let last = &played.snapshots[3].screen;
        assert!(last.contains("Second answer."), "{last}");
        check_snapshot("interrupt", width, &snapshot("interrupt", width, &played));
    }
}

#[test]
fn typing_while_the_agent_works_and_slash_commands_pass_too() {
    let queued = play("queued", 80, false).expect("queued replays");
    let during = &queued.snapshots[2].screen;
    assert!(during.contains("answer to second"), "{during}");
    assert!(!queued.app.running());
    let slash = play("slash", 80, false).expect("slash replays");
    let screen = &slash.snapshots.last().unwrap().screen;
    assert!(screen.contains("Commands: /help /exit"), "{screen}");
    assert!(
        screen.contains("unknown_command: unknown command /nope"),
        "{screen}"
    );
    assert!(screen.contains("● yes"), "{screen}");
    // the error ended its command: nothing is running
    assert!(!slash.app.running());
}

#[test]
fn every_scenario_draws_within_the_width_whatever_the_width() {
    for name in SCENARIOS {
        for width in [20, 33, 60, 100, 160] {
            let played = play(name, width, true).unwrap_or_else(|e| panic!("{name}: {e}"));
            for snap in &played.snapshots {
                for line in snap.screen.lines() {
                    assert!(
                        str_width(line) <= width,
                        "{name} @ {width} step {}: {line:?} is {} columns",
                        snap.step,
                        str_width(line)
                    );
                }
                assert!(
                    !snap.screen.chars().any(|c| c.is_control() && c != '\n'),
                    "{name}"
                );
            }
            let layout = played.app.layout(width);
            for line in layout.all() {
                assert!(line.width() <= width, "{name} @ {width}: {}", line.text());
            }
            if let Some((row, col)) = layout.cursor {
                assert!(
                    row < layout.live.len() && col < width,
                    "{name}: cursor ({row}, {col})"
                );
            }
        }
    }
}

#[test]
fn a_scenario_that_needs_an_approval_cannot_be_typed_yet_and_says_so() {
    let err = replay(&common::scenario("refusal"), &Ui::default(), 80, false)
        .map(|_| ())
        .unwrap_err();
    assert!(err.contains("permission_response"), "{err}");
    // fed events only, the request is on screen
    let played = play("refusal", 80, true).unwrap();
    assert!(
        played.snapshots[1]
            .screen
            .contains("Waiting for approval: write_file")
    );
}

#[test]
fn another_protocol_version_stops_the_interface_with_a_message() {
    let played = play("mismatch", 80, false).unwrap();
    let screen = &played.snapshots[0].screen;
    assert!(played.app.blocked(), "{screen}");
    assert!(
        screen.contains("engine reports") && screen.contains("\"9\""),
        "{screen}"
    );
    assert!(screen.contains("Press Ctrl-C to exit"), "{screen}");
    let mut app = played.app;
    assert!(app.update(Input::Key(Key::Char('x'))).is_empty());
    assert_eq!(app.input_text(), "", "typing is refused");
    assert!(app.layout(80).cursor.is_none());
    app.update(Input::Key(Key::CtrlC));
    assert!(app.should_quit());
}

fn app() -> App {
    App::new(&Ui::default())
}

fn press(app: &mut App, keys: &[Key]) -> Vec<Command> {
    keys.iter()
        .flat_map(|k| app.update(Input::Key(*k)))
        .collect()
}

#[test]
fn escape_interrupts_only_a_running_turn_and_ctrl_c_twice_exits() {
    let mut a = app();
    assert!(
        press(&mut a, &[Key::Esc]).is_empty(),
        "nothing runs: Esc does nothing"
    );
    press(&mut a, &[Key::Char('h'), Key::Char('i')]);
    let sent = press(&mut a, &[Key::Enter]);
    assert!(matches!(&sent[..], [Command::UserMessage { text, .. }] if text == "hi"));
    assert!(a.running());
    assert_eq!(press(&mut a, &[Key::Esc]), vec![Command::Interrupt {}]);

    // Ctrl+C once only asks; any other key takes it back
    assert!(press(&mut a, &[Key::CtrlC]).is_empty());
    assert!(a.screen_text(80).contains("Press Ctrl-C again to exit"));
    press(&mut a, &[Key::Char('x')]);
    assert!(!a.screen_text(80).contains("Press Ctrl-C again"));
    assert_eq!(a.input_text(), "x");
    // with text in the box the first Ctrl+C clears it instead
    press(&mut a, &[Key::CtrlC]);
    assert_eq!(a.input_text(), "");
    assert!(!a.should_quit());
    // twice in a row leaves
    press(&mut a, &[Key::CtrlC]);
    let out = press(&mut a, &[Key::CtrlC]);
    assert_eq!(out, vec![Command::Shutdown {}]);
    assert!(a.should_quit());
}

#[test]
fn the_exit_prompt_expires_with_the_clock() {
    let mut a = app();
    press(&mut a, &[Key::CtrlC]);
    a.update(Input::Tick(1000));
    assert!(a.screen_text(80).contains("Press Ctrl-C again"));
    a.update(Input::Tick(2500));
    assert!(!a.screen_text(80).contains("Press Ctrl-C again"));
    assert!(
        press(&mut a, &[Key::CtrlC]).is_empty(),
        "armed again, not leaving"
    );
    assert!(!a.should_quit());
}

#[test]
fn shift_tab_asks_for_the_next_mode_and_a_slash_line_is_a_command() {
    let mut a = app();
    assert_eq!(
        press(&mut a, &[Key::ShiftTab]),
        vec![Command::SetMode { mode: Mode::Next }]
    );
    for c in "/model fast one".chars() {
        a.update(Input::Key(Key::Char(c)));
    }
    let sent = press(&mut a, &[Key::Enter]);
    assert_eq!(
        sent,
        vec![Command::Slash {
            name: "model".into(),
            args: "fast one".into()
        }]
    );
}

#[test]
fn what_the_core_sends_cannot_move_the_cursor_or_paint_outside_the_interface() {
    use laris_protocol::Event;
    let mut a = app();
    let hostile = "ok \x1b[2J\x1b]0;owned\x07 end\x08\x08 done";
    for event in [
        Event::Text {
            delta: format!("{hostile}\n"),
        },
        Event::ToolCall {
            id: "t".into(),
            name: format!("Bash{hostile}"),
            arguments: serde_json::from_value(serde_json::json!({"command": hostile})).unwrap(),
        },
        Event::ToolResult {
            id: "t".into(),
            name: "Bash".into(),
            result: serde_json::json!({"error": {"code": "x", "message": hostile}}),
        },
        Event::Error {
            code: "bad".into(),
            message: hostile.into(),
        },
        Event::Status {
            kind: "line".into(),
            data: serde_json::from_value(serde_json::json!({"model": hostile, "branch": hostile}))
                .unwrap(),
        },
    ] {
        a.update(Input::Event(event));
    }
    let layout = a.layout(80);
    for color in [true, false] {
        let out = ansi(&layout.all(), color);
        let escapes = out.matches('\x1b').count();
        if color {
            // only the interface's own colour codes: each is `ESC [ ... m`
            assert_eq!(escapes, out.matches("\x1b[").count());
            for part in out.split('\x1b').skip(1) {
                assert!(part.starts_with('['), "{part:?}");
                let end = part.find('m').expect("an SGR sequence");
                assert!(
                    part[1..end].chars().all(|c| c.is_ascii_digit() || c == ';'),
                    "{part:?}"
                );
            }
        } else {
            assert_eq!(escapes, 0);
        }
        assert!(
            !out.chars()
                .any(|c| c.is_control() && c != '\n' && c != '\x1b')
        );
    }
    assert!(a.screen_text(80).contains("ok [2J]0;owned end done"));
}

#[test]
fn styles_follow_the_theme_and_a_mono_screen_has_no_colour() {
    let played = play("basic_chat", 80, false).unwrap();
    let layout = played.app.layout(80);
    let coloured = ansi(&layout.all(), true);
    assert!(
        coloured.contains("\x1b[1mbold\x1b[0m"),
        "bold is bold: {coloured:?}"
    );
    assert!(
        coloured.contains("\x1b[33mcode\x1b[0m"),
        "inline code is coloured"
    );
    assert!(coloured.contains("\x1b[35m"), "keywords are coloured");
    assert_eq!(ansi(&layout.all(), false).matches('\x1b').count(), 0);
    let mono = played.app.clone().with_theme(Theme::mono());
    let flat = ansi(&mono.layout(80).all(), true);
    assert!(
        !flat.contains("\x1b[3") && !flat.contains("\x1b[9"),
        "no colour codes in mono"
    );
    assert!(flat.contains("\x1b[1mbold"), "but bold stays");
}

#[test]
fn the_interface_speaks_the_language_of_the_settings() {
    let ui = Ui {
        language: laris_config::Language::Vi,
        ..Ui::default()
    };
    let played = replay(&common::scenario("interrupt"), &ui, 80, false).unwrap();
    let screen = &played.snapshots[2].screen;
    assert!(screen.contains("Đã ngắt"), "{screen}");
    assert!(screen.contains("Nhập tin nhắn"), "{screen}");
    for line in screen.lines() {
        assert!(str_width(line) <= 80, "{line:?}");
    }
}

#[test]
fn the_box_grows_with_the_text_and_keeps_the_cursor_inside_it() {
    let mut a = app();
    a.update(Input::Paste("first line\nsecond line\r\nthird".to_owned()));
    let layout = a.layout(60);
    let text = laris_tui::plain(&layout.live);
    assert!(
        text.contains("> first line") && text.contains("  second line") && text.contains("  third"),
        "{text}"
    );
    let (row, col) = layout.cursor.unwrap();
    let line = layout.live[row].text();
    assert_eq!(
        &line[..line.char_indices().nth(col).unwrap().0],
        "│   third"
    );
    // a very long unbroken line wraps by columns and stays inside the box
    a.update(Input::Paste("x".repeat(200)));
    for line in a.layout(60).live {
        assert!(line.width() <= 60, "{}", line.text());
    }
    // ... and a tall one scrolls to the cursor instead of growing without end
    a.update(Input::Paste("\nmore".repeat(30)));
    let tall = a.layout(60);
    assert!(tall.live.len() < 20, "{} live lines", tall.live.len());
    assert!(tall.live[tall.cursor.unwrap().0].text().contains("more"));
}
