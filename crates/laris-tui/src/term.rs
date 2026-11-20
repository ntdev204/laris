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
    DisableBracketedPaste, DisableMouseCapture, EnableBracketedPaste, EnableMouseCapture,
    Event as Raw, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseEventKind,
};
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, Ordering};

/// Lines one step of the mouse wheel moves.
pub const WHEEL_LINES: i32 = 3;

/// What the terminal sent that the interface cares about.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Term {
    /// A key.
    Key(Key),
    /// Pasted text (bracketed paste).
    Paste(String),
    /// The window changed to (columns, rows).
    Resize(u16, u16),
    /// Scroll the conversation by this many lines; positive goes back in time (wheel up).
    Scroll(i32),
    /// Scroll the conversation by this many pages; positive goes back in time (Page Up).
    Page(i32),
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
        Raw::Key(key) if key.kind != KeyEventKind::Release && key.code == KeyCode::PageUp => {
            Some(Term::Page(1))
        }
        Raw::Key(key) if key.kind != KeyEventKind::Release && key.code == KeyCode::PageDown => {
            Some(Term::Page(-1))
        }
        Raw::Key(key) => key_of(key).map(Term::Key),
        Raw::Paste(text) => Some(Term::Paste(text)),
        Raw::Resize(columns, rows) => Some(Term::Resize(columns, rows)),
        Raw::Mouse(mouse) => match mouse.kind {
            MouseEventKind::ScrollUp => Some(Term::Scroll(WHEEL_LINES)),
            MouseEventKind::ScrollDown => Some(Term::Scroll(-WHEEL_LINES)),
            _ => None,
        },
        _ => None,
    }
}

/// Whether the alternate screen and the mouse are on, so that one restore undoes exactly what was done.
static FULL: AtomicBool = AtomicBool::new(false);

/// Raw mode with bracketed paste, restored when dropped (and on a panic, so the shell is never left raw).
pub struct RawMode {
    _private: (),
}

impl RawMode {
    /// Enters raw mode.
    pub fn enter() -> io::Result<Self> {
        Self::begin(false)
    }

    /// Enters raw mode on the alternate screen with the mouse reported, like `vim`: on exit (or a panic) the
    /// terminal shows what it showed before.
    pub fn enter_full() -> io::Result<Self> {
        Self::begin(true)
    }

    fn begin(full: bool) -> io::Result<Self> {
        enable_raw_mode()?;
        let _ = crossterm::execute!(io::stdout(), EnableBracketedPaste);
        if full {
            FULL.store(true, Ordering::SeqCst);
            let _ = crossterm::execute!(io::stdout(), EnterAlternateScreen, EnableMouseCapture);
        }
        let previous = std::panic::take_hook();
        std::panic::set_hook(Box::new(move |info| {
            restore();
            previous(info);
        }));
        Ok(Self { _private: () })
    }
}

/// What gives the terminal back to the shell after the full-screen mode: the mouse off, the cursor shown, the
/// alternate screen left (the screen the shell had is back, as after `vim`), bracketed paste off.
pub fn leave_sequence<W: Write>(out: &mut W) -> io::Result<()> {
    crossterm::execute!(
        out,
        DisableMouseCapture,
        crossterm::cursor::Show,
        LeaveAlternateScreen,
        DisableBracketedPaste
    )
}

fn restore() {
    if FULL.swap(false, Ordering::SeqCst) {
        let _ = leave_sequence(&mut io::stdout());
    } else {
        let _ = crossterm::execute!(io::stdout(), DisableBracketedPaste);
    }
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
        // one atomic frame: the terminal shows the finished frame, not the erase and the redraw (no flicker); a
        // terminal that does not know the mode ignores it
        write!(self.out, "\x1b[?2026h\x1b[?25l")?;
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
        write!(self.out, "\x1b[?2026l")?;
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

/// Writes an [`App`] to the alternate screen like `vim`: the header on the top rows, the conversation in the middle
/// (it scrolls), the input box, the status line and the footer on the bottom rows. Only the rows that changed are
/// written, in one synchronised update.
pub struct FullScreen<W: Write> {
    out: W,
    color: bool,
    /// Lines the view is above the end of the conversation.
    scroll: usize,
    /// Length of the conversation at the last frame, to keep the view still while new lines come in below it.
    body_len: usize,
    /// What each screen row showed at the last frame.
    shown: Vec<String>,
    last: Option<(Layout, usize, usize, usize)>,
}

impl<W: Write> FullScreen<W> {
    /// A screen writing to `out`; `color` off writes no escape sequences for styles.
    pub fn new(out: W, color: bool) -> Self {
        Self {
            out,
            color,
            scroll: 0,
            body_len: 0,
            shown: Vec::new(),
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

    /// How many lines the view is above the end.
    pub fn scrolled(&self) -> usize {
        self.scroll
    }

    /// Moves the view by `lines` (positive: back in time). Clamped when drawn.
    pub fn scroll_by(&mut self, lines: i32) {
        let step = usize::try_from(lines.unsigned_abs()).unwrap_or(usize::MAX);
        self.scroll = if lines >= 0 {
            self.scroll.saturating_add(step)
        } else {
            self.scroll.saturating_sub(step)
        };
        self.last = None;
    }

    /// Moves the view by `pages` of the conversation area (positive: back in time).
    pub fn page_by(&mut self, pages: i32, rows: usize) {
        let page = i32::try_from(rows.saturating_sub(5).max(1)).unwrap_or(i32::MAX);
        self.scroll_by(pages.saturating_mul(page));
    }

    /// Back to the end of the conversation (typing does this).
    pub fn to_end(&mut self) {
        if self.scroll != 0 {
            self.scroll = 0;
            self.last = None;
        }
    }

    /// Clears the terminal and forgets what was shown (`/clear`).
    pub fn clear(&mut self) -> io::Result<()> {
        write!(self.out, "\x1b[2J\x1b[H")?;
        self.scroll = 0;
        self.body_len = 0;
        self.shown.clear();
        self.last = None;
        self.out.flush()
    }

    /// Draws `app` for a terminal of `columns` by `rows`.
    pub fn draw(&mut self, app: &App, columns: usize, rows: usize) -> io::Result<()> {
        let rows = rows.max(2);
        let layout = app.layout(columns);
        if self
            .last
            .as_ref()
            .is_some_and(|(last, high, wide, scroll)| {
                *last == layout && *high == rows && *wide == columns && *scroll == self.scroll
            })
        {
            return Ok(());
        }
        let head = layout.head.min(layout.committed.len());
        let fixed = layout.fixed.min(layout.live.len());
        let bottom_all = &layout.live[fixed..];
        // the header and the bottom never take more than the screen minus one conversation row
        let head_rows = head.min(rows - 1);
        let bottom_rows = bottom_all.len().min(rows - 1 - head_rows);
        let bottom_cut = bottom_all.len() - bottom_rows;
        let bottom = &bottom_all[bottom_cut..];
        let area = rows - head_rows - bottom.len();

        let mut body: Vec<&Line> = layout.committed[head..].iter().collect();
        body.extend(layout.live[..fixed].iter());
        if self.scroll > 0 && body.len() > self.body_len {
            self.scroll += body.len() - self.body_len;
        }
        self.body_len = body.len();
        let furthest = body.len().saturating_sub(area);
        self.scroll = self.scroll.min(furthest);
        let end = body.len() - self.scroll;
        let start = end.saturating_sub(area);

        let mut frame: Vec<String> = Vec::with_capacity(rows);
        frame.extend(
            layout.committed[..head_rows]
                .iter()
                .map(|l| row(l, self.color)),
        );
        let seen: Vec<String> = body[start..end]
            .iter()
            .map(|l| row(l, self.color))
            .collect();
        let blank = area - seen.len();
        frame.extend(seen);
        frame.extend(std::iter::repeat_n(String::new(), blank));
        frame.extend(bottom.iter().map(|l| row(l, self.color)));

        write!(self.out, "\x1b[?2026h\x1b[?25l")?;
        if self.shown.len() != rows {
            write!(self.out, "\x1b[2J")?;
            self.shown = vec![String::from("\0"); rows];
        }
        for (at, text) in frame.iter().enumerate() {
            if self.shown[at] != *text {
                write!(self.out, "\x1b[{};1H{text}\x1b[0m\x1b[K", at + 1)?;
                self.shown[at].clone_from(text);
            }
        }
        let bottom_top = rows - bottom.len();
        if let Some((row_at, col)) = layout.cursor
            && row_at >= fixed + bottom_cut
            && row_at - fixed - bottom_cut < bottom.len()
        {
            let at = bottom_top + (row_at - fixed - bottom_cut);
            write!(self.out, "\x1b[{};{}H\x1b[?25h", at + 1, col + 1)?;
        }
        write!(self.out, "\x1b[?2026l")?;
        self.last = Some((layout, rows, columns, self.scroll));
        self.out.flush()
    }

    /// Nothing to leave behind: the alternate screen is dropped when the terminal is restored.
    pub fn finish(&mut self) -> io::Result<()> {
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
