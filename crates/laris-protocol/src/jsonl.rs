//! JSON-lines encoding of core events and commands: one JSON object per line, each with a `type`.

use crate::events::{COMMAND_TYPES, Command, EVENT_TYPES, Event};
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::fmt;

/// A line that is not a valid message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LineError(pub String);

impl fmt::Display for LineError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for LineError {}

/// One message as a line with a final newline.
pub fn encode<T: Serialize>(message: &T) -> String {
    let mut line = serde_json::to_string(message).unwrap_or_default();
    line.push('\n');
    line
}

fn decode<T: DeserializeOwned>(line: &str, kinds: &[&str], what: &str) -> Result<T, LineError> {
    let value: Value = serde_json::from_str(line.trim()).map_err(|_| {
        LineError(format!(
            "not JSON: {}",
            line.trim().chars().take(120).collect::<String>()
        ))
    })?;
    let Some(object) = value.as_object() else {
        return Err(LineError(format!("{what} must be a JSON object")));
    };
    match object.get("type").and_then(Value::as_str) {
        Some(kind) if kinds.contains(&kind) => {}
        other => {
            return Err(LineError(format!(
                "unknown {what} type {}",
                other.map_or("null".to_owned(), |k| format!("{k:?}"))
            )));
        }
    }
    serde_json::from_value(value).map_err(|e| LineError(format!("invalid {what}: {e}")))
}

/// Decodes one event line. An unknown type is an error, not a crash.
pub fn decode_event(line: &str) -> Result<Event, LineError> {
    decode(line, &EVENT_TYPES, "event")
}

/// Decodes one command line.
pub fn decode_command(line: &str) -> Result<Command, LineError> {
    decode(line, &COMMAND_TYPES, "command")
}

/// Cuts a byte stream into complete lines, however the bytes arrive. Blank lines are dropped and a
/// final line without a newline waits for [`LineBuffer::finish`].
#[derive(Debug, Default)]
pub struct LineBuffer {
    pending: Vec<u8>,
}

impl LineBuffer {
    /// An empty buffer.
    pub fn new() -> Self {
        Self::default()
    }

    /// Adds bytes and returns the lines they completed.
    pub fn feed(&mut self, bytes: &[u8]) -> Vec<String> {
        let mut lines = Vec::new();
        for &b in bytes {
            if b == b'\n' {
                push_line(&mut lines, std::mem::take(&mut self.pending));
            } else {
                self.pending.push(b);
            }
        }
        lines
    }

    /// The last line, when the stream ended without a newline.
    pub fn finish(&mut self) -> Option<String> {
        let mut lines = Vec::new();
        push_line(&mut lines, std::mem::take(&mut self.pending));
        lines.pop()
    }
}

fn push_line(lines: &mut Vec<String>, bytes: Vec<u8>) {
    let text = String::from_utf8_lossy(&bytes);
    let text = text.trim();
    if !text.is_empty() {
        lines.push(text.to_owned());
    }
}
