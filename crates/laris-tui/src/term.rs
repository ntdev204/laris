//! The terminal itself: raw mode, the keys crossterm reports, and the inline screen that prints final lines once
//! into the scrollback and redraws only the live part at the bottom.
//!
//! Nothing here decides what the interface does; [`key_of`] turns what the terminal sent into a [`Key`], and
//! [`Screen`] writes an [`App`]'s [`Layout`] to any [`Write`], so it is tested against a byte buffer.

use crate::app::App;
use crate::input::Key;
use crate::style::{Line, ansi};
use crate::view::Layout;
use crossterm::event::{
    DisableBracketedPaste, EnableBracketedPaste, Event as Raw, KeyCode, KeyEvent, KeyEventKind,
    KeyModifiers,
};
use crossterm::terminal::{disable_raw_mode, enable_raw_mode};
use std::io::{self, Write};

/// What the terminal sent that the interface cares about.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Term {
    /// A key.
    Key(Key),
    /// Pasted text (bracketed paste).
    Paste(String),
    /// The window changed to (columns, rows).
    Resize(u16, u16),
}

/// The [`Key`] of a key event, if the interface has one. Releases are ignored (Windows reports them).
pub fn key_of(event: KeyEvent) -> Option<Key> {
    if event.kind == KeyEventKind::Release {
        return None;
    }
    let ctrl = event.modifiers.contains(KeyModifiers::CONTROL);
    let alt = event.modifiers.contains(KeyModifiers::ALT);
    let shift = event.modifiers.contains(KeyModifiers::SHIFT);
    Some(match event.code {
        KeyCode::Char(c) if ctrl => match c.to_ascii_lowercase() {
            'c' => Key::CtrlC,
            'd' => Key::CtrlD,
            'u' => Key::CtrlU,
            'k' => Key::CtrlK,
            'w' => Key::CtrlW,
            'r' => Key::CtrlR,
            'a' => Key::Home,
            'e' => Key::End,
            'j' => Key::Newline,
            _ => return None,
        },
        KeyCode::Char(_) if alt => return None,
        KeyCode::Char(c) => Key::Char(c),
        KeyCode::Enter if shift || alt => Key::Newline,
        KeyCode::Enter => Key::Enter,
        KeyCode::Backspace => Key::Backspace,
        KeyCode::Delete => Key::Delete,
        KeyCode::Left => Key::Left,
        KeyCode::Right => Key::Right,
        KeyCode::Up => Key::Up,
        KeyCode::Down => Key::Down,
        KeyCode::Home => Key::Home,
        KeyCode::End => Key::End,
        KeyCode::Esc => Key::Esc,
        KeyCode::Tab => Key::Tab,
        KeyCode::BackTab => Key::ShiftTab,
        _ => return None,
    })
}

/// What the interface does with a raw terminal event.
pub fn term_of(event: Raw) -> Option<Term> {
    match event {
        Raw::Key(key) => key_of(key).map(Term::Key),
        Raw::Paste(text) => Some(Term::Paste(text)),
        Raw::Resize(columns, rows) => Some(Term::Resize(columns, rows)),
        _ => None,
    }
}

/// Raw mode with bracketed paste, restored when dropped (and on a panic, so the shell is never left raw).
pub struct RawMode {
    _private: (),
}

impl RawMode {
    /// Enters raw mode.
    pub fn enter() -> io::Result<Self> {
        enable_raw_mode()?;
        let _ = crossterm::execute!(io::stdout(), EnableBracketedPaste);
        let previous = std::panic::take_hook();
        std::panic::set_hook(Box::new(move |info| {
            restore();
            previous(info);
        }));
        Ok(Self { _private: () })
    }
}

fn restore() {
    let _ = crossterm::execute!(io::stdout(), DisableBracketedPaste);
    let _ = disable_raw_mode();
}

impl Drop for RawMode {
    fn drop(&mut self) {
        restore();
    }
}

/// One line as bytes without its newline.
fn row(line: &Line, color: bool) -> String {
    let mut text = ansi(std::slice::from_ref(line), color);
    text.pop();
    text
}

/// Writes an [`App`] to a terminal that scrolls: lines that are final are printed once and stay in the
/// scrollback; the live lines at the bottom are erased and printed again on every frame.
pub struct Screen<W: Write> {
    out: W,
    color: bool,
    printed: usize,
    /// Rows the live block occupies and the row the cursor is on, counted from the block's first row.
    live_rows: usize,
    cursor_row: usize,
    last: Option<(Layout, usize)>,
}

impl<W: Write> Screen<W> {
    /// A screen writing to `out`; `color` off writes no escape sequences for styles.
    pub fn new(out: W, color: bool) -> Self {
        Self {
            out,
            color,
            printed: 0,
            live_rows: 0,
            cursor_row: 0,
            last: None,
        }
    }

    /// The writer, to take what was written so far.
    pub fn writer_mut(&mut self) -> &mut W {
        &mut self.out
    }

    /// The writer.
    pub fn into_inner(self) -> W {
        self.out
    }

    /// How many final lines were printed.
    pub fn printed(&self) -> usize {
        self.printed
    }

    fn erase_live(&mut self) -> io::Result<()> {
        if self.live_rows > 0 {
            if self.cursor_row > 0 {
                write!(self.out, "\x1b[{}A", self.cursor_row)?;
            }
            write!(self.out, "\r\x1b[J")?;
        }
        self.live_rows = 0;
        self.cursor_row = 0;
        Ok(())
    }

    /// Clears the terminal and forgets what was printed (`/clear`).
    pub fn clear(&mut self) -> io::Result<()> {
        write!(self.out, "\x1b[2J\x1b[3J\x1b[H")?;
        self.printed = 0;
        self.live_rows = 0;
        self.cursor_row = 0;
        self.last = None;
        self.out.flush()
    }

    /// Draws `app` for a terminal of `columns` by `rows`: the lines that became final are printed, the live part
    /// is redrawn, and the cursor is put where the input is. A live part taller than the window shows its last rows.
    pub fn draw(&mut self, app: &App, columns: usize, rows: usize) -> io::Result<()> {
        let layout = app.layout(columns);
        if self
            .last
            .as_ref()
            .is_some_and(|(last, high)| *last == layout && *high == rows)
        {
            return Ok(());
        }
        self.last = Some((layout.clone(), rows));
        self.erase_live()?;
        if layout.committed.len() < self.printed {
            write!(self.out, "\x1b[2J\x1b[3J\x1b[H")?;
            self.printed = 0;
        }
        for line in &layout.committed[self.printed..] {
            write!(self.out, "{}\r\n", row(line, self.color))?;
        }
        self.printed = layout.committed.len();

        let room = rows.saturating_sub(1).max(1);
        let cut = layout.live.len().saturating_sub(room);
        let live = &layout.live[cut..];
        for (i, line) in live.iter().enumerate() {
            if i > 0 {
                write!(self.out, "\r\n")?;
            }
            write!(self.out, "{}", row(line, self.color))?;
        }
        self.live_rows = live.len();
        let last = live.len().saturating_sub(1);
        self.cursor_row = last;
        match layout.cursor {
            Some((row_at, col)) if row_at >= cut && row_at - cut <= last => {
                let up = last - (row_at - cut);
                if up > 0 {
                    write!(self.out, "\x1b[{up}A")?;
                }
                write!(self.out, "\r")?;
                if col > 0 {
                    write!(self.out, "\x1b[{col}C")?;
                }
                self.cursor_row = row_at - cut;
                write!(self.out, "\x1b[?25h")?;
            }
            _ => write!(self.out, "\x1b[?25l")?,
        }
        self.out.flush()
    }

    /// Leaves the live part on screen and puts the cursor on a fresh line below it.
    pub fn finish(&mut self) -> io::Result<()> {
        let down = self
            .live_rows
            .saturating_sub(1)
            .saturating_sub(self.cursor_row);
        if down > 0 {
            write!(self.out, "\x1b[{down}B")?;
        }
        write!(self.out, "\x1b[?25h\r\n")?;
        self.live_rows = 0;
        self.cursor_row = 0;
        self.out.flush()
    }
}

/// The window size as (columns, rows); 80 by 24 when it cannot be asked.
pub fn size() -> (u16, u16) {
    crossterm::terminal::size().unwrap_or((80, 24))
}

/// Waits up to `timeout` for the next event the interface cares about. `Ok(None)` when none came (or the one that
/// came is not one of the interface's).
pub fn next(timeout: std::time::Duration) -> io::Result<Option<Term>> {
    if crossterm::event::poll(timeout)? {
        Ok(term_of(crossterm::event::read()?))
    } else {
        Ok(None)
    }
}

/// Whether an event is already waiting.
pub fn pending() -> io::Result<bool> {
    crossterm::event::poll(std::time::Duration::ZERO)
}
