//! Keeps the model's reasoning away from the client (SR-S4; threat: reasoning is also a leak channel).
//!
//! Some models write their reasoning inline between tags (`<think>…</think>`); others send it in a separate
//! field. Either way it is diverted here, handed to a [`ReasoningSink`] for the operator, and never streamed.

use std::collections::VecDeque;
use std::sync::Mutex;

/// A pair of tags that wrap reasoning.
pub type TagPair = (String, String);

/// Splits a text stream into visible text and reasoning, even when a tag is cut between two chunks.
#[derive(Debug)]
pub struct ThinkSplitter {
    tags: Vec<TagPair>,
    buffer: String,
    closing: Option<String>,
    reasoning: Vec<String>,
}

/// Length of a tail of `text` that could still become one of `tags`; it is held back, not emitted.
fn keep(text: &str, tags: &[&str]) -> usize {
    let mut longest = 0;
    for tag in tags {
        let max = tag.len().saturating_sub(1).min(text.len());
        for size in (1..=max).rev() {
            if !tag.is_char_boundary(size) || !text.is_char_boundary(text.len() - size) {
                continue;
            }
            if text.ends_with(&tag[..size]) {
                longest = longest.max(size);
                break;
            }
        }
    }
    longest
}

impl ThinkSplitter {
    /// A splitter for these tag pairs; none means everything is visible.
    pub fn new(tags: &[TagPair]) -> Self {
        Self {
            tags: tags
                .iter()
                .filter(|(open, close)| !open.is_empty() && !close.is_empty())
                .cloned()
                .collect(),
            buffer: String::new(),
            closing: None,
            reasoning: Vec::new(),
        }
    }

    /// Takes a chunk; returns its visible part.
    pub fn feed(&mut self, delta: &str) -> String {
        self.buffer.push_str(delta);
        let mut visible = String::new();
        while !self.buffer.is_empty() {
            if let Some(closing) = self.closing.clone() {
                if let Some(end) = self.buffer.find(&closing) {
                    self.reasoning.push(self.buffer[..end].to_owned());
                    self.buffer.drain(..end + closing.len());
                    self.closing = None;
                    continue;
                }
                let cut = self.buffer.len() - keep(&self.buffer, &[closing.as_str()]);
                self.reasoning.push(self.buffer[..cut].to_owned());
                self.buffer.drain(..cut);
                break;
            }
            let first = self
                .tags
                .iter()
                .filter_map(|(open, close)| {
                    self.buffer.find(open.as_str()).map(|at| (at, open, close))
                })
                .min_by_key(|(at, _, _)| *at);
            if let Some((at, open, close)) = first {
                let (open_len, close) = (open.len(), close.clone());
                visible.push_str(&self.buffer[..at]);
                self.buffer.drain(..at + open_len);
                self.closing = Some(close);
                continue;
            }
            let openers: Vec<&str> = self.tags.iter().map(|(o, _)| o.as_str()).collect();
            let cut = self.buffer.len() - keep(&self.buffer, &openers);
            visible.push_str(&self.buffer[..cut]);
            self.buffer.drain(..cut);
            break;
        }
        visible
    }

    /// The end of the stream: unfinished reasoning stays reasoning.
    pub fn finish(&mut self) -> String {
        let rest = std::mem::take(&mut self.buffer);
        if self.closing.is_some() {
            self.reasoning.push(rest);
            return String::new();
        }
        rest
    }

    /// The reasoning seen so far.
    pub fn take_reasoning(&mut self) -> String {
        self.reasoning.drain(..).collect()
    }
}

/// What the operator keeps of one answer's reasoning. It holds no answer text.
#[derive(Debug, Clone, PartialEq)]
pub struct ReasoningRecord {
    /// Session id.
    pub session_id: String,
    /// Model name.
    pub model: String,
    /// SHA-256 of the composed system prompt.
    pub prompt_sha256: String,
    /// The reasoning.
    pub reasoning: String,
    /// Unix seconds.
    pub at: f64,
}

/// Where the reasoning goes. It is written when the answer ends, fails or is dropped.
pub trait ReasoningSink: Send + Sync + 'static {
    /// Keeps one record.
    fn record(&self, record: ReasoningRecord);
}

/// A bounded in-memory store, newest last. The operator reads it at `GET /v1/admin/reasoning`.
#[derive(Debug)]
pub struct MemoryReasoning {
    cap: usize,
    items: Mutex<VecDeque<ReasoningRecord>>,
}

impl MemoryReasoning {
    /// A store of at most `cap` records; the oldest go first.
    pub fn new(cap: usize) -> Self {
        Self {
            cap: cap.max(1),
            items: Mutex::new(VecDeque::new()),
        }
    }

    /// The newest `limit` records, newest first.
    pub fn recent(&self, limit: usize) -> Vec<ReasoningRecord> {
        let items = self.items.lock().unwrap_or_else(|e| e.into_inner());
        items.iter().rev().take(limit).cloned().collect()
    }
}

impl ReasoningSink for MemoryReasoning {
    fn record(&self, record: ReasoningRecord) {
        let mut items = self.items.lock().unwrap_or_else(|e| e.into_inner());
        if items.len() >= self.cap {
            items.pop_front();
        }
        items.push_back(record);
    }
}

/// A sink that keeps nothing.
#[derive(Debug, Default, Clone, Copy)]
pub struct DiscardReasoning;

impl ReasoningSink for DiscardReasoning {
    fn record(&self, _record: ReasoningRecord) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    fn splitter() -> ThinkSplitter {
        ThinkSplitter::new(&[("<think>".into(), "</think>".into())])
    }

    fn run(chunks: &[&str]) -> (String, String) {
        let mut s = splitter();
        let mut visible = String::new();
        for c in chunks {
            visible.push_str(&s.feed(c));
        }
        visible.push_str(&s.finish());
        (visible, s.take_reasoning())
    }

    #[test]
    fn inline_reasoning_is_diverted() {
        let (v, r) = run(&["Hello <think>secret plan</think>world"]);
        assert_eq!((v.as_str(), r.as_str()), ("Hello world", "secret plan"));
    }

    #[test]
    fn tags_cut_between_chunks_are_still_found() {
        let (v, r) = run(&["Hi <thi", "nk>plan", " more</th", "ink> done"]);
        assert_eq!(v, "Hi  done");
        assert_eq!(r, "plan more");
    }

    #[test]
    fn every_split_point_gives_the_same_split() {
        let whole = "A <think>hidden é thought</think> B <think>two</think>C";
        let want = run(&[whole]);
        let chars: Vec<usize> = whole.char_indices().map(|(i, _)| i).collect();
        for &i in &chars {
            for &j in &chars {
                if i <= j {
                    assert_eq!(run(&[&whole[..i], &whole[i..j], &whole[j..]]), want);
                }
            }
        }
    }

    #[test]
    fn unfinished_reasoning_stays_reasoning() {
        let (v, r) = run(&["ok <think>never closed"]);
        assert_eq!(v, "ok ");
        assert_eq!(r, "never closed");
    }

    #[test]
    fn a_lone_angle_bracket_is_text() {
        let (v, _) = run(&["a < b and <thing>"]);
        assert_eq!(v, "a < b and <thing>");
    }

    #[test]
    fn no_tags_means_no_splitting() {
        let mut s = ThinkSplitter::new(&[]);
        assert_eq!(s.feed("<think>x</think>"), "<think>x</think>");
    }

    #[test]
    fn the_store_is_bounded() {
        let store = MemoryReasoning::new(2);
        for i in 0..3 {
            store.record(ReasoningRecord {
                session_id: format!("s{i}"),
                model: String::new(),
                prompt_sha256: String::new(),
                reasoning: String::new(),
                at: 0.0,
            });
        }
        let ids: Vec<_> = store.recent(10).into_iter().map(|r| r.session_id).collect();
        assert_eq!(ids, ["s2", "s1"]);
    }
}
