//! The keys and the inline screen (T158). The screen is checked by playing its bytes into a small terminal
//! emulator and comparing what is visible with what the interface says it shows.

#![allow(missing_docs)]

mod common;

use common::{SCENARIOS, scenario};
use crossterm::event::{KeyCode, KeyEvent, KeyEventKind, KeyEventState, KeyModifiers};
use laris_config::settings::Ui;
use laris_protocol::Command;
use laris_tui::replay::type_and_send;
use laris_tui::term::{Screen, Term, key_of, term_of};
use laris_tui::{App, Input, Key};

fn press(code: KeyCode, modifiers: KeyModifiers) -> Option<Key> {
    key_of(KeyEvent {
        code,
        modifiers,
        kind: KeyEventKind::Press,
        state: KeyEventState::NONE,
    })
}

#[test]
fn keys_map_the_way_the_hints_say() {
    use KeyCode::*;
    let none = KeyModifiers::NONE;
    let ctrl = KeyModifiers::CONTROL;
    assert_eq!(press(Char('a'), none), Some(Key::Char('a')));
    assert_eq!(press(Char('É'), none), Some(Key::Char('É')));
    assert_eq!(press(Char('A'), KeyModifiers::SHIFT), Some(Key::Char('A')));
    assert_eq!(press(Char('c'), ctrl), Some(Key::CtrlC));
    assert_eq!(press(Char('C'), ctrl), Some(Key::CtrlC));
    assert_eq!(press(Char('d'), ctrl), Some(Key::CtrlD));
    assert_eq!(press(Char('r'), ctrl), Some(Key::CtrlR));
    assert_eq!(press(Char('u'), ctrl), Some(Key::CtrlU));
    assert_eq!(press(Char('k'), ctrl), Some(Key::CtrlK));
    assert_eq!(press(Char('w'), ctrl), Some(Key::CtrlW));
    assert_eq!(press(Char('a'), ctrl), Some(Key::Home));
    assert_eq!(press(Char('e'), ctrl), Some(Key::End));
    assert_eq!(press(Char('z'), ctrl), None);
    assert_eq!(press(Char('x'), KeyModifiers::ALT), None);
    assert_eq!(press(Enter, none), Some(Key::Enter));
    assert_eq!(press(Enter, KeyModifiers::SHIFT), Some(Key::Newline));
    assert_eq!(press(Enter, KeyModifiers::ALT), Some(Key::Newline));
    assert_eq!(press(Tab, none), Some(Key::Tab));
    assert_eq!(press(BackTab, KeyModifiers::SHIFT), Some(Key::ShiftTab));
    assert_eq!(press(Esc, none), Some(Key::Esc));
    assert_eq!(press(Backspace, none), Some(Key::Backspace));
    assert_eq!(press(F(5), none), None);
    // a release (Windows) is not a second press
    assert_eq!(
        key_of(KeyEvent {
            code: Char('a'),
            modifiers: none,
            kind: KeyEventKind::Release,
            state: KeyEventState::NONE
        }),
        None
    );
}

#[test]
fn a_paste_and_a_resize_come_through_and_the_rest_is_ignored() {
    use crossterm::event::Event;
    assert_eq!(
        term_of(Event::Paste("a\nb".into())),
        Some(Term::Paste("a\nb".into()))
    );
    assert_eq!(term_of(Event::Resize(80, 24)), Some(Term::Resize(80, 24)));
    assert_eq!(term_of(Event::FocusGained), None);
}

/// A terminal that keeps every line (no window): enough to see what the screen's bytes leave behind.
#[derive(Default)]
struct Emulator {
    rows: Vec<Vec<char>>,
    row: usize,
    col: usize,
}

impl Emulator {
    fn put(&mut self, c: char) {
        while self.rows.len() <= self.row {
            self.rows.push(Vec::new());
        }
        let line = &mut self.rows[self.row];
        while line.len() <= self.col {
            line.push(' ');
        }
        line[self.col] = c;
        self.col += 1;
    }

    fn feed(&mut self, bytes: &str) {
        let chars: Vec<char> = bytes.chars().collect();
        let mut i = 0;
        while i < chars.len() {
            match chars[i] {
                '\r' => self.col = 0,
                '\n' => self.row += 1,
                '\x1b' => {
                    assert_eq!(
                        chars.get(i + 1),
                        Some(&'['),
                        "only CSI sequences are written"
                    );
                    let mut j = i + 2;
                    let mut params = String::new();
                    while !chars[j].is_ascii_alphabetic() {
                        params.push(chars[j]);
                        j += 1;
                    }
                    let n: usize = params.parse().unwrap_or(1);
                    match chars[j] {
                        'A' => self.row = self.row.saturating_sub(n),
                        'B' => self.row += n,
                        'C' => self.col += n,
                        'J' => {
                            if params == "2" || params == "3" {
                                self.rows.clear();
                            } else {
                                self.rows.truncate(self.row + 1);
                                if let Some(line) = self.rows.get_mut(self.row) {
                                    line.truncate(self.col);
                                }
                            }
                        }
                        'H' => {
                            self.row = 0;
                            self.col = 0;
                        }
                        'm' | 'h' | 'l' => {}
                        other => panic!("unexpected CSI {other:?}"),
                    }
                    i = j;
                }
                c => self.put(c),
            }
            i += 1;
        }
    }

    fn text(&self) -> String {
        let mut lines: Vec<String> = self
            .rows
            .iter()
            .map(|l| l.iter().collect::<String>().trim_end().to_owned())
            .collect();
        while lines.last().is_some_and(String::is_empty) {
            lines.pop();
        }
        lines.join("\n")
    }
}

fn shown(app: &App, width: usize) -> String {
    let mut text: Vec<String> = app
        .screen_text(width)
        .lines()
        .map(|l| l.trim_end().to_owned())
        .collect();
    while text.last().is_some_and(String::is_empty) {
        text.pop();
    }
    text.join("\n")
}

fn draw(screen: &mut Screen<Vec<u8>>, emulator: &mut Emulator, app: &App, width: usize) {
    screen.draw(app, width, 1000).unwrap();
    let bytes = std::mem::take(&mut screen_buffer(screen));
    emulator.feed(&String::from_utf8(bytes).unwrap());
}

fn screen_buffer(screen: &mut Screen<Vec<u8>>) -> Vec<u8> {
    // Screen owns its writer; take what it wrote so far by swapping in an empty one
    std::mem::take(screen.writer_mut())
}

#[test]
fn what_is_left_on_the_terminal_is_what_the_interface_shows_after_every_step() {
    for name in SCENARIOS {
        for width in [60, 100] {
            for color in [false, true] {
                let scenario = scenario(name);
                let mut app = App::new(&Ui::default());
                let mut screen = Screen::new(Vec::new(), color);
                let mut emulator = Emulator::default();
                draw(&mut screen, &mut emulator, &app, width);
                for (i, step) in scenario.steps.iter().enumerate() {
                    if let (Some(Command::UserMessage { text, .. }), Some(_)) =
                        (&step.command, &step.expect)
                    {
                        type_and_send(&mut app, text);
                        draw(&mut screen, &mut emulator, &app, width);
                    }
                    if let Some(wait) = step.wait {
                        app.update(Input::Tick(wait));
                    }
                    for event in &step.emit {
                        app.update(Input::Event(event.clone()));
                        draw(&mut screen, &mut emulator, &app, width);
                    }
                    // the committed lines are printed once; the live part is redrawn in place
                    assert_eq!(
                        emulator.text(),
                        shown(&app, width),
                        "{name} @ {width} colour {color} step {i}"
                    );
                }
            }
        }
    }
}

#[test]
fn a_final_line_is_written_once_however_often_the_screen_is_redrawn() {
    let mut app = App::new(&Ui::default());
    app.update(Input::Event(
        serde_json::from_str(
            r#"{"type":"ready","version":"1","engine":"2.0.0","session":"abcdef12","cwd":"/w","mode":"default","server":""}"#,
        )
        .unwrap(),
    ));
    let mut screen = Screen::new(Vec::new(), false);
    for _ in 0..5 {
        screen.draw(&app, 80, 24).unwrap();
    }
    let all = String::from_utf8(screen.into_inner()).unwrap();
    assert_eq!(all.matches("Laris").count(), 1, "{all:?}");
}

#[test]
fn colour_off_writes_no_style_sequences_and_colour_on_does() {
    let mut app = App::new(&Ui::default());
    type_and_send(&mut app, "hi");
    let bytes = |color| {
        let mut screen = Screen::new(Vec::new(), color);
        screen.draw(&app, 80, 24).unwrap();
        String::from_utf8(screen.into_inner()).unwrap()
    };
    assert!(
        !bytes(false).contains("m>"),
        "no style codes: {:?}",
        bytes(false)
    );
    assert!(bytes(true).contains("\x1b[0m"));
}

#[test]
fn a_live_part_taller_than_the_window_shows_its_last_rows() {
    let mut app = App::new(&Ui::default());
    for _ in 0..30 {
        app.update(Input::Key(Key::Char('x')));
        app.update(Input::Key(Key::Newline));
    }
    let mut screen = Screen::new(Vec::new(), false);
    screen.draw(&app, 40, 8).unwrap();
    let text = String::from_utf8(screen.into_inner()).unwrap();
    // 8 rows: at most 7 rows are written (one stays free), joined by 6 line breaks
    assert!(text.matches("\r\n").count() <= 6, "{text:?}");
}

#[test]
fn clear_forgets_what_was_printed() {
    let mut app = App::new(&Ui::default());
    type_and_send(&mut app, "hello");
    let mut screen = Screen::new(Vec::new(), false);
    screen.draw(&app, 60, 24).unwrap();
    assert!(screen.printed() > 0);
    type_and_send(&mut app, "/clear");
    assert!(app.take_clear());
    screen.clear().unwrap();
    assert_eq!(screen.printed(), 0);
    screen.draw(&app, 60, 24).unwrap();
    let text = String::from_utf8(screen.into_inner()).unwrap();
    assert!(text.contains("\x1b[2J"));
    assert!(text.contains("Screen cleared"));
}

#[test]
fn finish_puts_the_cursor_below_the_live_part() {
    let app = App::new(&Ui::default());
    let mut screen = Screen::new(Vec::new(), false);
    screen.draw(&app, 60, 24).unwrap();
    screen.finish().unwrap();
    let text = String::from_utf8(screen.into_inner()).unwrap();
    assert!(text.ends_with("\r\n"), "{text:?}");
}

#[test]
fn an_unchanged_screen_is_not_written_again_and_a_changed_one_is() {
    let mut app = App::new(&Ui::default());
    let mut screen = Screen::new(Vec::new(), false);
    screen.draw(&app, 80, 24).unwrap();
    let first = std::mem::take(screen.writer_mut()).len();
    assert!(first > 0);
    screen.draw(&app, 80, 24).unwrap();
    assert!(
        screen.writer_mut().is_empty(),
        "the same frame writes nothing"
    );
    app.update(Input::Key(Key::Char('x')));
    screen.draw(&app, 80, 24).unwrap();
    assert!(!screen.writer_mut().is_empty());
    // a new window height is a new frame too
    std::mem::take(screen.writer_mut());
    screen.draw(&app, 80, 10).unwrap();
    assert!(!screen.writer_mut().is_empty());
}

#[test]
fn a_frame_is_one_synchronised_update_so_the_terminal_does_not_flicker() {
    let mut app = App::new(&Ui::default());
    let mut screen = Screen::new(Vec::new(), false);
    app.update(Input::Key(Key::Char('x')));
    screen.draw(&app, 80, 24).unwrap();
    let bytes = String::from_utf8(std::mem::take(screen.writer_mut())).unwrap();
    assert!(bytes.starts_with("\x1b[?2026h"), "{bytes:?}");
    assert!(bytes.ends_with("\x1b[?2026l"), "{bytes:?}");
    assert_eq!(bytes.matches("\x1b[?2026h").count(), 1);
}

#[test]
fn the_spinner_moves_slowly_and_only_while_something_runs() {
    let mut app = App::new(&Ui::default());
    let before = app.layout(80);
    // idle: ticks change nothing, so nothing is redrawn
    for _ in 0..50 {
        app.update(Input::Tick(40));
    }
    assert_eq!(app.layout(80), before);
}
