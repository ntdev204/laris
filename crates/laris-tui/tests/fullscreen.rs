//! The full-screen interface (T237): the layout of the alternate screen, the scrolling, and the history of a
//! resumed session. The bytes are played into a small windowed terminal emulator and compared with what the
//! interface says it shows.

#![allow(missing_docs)]

use crossterm::event::{Event, KeyCode, KeyEvent, KeyEventKind, KeyEventState, KeyModifiers};
use crossterm::event::{MouseEvent, MouseEventKind};
use laris_config::settings::Ui;
use laris_protocol::Event as Core;
use laris_tui::term::{FullScreen, Term, term_of};
use laris_tui::{App, History, Input, Key};

/// A terminal with a window: absolute cursor moves, erase in line and display, nothing else.
struct Window {
    rows: Vec<Vec<char>>,
    columns: usize,
    row: usize,
    col: usize,
    cursor_shown: bool,
    writes: usize,
}

impl Window {
    fn new(columns: usize, rows: usize) -> Self {
        Self {
            rows: vec![vec![' '; columns]; rows],
            columns,
            row: 0,
            col: 0,
            cursor_shown: true,
            writes: 0,
        }
    }

    fn feed(&mut self, bytes: &str) {
        let chars: Vec<char> = bytes.chars().collect();
        let mut i = 0;
        while i < chars.len() {
            if chars[i] != '\x1b' {
                assert!(
                    self.row < self.rows.len() && self.col < self.columns,
                    "write outside the window"
                );
                self.rows[self.row][self.col] = chars[i];
                self.col += 1;
                self.writes += 1;
                i += 1;
                continue;
            }
            assert_eq!(chars[i + 1], '[');
            let mut j = i + 2;
            let mut params = String::new();
            while !chars[j].is_ascii_alphabetic() {
                params.push(chars[j]);
                j += 1;
            }
            let numbers: Vec<usize> = params.split(';').filter_map(|p| p.parse().ok()).collect();
            match chars[j] {
                'H' => {
                    self.row = numbers.first().copied().unwrap_or(1) - 1;
                    self.col = numbers.get(1).copied().unwrap_or(1) - 1;
                }
                'K' => {
                    for c in self.col..self.columns {
                        self.rows[self.row][c] = ' ';
                    }
                }
                'J' => {
                    for r in &mut self.rows {
                        r.fill(' ');
                    }
                }
                'h' if params == "?25" => self.cursor_shown = true,
                'l' if params == "?25" => self.cursor_shown = false,
                'h' | 'l' if params == "?2026" => {}
                'm' => {}
                other => panic!("unexpected sequence {params}{other}"),
            }
            i = j + 1;
        }
    }

    fn text(&self) -> Vec<String> {
        self.rows
            .iter()
            .map(|r| r.iter().collect::<String>().trim_end().to_owned())
            .collect()
    }
}

fn app() -> App {
    let mut app = App::new(&Ui::default());
    app.update(Input::Event(Core::Ready {
        version: laris_protocol::CORE_VERSION.to_owned(),
        engine: "1.0.1".into(),
        session: "s".into(),
        cwd: "/work".into(),
        mode: "default".into(),
        server: "https://example.test:8443/v1".into(),
    }));
    app
}

fn say(app: &mut App, question: &str, answer: &str) {
    app.update(Input::Event(Core::Status {
        kind: "queued".into(),
        data: serde_json::Map::new(),
    }));
    for c in question.chars() {
        app.update(Input::Key(Key::Char(c)));
    }
    app.update(Input::Key(Key::Enter));
    app.update(Input::Event(Core::Text {
        delta: answer.into(),
    }));
    app.update(Input::Event(Core::Done {
        status: "completed".into(),
        answer: answer.into(),
    }));
}

fn show(screen: &mut FullScreen<Vec<u8>>, window: &mut Window, app: &App) {
    screen.draw(app, window.columns, window.rows.len()).unwrap();
    let bytes = std::mem::take(screen.writer_mut());
    window.feed(&String::from_utf8(bytes).unwrap());
}

fn long_talk(count: usize) -> App {
    let mut app = app();
    for n in 0..count {
        say(&mut app, &format!("question {n}"), &format!("answer {n}"));
    }
    app
}

#[test]
fn the_header_is_on_top_and_the_input_and_status_are_fixed_at_the_bottom() {
    let app = app();
    let mut window = Window::new(60, 20);
    let mut screen = FullScreen::new(Vec::new(), false);
    show(&mut screen, &mut window, &app);
    let text = window.text();
    assert!(text[0].contains("Laris"), "header: {text:?}");
    assert!(text[1].contains("/work"), "header: {text:?}");
    let last = text.len() - 1;
    assert!(
        !text[last].is_empty(),
        "the footer is on the last row: {text:?}"
    );
    let input = text
        .iter()
        .position(|r| r.starts_with('╭') || r.starts_with('┌') || r.contains('>'))
        .expect("the input box");
    assert!(input > 10, "the input box is near the bottom: {text:?}");
    assert!(window.cursor_shown);
}

#[test]
fn a_long_conversation_scrolls_and_the_bottom_stays_where_it_is() {
    let mut app = long_talk(30);
    let mut window = Window::new(60, 20);
    let mut screen = FullScreen::new(Vec::new(), false);
    show(&mut screen, &mut window, &app);
    let at_end = window.text();
    assert!(at_end[0].contains("Laris"), "the header stays: {at_end:?}");
    assert!(at_end.iter().any(|r| r.contains("answer 29")));
    assert!(
        !at_end.iter().any(|r| r.contains("question 0")),
        "old lines are scrolled out"
    );

    screen.scroll_by(10);
    show(&mut screen, &mut window, &app);
    let back = window.text();
    assert_eq!(back[0], at_end[0], "the header does not move");
    assert_eq!(back.last(), at_end.last(), "the footer does not move");
    assert!(
        !back.iter().any(|r| r.contains("answer 29")),
        "scrolled back in time: {back:?}"
    );
    assert_eq!(screen.scrolled(), 10);

    // a new answer arrives while the person reads: the view stays on the same lines
    let before: Vec<String> = back[3..12].to_vec();
    say(&mut app, "question 30", "answer 30");
    show(&mut screen, &mut window, &app);
    assert_eq!(
        window.text()[3..12].to_vec(),
        before,
        "the view stays still"
    );

    screen.to_end();
    show(&mut screen, &mut window, &app);
    assert!(window.text().iter().any(|r| r.contains("answer 30")));
    // the first conversation line is reachable
    screen.scroll_by(10_000);
    show(&mut screen, &mut window, &app);
    assert!(window.text().iter().any(|r| r.contains("question 0")));
    screen.scroll_by(-10_000);
    assert_eq!(screen.scrolled(), 0);
}

#[test]
fn only_the_rows_that_changed_are_written_and_an_unchanged_frame_writes_nothing() {
    let mut app = long_talk(3);
    let mut window = Window::new(60, 20);
    let mut screen = FullScreen::new(Vec::new(), false);
    show(&mut screen, &mut window, &app);
    show(&mut screen, &mut window, &app);
    let written = window.writes;
    show(&mut screen, &mut window, &app);
    assert_eq!(window.writes, written, "an unchanged screen is not written");
    app.update(Input::Key(Key::Char('x')));
    screen.draw(&app, 60, 20).unwrap();
    let frame = String::from_utf8(std::mem::take(screen.writer_mut())).unwrap();
    assert!(frame.starts_with("\x1b[?2026h"), "one synchronised frame");
    assert!(frame.ends_with("\x1b[?2026l"));
    assert!(
        !frame.contains("\x1b[2J"),
        "no full clear for one changed row"
    );
    assert!(
        frame.matches("\x1b[K").count() <= 3,
        "only the input rows are rewritten: {frame:?}"
    );
}

#[test]
fn a_resize_redraws_the_whole_window() {
    let app = long_talk(5);
    let mut window = Window::new(60, 20);
    let mut screen = FullScreen::new(Vec::new(), false);
    show(&mut screen, &mut window, &app);
    let mut small = Window::new(40, 10);
    show(&mut screen, &mut small, &app);
    let text = small.text();
    assert!(text[0].contains("Laris"));
    assert!(!text[9].is_empty());
}

#[test]
fn a_bottom_taller_than_the_window_still_leaves_a_row_for_the_conversation() {
    let app = long_talk(5);
    let mut window = Window::new(60, 4);
    let mut screen = FullScreen::new(Vec::new(), false);
    show(&mut screen, &mut window, &app);
    assert_eq!(window.text().len(), 4);
}

#[test]
fn the_wheel_and_the_page_keys_scroll() {
    let wheel = |kind| {
        Event::Mouse(MouseEvent {
            kind,
            column: 1,
            row: 1,
            modifiers: KeyModifiers::NONE,
        })
    };
    assert_eq!(
        term_of(wheel(MouseEventKind::ScrollUp)),
        Some(Term::Scroll(3))
    );
    assert_eq!(
        term_of(wheel(MouseEventKind::ScrollDown)),
        Some(Term::Scroll(-3))
    );
    assert_eq!(term_of(wheel(MouseEventKind::Moved)), None);
    let key = |code| {
        Event::Key(KeyEvent {
            code,
            modifiers: KeyModifiers::NONE,
            kind: KeyEventKind::Press,
            state: KeyEventState::NONE,
        })
    };
    assert_eq!(term_of(key(KeyCode::PageUp)), Some(Term::Page(1)));
    assert_eq!(term_of(key(KeyCode::PageDown)), Some(Term::Page(-1)));
    let mut screen = FullScreen::new(Vec::new(), false);
    screen.page_by(1, 24);
    assert_eq!(screen.scrolled(), 19);
}

#[test]
fn a_resumed_session_shows_its_conversation_again() {
    let mut app = app();
    app.show_history(vec![
        History::User("what is 2+2".into()),
        History::Event(Core::Text {
            delta: "It is ".into(),
        }),
        History::Event(Core::Text {
            delta: "four.".into(),
        }),
        History::Event(Core::Done {
            status: "completed".into(),
            answer: "It is four.".into(),
        }),
        History::Event(Core::LoginRequired {
            reason: laris_protocol::events::LoginReason::NoKey,
            server: String::new(),
            fingerprint: String::new(),
            message: String::new(),
        }),
    ]);
    assert!(!app.running());
    assert!(
        app.sign_in().is_none(),
        "a login of the past does not reopen"
    );
    let mut window = Window::new(60, 20);
    let mut screen = FullScreen::new(Vec::new(), false);
    show(&mut screen, &mut window, &app);
    let text = window.text();
    assert!(text.iter().any(|r| r.contains("what is 2+2")), "{text:?}");
    assert!(text.iter().any(|r| r.contains("It is four.")), "{text:?}");
}

#[test]
fn leaving_gives_the_terminal_back_in_the_order_vim_does() {
    let mut out = Vec::new();
    laris_tui::term::leave_sequence(&mut out).unwrap();
    let text = String::from_utf8(out).unwrap();
    let at = |needle: &str| {
        text.find(needle)
            .unwrap_or_else(|| panic!("{needle} missing in {text:?}"))
    };
    // mouse off, cursor on, alternate screen left, paste off
    assert!(at("\x1b[?1000l") < at("\x1b[?25h"));
    assert!(at("\x1b[?25h") < at("\x1b[?1049l"));
    assert!(at("\x1b[?1049l") < at("\x1b[?2004l"));
}
