//! What a turn actually received: retrieved hits and the brain titles of `LarisMeta`.

use crate::text::fold;
use laris_protocol::LarisMeta;
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

/// One retrieved hit.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Hit {
    /// The source (file or document name).
    pub source: String,
    /// Its rank in the tool result.
    pub rank: u32,
    /// Its title, when the result had one.
    pub title: String,
    /// The excerpt.
    pub text: String,
}

/// The evidence of one turn. Ranks repeat across searches, so a citation matches any hit with its source and rank.
#[derive(Clone, Debug, Default)]
pub struct Evidence {
    hits: Vec<Hit>,
    brain: Vec<String>,
}

static HIT_LINE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^\s*(?:[-*]\s+)?\[([^\[\]\n#]{1,200}?)\s+#(\d{1,6})\]\s*(.*)$")
        .expect("valid hit pattern")
});

impl Evidence {
    /// No evidence.
    pub fn new() -> Self {
        Self::default()
    }

    /// Adds a hit (an identical one is kept once).
    pub fn add(&mut self, hit: Hit) {
        if !self.hits.contains(&hit) {
            self.hits.push(hit);
        }
    }

    /// Reads the hits of a tool result written as text: lines `[source #rank] title: excerpt`, each excerpt running on
    /// until a blank line or the next hit. Returns how many it found.
    pub fn absorb_text(&mut self, text: &str) -> usize {
        let mut found = 0;
        let mut open: Option<Hit> = None;
        for line in text.lines() {
            if let Some(caps) = HIT_LINE.captures(line)
                && let Ok(rank) = caps[2].parse::<u32>()
            {
                if let Some(hit) = open.take() {
                    self.add(hit);
                }
                open = Some(Hit {
                    source: caps[1].trim().to_string(),
                    rank,
                    title: String::new(),
                    text: caps[3].trim().to_string(),
                });
                found += 1;
            } else if line.trim().is_empty() {
                if let Some(hit) = open.take() {
                    self.add(hit);
                }
            } else if let Some(hit) = open.as_mut() {
                hit.text.push(' ');
                hit.text.push_str(line.trim());
            }
        }
        if let Some(hit) = open {
            self.add(hit);
        }
        found
    }

    /// Reads the hits of a tool result written as JSON: any object with a `source`, a `rank` and an excerpt under
    /// `text`, `excerpt`, `snippet` or `content`, at any depth, and text lines inside string values. Returns how many.
    pub fn absorb_json(&mut self, value: &Value) -> usize {
        match value {
            Value::Object(map) => {
                let source = map.get("source").and_then(Value::as_str);
                let rank = map
                    .get("rank")
                    .and_then(Value::as_u64)
                    .and_then(|r| u32::try_from(r).ok());
                let excerpt = ["text", "excerpt", "snippet", "content"]
                    .iter()
                    .find_map(|key| map.get(*key).and_then(Value::as_str));
                if let (Some(source), Some(rank), Some(text)) = (source, rank, excerpt) {
                    self.add(Hit {
                        source: source.trim().to_string(),
                        rank,
                        title: map
                            .get("title")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        text: text.to_string(),
                    });
                    1
                } else {
                    map.values().map(|v| self.absorb_json(v)).sum()
                }
            }
            Value::Array(items) => items.iter().map(|v| self.absorb_json(v)).sum(),
            Value::String(text) if text.contains('#') => self.absorb_text(text),
            _ => 0,
        }
    }

    /// Takes the brain titles of a response's `laris` block.
    pub fn set_brain(&mut self, meta: &LarisMeta) {
        self.brain = meta.brain.clone();
    }

    /// The same, as a builder.
    pub fn with_brain(mut self, meta: &LarisMeta) -> Self {
        self.set_brain(meta);
        self
    }

    /// Whether the turn has no retrieved hit.
    pub fn is_empty(&self) -> bool {
        self.hits.is_empty()
    }

    /// The hits.
    pub fn hits(&self) -> &[Hit] {
        &self.hits
    }

    /// The hits a citation `[source #rank]` can mean (source compared without case or extra spaces).
    pub fn matching(&self, source: &str, rank: u32) -> Vec<&Hit> {
        let wanted = fold(source);
        self.hits
            .iter()
            .filter(|h| h.rank == rank && fold(&h.source) == wanted)
            .collect()
    }

    /// Whether `title` is one of the brain notes the server listed.
    pub fn has_brain(&self, title: &str) -> bool {
        let wanted = fold(title);
        self.brain.iter().any(|t| fold(t) == wanted)
    }
}
