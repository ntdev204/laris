//! BM25 over the passages of ingested documents (SR-H13, SR-L3).
//!
//! A passage is a run of characters of a document, with the span it came from. The index ranks passages by Okapi
//! BM25 over their words and gives each hit the span, so an answer can quote it and the quote can be checked against
//! the document. Everything is deterministic: score descending, then source, then start.

use std::collections::{BTreeSet, HashMap};

use crate::text::{round_to, tokens};

const K1: f64 = 1.5;
const B: f64 = 0.75;

/// A passage as the index takes it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PassageRecord {
    /// Stable id of the passage.
    pub id: String,
    /// Where the document came from (a path or a title); what an answer cites.
    pub source: String,
    /// Character offset of the first character in the document text.
    pub start: usize,
    /// Character offset after the last character.
    pub end: usize,
    /// The text, equal to the characters `start..end` of the document.
    pub text: String,
}

/// A ranked passage.
#[derive(Debug, Clone, PartialEq)]
pub struct PassageHit {
    /// The passage.
    pub passage: PassageRecord,
    /// BM25 score, rounded to eight places.
    pub score: f64,
}

/// An inverted index over passages.
pub struct PassageIndex {
    passages: Vec<PassageRecord>,
    lengths: Vec<usize>,
    avg: f64,
    postings: HashMap<String, Vec<(u32, u32)>>,
}

impl PassageIndex {
    /// Indexes `passages`.
    pub fn new(passages: Vec<PassageRecord>) -> PassageIndex {
        let mut lengths = Vec::with_capacity(passages.len());
        let mut postings: HashMap<String, Vec<(u32, u32)>> = HashMap::new();
        for (doc, passage) in passages.iter().enumerate() {
            let words = tokens(&passage.text);
            let mut counts: HashMap<&str, u32> = HashMap::new();
            for word in &words {
                *counts.entry(word.as_str()).or_insert(0) += 1;
            }
            for (word, tf) in counts {
                postings
                    .entry(word.to_owned())
                    .or_default()
                    .push((doc as u32, tf));
            }
            lengths.push(words.len());
        }
        let total: usize = lengths.iter().sum();
        let avg = if lengths.is_empty() {
            0.0
        } else {
            total as f64 / lengths.len() as f64
        };
        PassageIndex {
            passages,
            lengths,
            avg,
            postings,
        }
    }

    /// Number of passages.
    pub fn len(&self) -> usize {
        self.passages.len()
    }

    /// True when nothing is indexed.
    pub fn is_empty(&self) -> bool {
        self.passages.is_empty()
    }

    /// The best `limit` passages for `query`. A passage that shares no word with the query is never returned.
    pub fn search(&self, query: &str, limit: usize) -> Vec<PassageHit> {
        let terms: BTreeSet<String> = tokens(query).into_iter().collect();
        let n = self.passages.len() as f64;
        let avg = if self.avg == 0.0 { 1.0 } else { self.avg };
        let mut scores = vec![0.0_f64; self.passages.len()];
        for term in &terms {
            let Some(posting) = self.postings.get(term) else {
                continue;
            };
            let df = posting.len() as f64;
            let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
            for &(doc, tf) in posting {
                let d = doc as usize;
                let tf = f64::from(tf);
                let norm = tf + K1 * (1.0 - B + B * self.lengths[d] as f64 / avg);
                scores[d] += idf * tf * (K1 + 1.0) / norm;
            }
        }
        let mut scored: Vec<(f64, usize)> = scores
            .iter()
            .enumerate()
            .filter(|(_, s)| **s > 0.0)
            .map(|(d, s)| (round_to(*s, 8), d))
            .collect();
        scored.sort_by(|a, b| {
            b.0.total_cmp(&a.0).then_with(|| {
                let (x, y) = (&self.passages[a.1], &self.passages[b.1]);
                x.source.cmp(&y.source).then(x.start.cmp(&y.start))
            })
        });
        scored
            .into_iter()
            .take(limit)
            .map(|(score, d)| PassageHit {
                passage: self.passages[d].clone(),
                score,
            })
            .collect()
    }
}
