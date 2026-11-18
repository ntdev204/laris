//! BM25 over vault notes: body and title, deterministic.

use std::collections::{BTreeSet, HashMap};

use laris_vault::VaultIndex;

use crate::text::{round_to, tokens};

const K1: f64 = 1.5;
const B: f64 = 0.75;
/// A title word counts as this many body words.
const TITLE_WEIGHT: usize = 3;

/// A note and its score (rounded to eight places, as generation 1 returns it).
#[derive(Debug, Clone, PartialEq)]
pub struct Hit {
    /// Vault-relative path.
    pub path: String,
    /// BM25 score.
    pub score: f64,
}

/// An inverted index over the notes of a vault, optionally restricted to top-level folders.
pub struct NoteSearch {
    paths: Vec<String>,
    lengths: Vec<usize>,
    avg: f64,
    /// term -> (document, term frequency), documents ascending.
    postings: HashMap<String, Vec<(u32, u32)>>,
}

impl NoteSearch {
    /// Indexes every note (or those whose first path segment is in `folders`, when it is not empty).
    pub fn new(index: &VaultIndex, folders: &[String]) -> NoteSearch {
        let mut paths = Vec::new();
        let mut lengths = Vec::new();
        let mut postings: HashMap<String, Vec<(u32, u32)>> = HashMap::new();
        for (path, note) in &index.notes {
            if !folders.is_empty() && !folders.iter().any(|f| path.split('/').next() == Some(f)) {
                continue;
            }
            let mut words = tokens(&note.body);
            let title = tokens(&note.title);
            for _ in 0..TITLE_WEIGHT {
                words.extend(title.iter().cloned());
            }
            let doc = paths.len() as u32;
            let mut counts: HashMap<&str, u32> = HashMap::new();
            for word in &words {
                *counts.entry(word.as_str()).or_insert(0) += 1;
            }
            for (word, tf) in counts {
                postings
                    .entry(word.to_string())
                    .or_default()
                    .push((doc, tf));
            }
            lengths.push(words.len());
            paths.push(path.clone());
        }
        let total: usize = lengths.iter().sum();
        let avg = if lengths.is_empty() {
            0.0
        } else {
            total as f64 / lengths.len() as f64
        };
        NoteSearch {
            paths,
            lengths,
            avg,
            postings,
        }
    }

    /// Number of indexed notes.
    pub fn len(&self) -> usize {
        self.paths.len()
    }

    /// True when no note is indexed.
    pub fn is_empty(&self) -> bool {
        self.paths.is_empty()
    }

    /// The best `limit` notes for `query`: score descending, then path ascending.
    pub fn search(&self, query: &str, limit: usize) -> Vec<Hit> {
        let terms: BTreeSet<String> = tokens(query).into_iter().collect();
        let n = self.paths.len() as f64;
        let avg = if self.avg == 0.0 { 1.0 } else { self.avg };
        let mut scores = vec![0.0_f64; self.paths.len()];
        let mut touched: Vec<u32> = Vec::new();
        let mut seen = vec![false; self.paths.len()];
        // terms are visited in sorted order, so every note's sum is built in the order generation 1 uses
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
                if !seen[d] {
                    seen[d] = true;
                    touched.push(doc);
                }
            }
        }
        let mut scored: Vec<(f64, &str)> = touched
            .iter()
            .filter(|&&d| scores[d as usize] > 0.0)
            .map(|&d| {
                (
                    round_to(scores[d as usize], 8),
                    self.paths[d as usize].as_str(),
                )
            })
            .collect();
        scored.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| a.1.cmp(b.1)));
        scored
            .into_iter()
            .take(limit)
            .map(|(score, path)| Hit {
                path: path.to_string(),
                score,
            })
            .collect()
    }
}
