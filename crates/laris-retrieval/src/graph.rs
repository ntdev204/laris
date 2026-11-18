//! Graph-aware retrieval: BM25 finds seed notes, the links around each seed are added with a decayed score (a note
//! that explains a hit is usually next to it, even when it shares no words with the query).

use std::collections::{BTreeMap, BTreeSet};

use laris_vault::VaultIndex;

use crate::search::NoteSearch;
use crate::text::round_to;

/// How a note came into the results.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Via {
    /// Found by BM25.
    Bm25,
    /// Brought in by the links around a BM25 hit.
    Link,
    /// Found in the corpus search (see [`crate::fuse_with_corpus`]).
    Corpus,
}

impl Via {
    /// The label generation 1 uses: `bm25`, `link`, `corpus`.
    pub fn as_str(self) -> &'static str {
        match self {
            Via::Bm25 => "bm25",
            Via::Link => "link",
            Via::Corpus => "corpus",
        }
    }
}

/// One retrieved note.
#[derive(Debug, Clone, PartialEq)]
pub struct RetrievalResult {
    /// Vault-relative path.
    pub path: String,
    /// Score: 1.0 for the best BM25 note, relative values below.
    pub score: f64,
    /// How it came in.
    pub via: Via,
    /// For a link result: the note whose neighbourhood brought it in.
    pub seed: String,
    /// `rank N` for a BM25 result, `linked` for a link result, the source file for a corpus result.
    pub detail: String,
}

/// Tunables of the graph expansion. Generation 1 defaults.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GraphConfig {
    /// BM25 notes used as seeds.
    pub seeds: usize,
    /// Weight of a link against a direct hit.
    pub link_weight: f64,
    /// Decay applied on top of the link weight.
    pub decay: f64,
}

impl Default for GraphConfig {
    fn default() -> GraphConfig {
        GraphConfig {
            seeds: 5,
            link_weight: 0.4,
            decay: 0.8,
        }
    }
}

/// BM25 seeds expanded along the links of the vault.
pub struct GraphRetriever<'a> {
    index: &'a VaultIndex,
    folders: Vec<String>,
    search: NoteSearch,
    config: GraphConfig,
}

impl<'a> GraphRetriever<'a> {
    /// A retriever over `index`, restricted to the top-level `folders` when the list is not empty.
    pub fn new(
        index: &'a VaultIndex,
        folders: &[String],
        config: GraphConfig,
    ) -> GraphRetriever<'a> {
        GraphRetriever {
            index,
            folders: folders.to_vec(),
            search: NoteSearch::new(index, folders),
            config,
        }
    }

    fn allowed(&self, path: &str) -> bool {
        self.folders.is_empty()
            || self
                .folders
                .iter()
                .any(|f| path.split('/').next() == Some(f))
    }

    /// The best `k` notes for `query`: score (rounded to ten places) descending, then path ascending.
    pub fn retrieve(&self, query: &str, k: usize) -> Vec<RetrievalResult> {
        let base = self.search.search(query, self.config.seeds);
        let Some(first) = base.first() else {
            return Vec::new();
        };
        let top = if first.score == 0.0 { 1.0 } else { first.score };
        let in_base: BTreeSet<&str> = base.iter().map(|h| h.path.as_str()).collect();
        let mut scores: BTreeMap<String, f64> = BTreeMap::new();
        let mut meta: BTreeMap<String, (Via, String, String)> = BTreeMap::new();
        for (rank, hit) in base.iter().enumerate() {
            scores.insert(hit.path.clone(), hit.score / top);
            meta.insert(
                hit.path.clone(),
                (Via::Bm25, String::new(), format!("rank {}", rank + 1)),
            );
        }
        for hit in &base {
            let seed_value = hit.score / top;
            for other in self.index.neighbours(&hit.path) {
                if !self.allowed(&other) || in_base.contains(other.as_str()) {
                    continue;
                }
                let gain = seed_value * self.config.link_weight * self.config.decay;
                *scores.entry(other.clone()).or_insert(0.0) += gain;
                meta.entry(other)
                    .or_insert((Via::Link, hit.path.clone(), "linked".to_string()));
            }
        }
        let mut ordered: Vec<(f64, String)> = scores
            .into_iter()
            .map(|(path, score)| (score, path))
            .collect();
        ordered.sort_by(|a, b| {
            round_to(b.0, 10)
                .total_cmp(&round_to(a.0, 10))
                .then_with(|| a.1.cmp(&b.1))
        });
        ordered
            .into_iter()
            .take(k)
            .map(|(score, path)| {
                let (via, seed, detail) =
                    meta.remove(&path)
                        .unwrap_or((Via::Link, String::new(), String::new()));
                RetrievalResult {
                    path,
                    score: round_to(score, 8),
                    via,
                    seed,
                    detail,
                }
            })
            .collect()
    }
}
