//! Styled text: spans, lines, the theme, and how they become ANSI.

use crate::width::str_width;
use laris_config::settings::Theme as ThemeSetting;

/// A terminal colour.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Color {
    /// The terminal's own.
    #[default]
    Default,
    /// Red.
    Red,
    /// Green.
    Green,
    /// Yellow.
    Yellow,
    /// Blue.
    Blue,
    /// Magenta.
    Magenta,
    /// Cyan.
    Cyan,
    /// Grey.
    Gray,
}

impl Color {
    fn code(self) -> Option<u8> {
        match self {
            Self::Default => None,
            Self::Red => Some(31),
            Self::Green => Some(32),
            Self::Yellow => Some(33),
            Self::Blue => Some(34),
            Self::Magenta => Some(35),
            Self::Cyan => Some(36),
            Self::Gray => Some(90),
        }
    }
}

/// How a span looks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Style {
    /// Colour.
    pub fg: Color,
    /// Bold.
    pub bold: bool,
    /// Dim.
    pub dim: bool,
    /// Italic.
    pub italic: bool,
    /// Underlined.
    pub underline: bool,
}

impl Style {
    /// Plain.
    pub const PLAIN: Self = Self {
        fg: Color::Default,
        bold: false,
        dim: false,
        italic: false,
        underline: false,
    };

    /// With a colour.
    #[must_use]
    pub const fn fg(mut self, fg: Color) -> Self {
        self.fg = fg;
        self
    }

    /// Bold.
    #[must_use]
    pub const fn bold(mut self) -> Self {
        self.bold = true;
        self
    }

    /// Dim.
    #[must_use]
    pub const fn dim(mut self) -> Self {
        self.dim = true;
        self
    }

    /// Italic.
    #[must_use]
    pub const fn italic(mut self) -> Self {
        self.italic = true;
        self
    }

    /// Underlined.
    #[must_use]
    pub const fn underline(mut self) -> Self {
        self.underline = true;
        self
    }

    /// `self` with what `over` adds on top (a colour replaces, flags add up).
    #[must_use]
    pub fn on(self, over: Style) -> Style {
        Style {
            fg: if over.fg == Color::Default {
                self.fg
            } else {
                over.fg
            },
            bold: self.bold || over.bold,
            dim: self.dim || over.dim,
            italic: self.italic || over.italic,
            underline: self.underline || over.underline,
        }
    }

    fn escape(self) -> String {
        let mut codes: Vec<String> = Vec::new();
        if self.bold {
            codes.push("1".into());
        }
        if self.dim {
            codes.push("2".into());
        }
        if self.italic {
            codes.push("3".into());
        }
        if self.underline {
            codes.push("4".into());
        }
        if let Some(c) = self.fg.code() {
            codes.push(c.to_string());
        }
        if codes.is_empty() {
            String::new()
        } else {
            format!("\x1b[{}m", codes.join(";"))
        }
    }
}

/// Text in one style.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Span {
    /// The text; never holds a newline or a control character.
    pub text: String,
    /// The style.
    pub style: Style,
}

impl Span {
    /// A span.
    pub fn new(text: impl Into<String>, style: Style) -> Self {
        Self {
            text: text.into(),
            style,
        }
    }
}

/// One line of the screen.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Line(pub Vec<Span>);

impl Line {
    /// A line of one span.
    pub fn styled(text: impl Into<String>, style: Style) -> Self {
        Self(vec![Span::new(text, style)])
    }

    /// An unstyled line.
    pub fn plain(text: impl Into<String>) -> Self {
        Self::styled(text, Style::PLAIN)
    }

    /// An empty line.
    pub fn blank() -> Self {
        Self::default()
    }

    /// Appends a span.
    pub fn push(&mut self, text: impl Into<String>, style: Style) {
        self.0.push(Span::new(text, style));
    }

    /// Columns.
    pub fn width(&self) -> usize {
        self.0.iter().map(|s| str_width(&s.text)).sum()
    }

    /// The text without styles.
    pub fn text(&self) -> String {
        self.0.iter().map(|s| s.text.as_str()).collect()
    }

    /// The text without styles and without trailing spaces.
    pub fn trimmed(&self) -> String {
        self.text().trim_end().to_owned()
    }

    /// `self` followed by `other`.
    #[must_use]
    pub fn then(mut self, other: Line) -> Self {
        self.0.extend(other.0);
        self
    }

    /// Pads with spaces to `columns`.
    pub fn pad(&mut self, columns: usize) {
        let w = self.width();
        if w < columns {
            self.push(" ".repeat(columns - w), Style::PLAIN);
        }
    }
}

/// What things look like. Colours carry meaning; with `mono` only bold, dim and underline are used.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Theme {
    mono: bool,
    light: bool,
}

impl Theme {
    /// The theme of the `ui.theme` setting; `Auto` is taken to be dark.
    pub fn of(setting: ThemeSetting) -> Self {
        Self {
            mono: false,
            light: setting == ThemeSetting::Light,
        }
    }

    /// No colours at all.
    pub fn mono() -> Self {
        Self {
            mono: true,
            light: false,
        }
    }

    fn colour(self, c: Color) -> Style {
        if self.mono {
            Style::PLAIN
        } else {
            Style::PLAIN.fg(c)
        }
    }

    /// The brand colour: the banner, the bullet of an answer.
    pub fn accent(self) -> Style {
        self.colour(Color::Magenta).on(Style::PLAIN.bold())
    }

    /// What the user typed.
    pub fn user(self) -> Style {
        Style::PLAIN.bold()
    }

    /// Less important text.
    pub fn dim(self) -> Style {
        if self.mono || !self.light {
            Style::PLAIN.dim()
        } else {
            self.colour(Color::Gray)
        }
    }

    /// Tool names.
    pub fn tool(self) -> Style {
        self.colour(Color::Cyan).on(Style::PLAIN.bold())
    }

    /// Errors.
    pub fn error(self) -> Style {
        self.colour(Color::Red)
    }

    /// Success.
    pub fn success(self) -> Style {
        self.colour(Color::Green)
    }

    /// Warnings and the armed exit.
    pub fn warn(self) -> Style {
        self.colour(Color::Yellow)
    }

    /// Headings.
    pub fn heading(self) -> Style {
        self.colour(Color::Cyan).on(Style::PLAIN.bold())
    }

    /// Inline code.
    pub fn code(self) -> Style {
        self.colour(Color::Yellow)
    }

    /// Links.
    pub fn link(self) -> Style {
        self.colour(Color::Blue).on(Style::PLAIN.underline())
    }

    /// Keywords in code.
    pub fn keyword(self) -> Style {
        self.colour(Color::Magenta)
    }

    /// Strings in code.
    pub fn string(self) -> Style {
        self.colour(Color::Green)
    }

    /// Numbers in code.
    pub fn number(self) -> Style {
        self.colour(Color::Cyan)
    }

    /// Comments in code.
    pub fn comment(self) -> Style {
        self.dim().on(Style::PLAIN.italic())
    }

    /// Borders.
    pub fn border(self) -> Style {
        self.dim()
    }
}

/// Lines as text, one per line, without styles and without trailing spaces: what tests compare.
pub fn plain(lines: &[Line]) -> String {
    let mut out = String::new();
    for line in lines {
        out.push_str(&line.trimmed());
        out.push('\n');
    }
    out
}

/// Lines as bytes for a terminal. With `color` off there are no escape sequences at all.
pub fn ansi(lines: &[Line], color: bool) -> String {
    let mut out = String::new();
    for line in lines {
        for span in &line.0 {
            let escape = if color {
                span.style.escape()
            } else {
                String::new()
            };
            if escape.is_empty() {
                out.push_str(&span.text);
            } else {
                out.push_str(&escape);
                out.push_str(&span.text);
                out.push_str("\x1b[0m");
            }
        }
        out.push('\n');
    }
    out
}
