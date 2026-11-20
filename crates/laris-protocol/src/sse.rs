//! Server-sent events of P1 and P2: `data: <json>` blocks closed by `data: [DONE]`.
//!
//! An error after a stream has started is an `error` event followed by `[DONE]` (SR-P1).

use crate::p1::ChatResponseChunk;
use crate::p2::ChatCompletionChunk;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fmt;

/// Payload that closes every stream.
pub const DONE: &str = "[DONE]";

/// Message and type of a failure.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ErrorDetail {
    /// Human-readable message.
    pub message: String,
    /// Error class name or code.
    #[serde(rename = "type", default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// The event sent when a stream fails after it started; `[DONE]` follows it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct StreamError {
    /// The failure.
    pub error: ErrorDetail,
}

/// A malformed stream.
#[derive(Debug)]
pub enum SseError {
    /// A `data:` line is not valid JSON of the expected shape.
    Json(serde_json::Error),
    /// The bytes are not UTF-8.
    Utf8,
}

impl fmt::Display for SseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Json(e) => write!(f, "invalid event payload: {e}"),
            Self::Utf8 => f.write_str("event stream is not UTF-8"),
        }
    }
}

impl std::error::Error for SseError {}

/// One event of a P1 chat stream.
#[derive(Debug, Clone, PartialEq)]
#[allow(clippy::large_enum_variant)] // one event at a time; boxing would change every consumer
pub enum P1Event {
    /// A chunk (text, tool calls, evidence list or usage).
    Chunk(ChatResponseChunk),
    /// The stream failed after it started.
    Error(StreamError),
    /// `[DONE]`.
    Done,
}

/// One event of a P2 stream.
#[derive(Debug, Clone, PartialEq)]
pub enum P2Event {
    /// A chunk.
    Chunk(ChatCompletionChunk),
    /// The model failed after the stream started.
    Error(StreamError),
    /// `[DONE]`.
    Done,
}

fn parse(data: &str) -> Result<Parsed, SseError> {
    if data == DONE {
        return Ok(Parsed::Done);
    }
    let value: Value = serde_json::from_str(data).map_err(SseError::Json)?;
    if value.get("error").is_some() {
        serde_json::from_value(value)
            .map(Parsed::Error)
            .map_err(SseError::Json)
    } else {
        Ok(Parsed::Data(value))
    }
}

enum Parsed {
    Done,
    Error(StreamError),
    Data(Value),
}

impl P1Event {
    /// Decodes the data of one event.
    pub fn from_data(data: &str) -> Result<Self, SseError> {
        Ok(match parse(data)? {
            Parsed::Done => Self::Done,
            Parsed::Error(e) => Self::Error(e),
            Parsed::Data(v) => Self::Chunk(serde_json::from_value(v).map_err(SseError::Json)?),
        })
    }

    /// Encodes the event as bytes ready to send.
    pub fn encode(&self) -> Vec<u8> {
        match self {
            Self::Chunk(c) => encode_json(c),
            Self::Error(e) => encode_json(e),
            Self::Done => encode_done(),
        }
    }
}

impl P2Event {
    /// Decodes the data of one event.
    pub fn from_data(data: &str) -> Result<Self, SseError> {
        Ok(match parse(data)? {
            Parsed::Done => Self::Done,
            Parsed::Error(e) => Self::Error(e),
            Parsed::Data(v) => Self::Chunk(serde_json::from_value(v).map_err(SseError::Json)?),
        })
    }

    /// Encodes the event as bytes ready to send.
    pub fn encode(&self) -> Vec<u8> {
        match self {
            Self::Chunk(c) => encode_json(c),
            Self::Error(e) => encode_json(e),
            Self::Done => encode_done(),
        }
    }
}

fn encode_json<T: Serialize>(payload: &T) -> Vec<u8> {
    // Serialising these types cannot fail: every key is a string and every value is JSON.
    let json = serde_json::to_string(payload).unwrap_or_default();
    format!("data: {json}\n\n").into_bytes()
}

/// The closing event.
pub fn encode_done() -> Vec<u8> {
    format!("data: {DONE}\n\n").into_bytes()
}

/// Incremental decoder: feed bytes as they arrive, get the data of every complete event.
///
/// Events end at a blank line; lines other than `data:` (comments, `event:`) are skipped, and several
/// `data:` lines of one event are joined with `\n`, as the SSE standard says.
#[derive(Debug, Default)]
pub struct SseDecoder {
    buffer: Vec<u8>,
}

impl SseDecoder {
    /// An empty decoder.
    pub fn new() -> Self {
        Self::default()
    }

    /// Adds bytes and returns the data of the events they complete.
    pub fn feed(&mut self, bytes: &[u8]) -> Result<Vec<String>, SseError> {
        self.buffer.extend_from_slice(bytes);
        let mut events = Vec::new();
        while let Some((end, sep)) = find_boundary(&self.buffer) {
            let block: Vec<u8> = self.buffer.drain(..end + sep).collect();
            let text = std::str::from_utf8(&block[..end]).map_err(|_| SseError::Utf8)?;
            let mut data: Vec<&str> = Vec::new();
            for line in text.lines() {
                if let Some(rest) = line.strip_prefix("data:") {
                    data.push(rest.strip_prefix(' ').unwrap_or(rest));
                }
            }
            if !data.is_empty() {
                events.push(data.join("\n"));
            }
        }
        Ok(events)
    }

    /// Whether bytes of an unfinished event are waiting.
    pub fn has_pending(&self) -> bool {
        !self.buffer.iter().all(u8::is_ascii_whitespace)
    }
}

/// Position of the first blank line and the length of its separator.
fn find_boundary(buf: &[u8]) -> Option<(usize, usize)> {
    let mut i = 0;
    while i < buf.len() {
        if buf[i..].starts_with(b"\r\n\r\n") {
            return Some((i, 4));
        }
        if buf[i..].starts_with(b"\n\n") {
            return Some((i, 2));
        }
        i += 1;
    }
    None
}
