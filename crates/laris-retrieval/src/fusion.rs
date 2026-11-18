//! Reciprocal-rank fusion: scale-free, deterministic, ties by identifier.

use std::collections::BTreeMap;

use laris_vault::writer::safe_title;

use crate::graph::{RetrievalResult, Via};
use crate::text::round_to;

/// Smoothing constant of the reciprocal rank. Generation 1 value.
pub const RRF_K: f64 = 60.0;
/// The suffix generation 1 gives a Source note, so it stays distinct from a concept of the same word.
pub const SOURCE_SUFFIX: &str = " (source)";

/// The note name for a source path: its stem made safe, plus the suffix. Ingest and answers use the same rule so
/// the links resolve.
pub fn source_title(source: &str) -> String {
    let name = source
        .split('/')
        .rfind(|part| !part.is_empty() && *part != ".")
        .unwrap_or("");
    // pathlib: the suffix starts at the last dot unless it is the first or the last character
    let stem = match name.rfind('.') {
        Some(i) if i > 0 && i + 1 < name.len() => &name[..i],
        _ => name,
    };
    let stem = if stem.is_empty() { source } else { stem };
    format!("{}{SOURCE_SUFFIX}", safe_title(stem, "Untitled"))
}

/// Reciprocal-rank fusion of note results and corpus hits (source file names, best first). A corpus hit joins the
/// note of its Source when one exists. Returns the best `k`.
pub fn fuse_with_corpus(
    notes: &[RetrievalResult],
    corpus_sources: &[String],
    k: usize,
) -> Vec<RetrievalResult> {
    let mut ranks: BTreeMap<String, f64> = BTreeMap::new();
    let mut meta: BTreeMap<String, RetrievalResult> = BTreeMap::new();
    for (rank, item) in notes.iter().enumerate() {
        *ranks.entry(item.path.clone()).or_insert(0.0) += 1.0 / (RRF_K + rank as f64 + 1.0);
        meta.insert(item.path.clone(), item.clone());
    }
    let mut seen: Vec<String> = Vec::new();
    for (rank, source) in corpus_sources.iter().enumerate() {
        let path = format!("Sources/{}.md", source_title(source));
        if seen.contains(&path) {
            continue;
        }
        seen.push(path.clone());
        *ranks.entry(path.clone()).or_insert(0.0) += 1.0 / (RRF_K + rank as f64 + 1.0);
        meta.entry(path.clone()).or_insert(RetrievalResult {
            path,
            score: 0.0,
            via: Via::Corpus,
            seed: String::new(),
            detail: source.clone(),
        });
    }
    let mut ordered: Vec<(f64, String)> = ranks.into_iter().map(|(p, s)| (s, p)).collect();
    ordered.sort_by(|a, b| {
        round_to(b.0, 12)
            .total_cmp(&round_to(a.0, 12))
            .then_with(|| a.1.cmp(&b.1))
    });
    ordered
        .into_iter()
        .take(k)
        .filter_map(|(score, path)| {
            meta.remove(&path).map(|m| RetrievalResult {
                score: round_to(score, 10),
                ..m
            })
        })
        .collect()
}

/// A ranked list from one channel, best first.
#[derive(Debug, Clone, PartialEq)]
pub struct Channel {
    /// Name used in provenance: `bm25`, `graph`, `dense`.
    pub name: String,
    /// Weight of this channel in the sum; 1.0 by default, a non-positive weight silences the channel.
    pub weight: f64,
    /// False for a channel that has not passed its gate (a dense channel before G12).
    pub qualified: bool,
    /// Identifiers, best first.
    pub items: Vec<String>,
}

/// One fused identifier.
#[derive(Debug, Clone, PartialEq)]
pub struct Fused {
    /// Identifier, a vault-relative path.
    pub id: String,
    /// Fused score, rounded to ten places.
    pub score: f64,
    /// `(channel, 1-based rank)` for every channel that returned it, in channel order.
    pub ranks: Vec<(String, usize)>,
    /// Names of the contributing channels that are not qualified. Not empty means the answer rests on a channel
    /// that must be labelled so.
    pub unqualified_channels: Vec<String>,
}

/// Weighted reciprocal-rank fusion over any number of channels: the sum of `weight / (60 + rank)` per channel
/// (rank starts at 1), score descending, then identifier ascending. Returns the best `k`.
pub fn fuse_ranked(channels: &[Channel], k: usize) -> Vec<Fused> {
    let mut acc: BTreeMap<&str, Fused> = BTreeMap::new();
    for channel in channels {
        if channel.weight <= 0.0 {
            continue;
        }
        for (i, id) in channel.items.iter().enumerate() {
            let entry = acc.entry(id.as_str()).or_insert_with(|| Fused {
                id: id.clone(),
                score: 0.0,
                ranks: Vec::new(),
                unqualified_channels: Vec::new(),
            });
            if entry.ranks.iter().any(|(name, _)| *name == channel.name) {
                continue; // a repeated id counts once, at its best rank
            }
            entry.score += channel.weight / (RRF_K + (i + 1) as f64);
            entry.ranks.push((channel.name.clone(), i + 1));
            if !channel.qualified {
                entry.unqualified_channels.push(channel.name.clone());
            }
        }
    }
    let mut all: Vec<Fused> = acc.into_values().collect();
    all.sort_by(|a, b| {
        round_to(b.score, 12)
            .total_cmp(&round_to(a.score, 12))
            .then_with(|| a.id.cmp(&b.id))
    });
    all.truncate(k);
    for f in &mut all {
        f.score = round_to(f.score, 10);
    }
    all
}
