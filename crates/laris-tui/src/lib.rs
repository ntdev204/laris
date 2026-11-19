//! Terminal interface (SR-C1).
//!
//! The interface draws what the core says and sends what the user does; it holds no tool, permission or storage
//! logic. It is built from parts that do not touch the terminal, so every one can be tested:
//!
//! * [`width`]: columns of a character, wrapping and cutting by columns.
//! * [`style`]: styled lines, the theme, and their conversion to text or ANSI.
//! * [`markdown`] and [`highlight`]: Markdown and code for the terminal; a streamed answer is rendered line by line.
//! * [`input`]: the input box's text, cursor and history, and the keys.
//! * [`App`]: the state, changed by [`Input`]s (keys, pastes, core events, clock ticks) which give back the commands
//!   to send; [`App::layout`] draws it at a width as final lines and live lines.
//! * [`replay`]: drives an [`App`] with a recorded core, a scenario of `laris-protocol`.
//!
//! The raw-mode loop that reads the keyboard and writes to the screen needs `crossterm`, which is approved (T119)
//! but not vendored yet; it is built on this with the real core in T158.

pub mod app;
pub mod highlight;
pub mod input;
pub mod markdown;
pub mod replay;
pub mod style;
pub mod view;
pub mod width;

pub use app::{App, Info, Input, Item, Tone};
pub use input::{InputBuffer, Key};
pub use style::{Color, Line, Span, Style, Theme, ansi, plain};
pub use view::Layout;
