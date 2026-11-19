//! The input box's text: a multi-line buffer with a cursor, and a history of what was sent.

use crate::width::char_width;

/// A key the interface understands. The terminal driver turns what the terminal sends into these.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    /// A character.
    Char(char),
    /// Enter: send.
    Enter,
    /// Shift+Enter or Alt+Enter: a new line.
    Newline,
    /// Backspace.
    Backspace,
    /// Delete.
    Delete,
    /// Left.
    Left,
    /// Right.
    Right,
    /// Up.
    Up,
    /// Down.
    Down,
    /// Home.
    Home,
    /// End.
    End,
    /// Escape.
    Esc,
    /// Ctrl+C.
    CtrlC,
    /// Ctrl+D.
    CtrlD,
    /// Ctrl+U: delete to the start of the line.
    CtrlU,
    /// Ctrl+K: delete to the end of the line.
    CtrlK,
    /// Ctrl+W: delete the word before the cursor.
    CtrlW,
    /// Tab.
    Tab,
    /// Shift+Tab.
    ShiftTab,
}

/// The text being written.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InputBuffer {
    text: Vec<char>,
    cursor: usize,
    history: Vec<String>,
    browsing: Option<usize>,
    draft: String,
}

impl InputBuffer {
    /// An empty buffer.
    pub fn new() -> Self {
        Self::default()
    }

    /// The text.
    pub fn text(&self) -> String {
        self.text.iter().collect()
    }

    /// Whether nothing is written.
    pub fn is_empty(&self) -> bool {
        self.text.is_empty()
    }

    /// The cursor, as a character position.
    pub fn cursor(&self) -> usize {
        self.cursor
    }

    /// The cursor as (line, column in characters).
    pub fn cursor_line_col(&self) -> (usize, usize) {
        let before = &self.text[..self.cursor];
        let line = before.iter().filter(|&&c| c == '\n').count();
        let col = before.iter().rev().take_while(|&&c| c != '\n').count();
        (line, col)
    }

    /// Replaces the text and puts the cursor at its end.
    pub fn set(&mut self, text: &str) {
        self.text = text
            .chars()
            .filter(|c| !c.is_control() || *c == '\n')
            .collect();
        self.cursor = self.text.len();
    }

    /// Inserts `text` at the cursor. Tabs become spaces, `\r\n` and `\r` become `\n`, other control characters are
    /// dropped.
    pub fn insert(&mut self, text: &str) {
        self.browsing = None;
        let text = text.replace("\r\n", "\n").replace('\r', "\n");
        for c in text.chars() {
            let c = match c {
                '\t' => ' ',
                c if c.is_control() && c != '\n' => continue,
                c => c,
            };
            self.text.insert(self.cursor, c);
            self.cursor += 1;
        }
    }

    /// Takes the text out for sending and keeps it in the history. A trailing `\` before the newline is a request for
    /// a new line, not for sending: see [`InputBuffer::continues`].
    pub fn take(&mut self) -> String {
        let text = self.text();
        self.text.clear();
        self.cursor = 0;
        self.browsing = None;
        self.draft.clear();
        if !text.trim().is_empty() && self.history.last() != Some(&text) {
            self.history.push(text.clone());
        }
        text
    }

    /// Clears the text without keeping it.
    pub fn clear(&mut self) {
        self.text.clear();
        self.cursor = 0;
        self.browsing = None;
    }

    /// Whether the text ends in a backslash: Enter then adds a line instead of sending.
    pub fn continues(&self) -> bool {
        self.cursor == self.text.len() && self.text.last() == Some(&'\\')
    }

    /// Removes the trailing backslash and adds a new line.
    pub fn continue_line(&mut self) {
        self.text.pop();
        self.cursor = self.text.len();
        self.insert("\n");
    }

    fn line_bounds(&self) -> (usize, usize) {
        let start = self.text[..self.cursor]
            .iter()
            .rposition(|&c| c == '\n')
            .map_or(0, |p| p + 1);
        let end = self.text[self.cursor..]
            .iter()
            .position(|&c| c == '\n')
            .map_or(self.text.len(), |p| self.cursor + p);
        (start, end)
    }

    fn move_vertically(&mut self, down: bool) -> bool {
        let (line, col) = self.cursor_line_col();
        let lines: Vec<usize> = self.text.split(|&c| c == '\n').map(<[char]>::len).collect();
        let target = if down {
            if line + 1 >= lines.len() {
                return false;
            }
            line + 1
        } else {
            if line == 0 {
                return false;
            }
            line - 1
        };
        let start: usize = lines[..target].iter().map(|n| n + 1).sum();
        self.cursor = start + col.min(lines[target]);
        true
    }

    fn recall(&mut self, older: bool) -> bool {
        if self.history.is_empty() {
            return false;
        }
        let next = match (self.browsing, older) {
            (None, true) => {
                self.draft = self.text();
                self.history.len() - 1
            }
            (Some(0), true) => return true,
            (Some(i), true) => i - 1,
            (Some(i), false) if i + 1 < self.history.len() => i + 1,
            (Some(_), false) => {
                self.browsing = None;
                let draft = std::mem::take(&mut self.draft);
                self.set(&draft);
                return true;
            }
            (None, false) => return false,
        };
        self.browsing = Some(next);
        let entry = self.history[next].clone();
        self.set(&entry);
        true
    }

    /// Applies an editing key. `true` when it was one (the others are the application's).
    pub fn edit(&mut self, key: Key) -> bool {
        match key {
            Key::Char(c) => self.insert(&c.to_string()),
            Key::Newline => self.insert("\n"),
            Key::Backspace => {
                if self.cursor > 0 {
                    self.cursor -= 1;
                    self.text.remove(self.cursor);
                }
            }
            Key::Delete => {
                if self.cursor < self.text.len() {
                    self.text.remove(self.cursor);
                }
            }
            Key::Left => self.cursor = self.cursor.saturating_sub(1),
            Key::Right => self.cursor = (self.cursor + 1).min(self.text.len()),
            Key::Home => self.cursor = self.line_bounds().0,
            Key::End => self.cursor = self.line_bounds().1,
            Key::Up => {
                if !self.move_vertically(false) {
                    self.recall(true);
                }
            }
            Key::Down => {
                if !self.move_vertically(true) {
                    self.recall(false);
                }
            }
            Key::CtrlU => {
                let (start, _) = self.line_bounds();
                self.text.drain(start..self.cursor);
                self.cursor = start;
            }
            Key::CtrlK => {
                let (_, end) = self.line_bounds();
                self.text.drain(self.cursor..end);
            }
            Key::CtrlW => {
                let mut start = self.cursor;
                while start > 0
                    && self.text[start - 1].is_whitespace()
                    && self.text[start - 1] != '\n'
                {
                    start -= 1;
                }
                while start > 0 && !self.text[start - 1].is_whitespace() {
                    start -= 1;
                }
                self.text.drain(start..self.cursor);
                self.cursor = start;
            }
            _ => return false,
        }
        if !matches!(
            key,
            Key::Up | Key::Down | Key::Left | Key::Right | Key::Home | Key::End
        ) {
            self.browsing = None;
        }
        true
    }

    /// The text as rows of the box at `columns` text columns: each logical line, wrapped by columns. Returns the
    /// rows and the cursor as (row, column).
    pub fn rows(&self, columns: usize) -> (Vec<String>, (usize, usize)) {
        let columns = columns.max(2);
        let mut rows: Vec<String> = vec![String::new()];
        let mut used = 0;
        let mut cursor = (0, 0);
        for (i, &c) in self.text.iter().enumerate() {
            if c == '\n' {
                if i == self.cursor {
                    cursor = (rows.len() - 1, used);
                }
                rows.push(String::new());
                used = 0;
                continue;
            }
            let w = char_width(c);
            if used + w > columns {
                rows.push(String::new());
                used = 0;
            }
            if i == self.cursor {
                cursor = (rows.len() - 1, used);
            }
            if let Some(row) = rows.last_mut() {
                row.push(c);
            }
            used += w;
        }
        if self.cursor == self.text.len() {
            if used >= columns {
                rows.push(String::new());
                used = 0;
            }
            cursor = (rows.len() - 1, used);
        }
        (rows, cursor)
    }
}
