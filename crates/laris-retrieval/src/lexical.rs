//! Lexical passage retrieval over a vault: TF-IDF and BM25, with the note path and the character span of every hit
//! (SR-M11, T230). No embedding model is involved; the ranking is a pure function of the notes and the query.
//!
//! # Passages
//!
//! A note body is cut into passages at blank lines (the paragraphs of [`crate::cite`]). A paragraph longer than
//! [`MAX_PASSAGE_CHARS`] is cut again at the last whitespace before that limit, so no word is split. Notes in
//! `_inbox/` are never indexed. A passage knows its note path, its span in **characters** of the note body
//! (`start..end`, `end` exclusive) and the SHA-256 of the note, so [`verify_passage`] can check a quotation.
//!
//! # Tokenisation
//!
//! [`crate::tokens`]: the text is split at every character that is not a letter or a digit, and each run is
//! lower-cased. There is no stemming and no stop-word list; both change scores in ways that are hard to audit, and a
//! stop word costs little because its idf is near zero. A query term counts once however often it is repeated.
//!
//! # Scorers
//!
//! With `N` passages, `df(t)` the number of passages that hold the term `t`, `tf(t, d)` its count in passage `d` and
//! `|d|` the passage length in tokens:
//!
//! * **BM25** (Okapi): `Σ_t idf(t) · tf · (k1 + 1) / (tf + k1 · (1 − b + b · |d| / avg|d|))` with
//!   `idf(t) = ln(1 + (N − df + 0.5) / (df + 0.5))`, `k1 = 1.5`, `b = 0.75`. Same constants as the note and passage
//!   indexes of this crate.
//! * **TF-IDF** (cosine): the passage vector has the weight `(1 + ln tf) · idf(t)` per term and the query vector has
//!   `idf(t)` per distinct term, with `idf(t) = 1 + ln(N / df)`; the score is their cosine. Terms of the query that
//!   no passage holds do not enter the query norm (they carry no information in this corpus).
//! * **Fused**: reciprocal-rank fusion of the two rankings, `Σ 1 / (60 + rank)` with rank from 1, as
//!   [`crate::fuse_ranked`]. The fused score depends on ranks only, so the two incomparable scales need no
//!   normalisation.
//!
//! Scores are rounded to eight places (ten for the fused score). Ties are broken by path, then by start, ascending.
//! A passage with no query term is never returned.

use std::collections::{BTreeSet, HashMap};

use laris_vault::VaultIndex;

use crate::fusion::{Channel, fuse_ranked};
use crate::provenance::paragraphs;
use crate::search::in_inbox;
use crate::text::{round_to, tokens};

/// Longest passage in characters; a longer paragraph is cut at whitespace.
pub const MAX_PASSAGE_CHARS: usize = 800;
/// How many passages of each ranking enter the fusion (or `limit` when that is larger): a passage outside both top
/// lists adds at most `1 / 160` and cannot change the head of the fused list.
pub const FUSION_DEPTH: usize = 100;
const K1: f64 = 1.5;
const B: f64 = 0.75;

/// How passages are ranked.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scorer {
    /// Cosine of tf-idf vectors.
    TfIdf,
    /// Okapi BM25.
    Bm25,
    /// Reciprocal-rank fusion of both.
    Fused,
}

impl Scorer {
    /// The label used in evidence: `tfidf`, `bm25`, `fused`.
    pub fn as_str(self) -> &'static str {
        match self {
            Scorer::TfIdf => "tfidf",
            Scorer::Bm25 => "bm25",
            Scorer::Fused => "fused",
        }
    }
}

/// A passage of a note with its span.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VaultPassage {
    /// Vault-relative path of the note.
    pub path: String,
    /// SHA-256 of the note text when the passage was taken.
    pub note_sha256: String,
    /// Character offset of the first character in the note body.
    pub start: usize,
    /// Character offset after the last character.
    pub end: usize,
    /// The text, equal to the characters `start..end` of the body.
    pub text: String,
}

/// A ranked passage.
#[derive(Debug, Clone, PartialEq)]
pub struct VaultPassageHit {
    /// The passage.
    pub passage: VaultPassage,
    /// Score of the scorer that ranked it.
    pub score: f64,
    /// 1-based rank.
    pub rank: usize,
}

/// Why a passage cannot be cited.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PassageError {
    /// The note is not in the index.
    MissingNote,
    /// The note changed since the passage was taken.
    ChangedNote,
    /// The span does not hold the text.
    Mismatch,
}

impl std::fmt::Display for PassageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            PassageError::MissingNote => "the note is not in the index",
            PassageError::ChangedNote => "the note changed since the passage was taken",
            PassageError::Mismatch => "the span does not hold the passage text",
        })
    }
}

impl std::error::Error for PassageError {}

/// Checks a passage against the index; fails closed.
pub fn verify_passage(index: &VaultIndex, passage: &VaultPassage) -> Result<(), PassageError> {
    let note = index
        .notes
        .get(&passage.path)
        .ok_or(PassageError::MissingNote)?;
    if note.sha256 != passage.note_sha256 {
        return Err(PassageError::ChangedNote);
    }
    let len = passage.end.saturating_sub(passage.start);
    let text: String = note.body.chars().skip(passage.start).take(len).collect();
    if text == passage.text && text.chars().count() == len {
        Ok(())
    } else {
        Err(PassageError::Mismatch)
    }
}

/// Splits one note body into passages: `(char_start, char_end, text)`.
pub fn split_body(body: &str, max_chars: usize) -> Vec<(usize, usize, String)> {
    let char_at: HashMap<usize, usize> = body
        .char_indices()
        .enumerate()
        .map(|(c, (b, _))| (b, c))
        .chain(std::iter::once((body.len(), body.chars().count())))
        .collect();
    let mut out = Vec::new();
    for (start, end) in paragraphs(body) {
        let mut from = start;
        while from < end {
            let mut to = end;
            if body[from..end].chars().count() > max_chars {
                let limit = body[from..end]
                    .char_indices()
                    .nth(max_chars)
                    .map_or(end, |(i, _)| from + i);
                // the window ends on a word boundary when the next character is whitespace
                to = if body[limit..end].starts_with(char::is_whitespace) {
                    limit
                } else {
                    match body[from..limit].rfind(char::is_whitespace) {
                        Some(i) if i > 0 => from + i,
                        _ => limit,
                    }
                };
            }
            out.push((char_at[&from], char_at[&to], body[from..to].to_owned()));
            from = to;
            while let Some(c) = body[from..end].chars().next().filter(|c| c.is_whitespace()) {
                from += c.len_utf8();
            }
        }
    }
    out
}

/// An inverted index over the passages of a vault.
pub struct VaultPassages {
    passages: Vec<VaultPassage>,
    lengths: Vec<usize>,
    avg: f64,
    /// term -> (passage, term frequency), passages ascending.
    postings: HashMap<String, Vec<(u32, u32)>>,
    /// Euclidean norm of each passage's tf-idf vector.
    norms: Vec<f64>,
}

fn tfidf_idf(n: f64, df: f64) -> f64 {
    1.0 + (n / df).ln()
}

impl VaultPassages {
    /// Indexes the passages of every note outside `_inbox/`.
    pub fn new(index: &VaultIndex) -> VaultPassages {
        VaultPassages::with_max_chars(index, MAX_PASSAGE_CHARS)
    }

    /// As [`VaultPassages::new`] with a chosen passage length limit.
    pub fn with_max_chars(index: &VaultIndex, max_chars: usize) -> VaultPassages {
        let mut passages = Vec::new();
        let mut lengths = Vec::new();
        let mut postings: HashMap<String, Vec<(u32, u32)>> = HashMap::new();
        let mut rows: Vec<Vec<(String, u32)>> = Vec::new();
        for (path, note) in &index.notes {
            if in_inbox(path) {
                continue;
            }
            for (start, end, text) in split_body(&note.body, max_chars) {
                let words = tokens(&text);
                let doc = passages.len() as u32;
                let mut counts: HashMap<&str, u32> = HashMap::new();
                for word in &words {
                    *counts.entry(word.as_str()).or_insert(0) += 1;
                }
                let mut row: Vec<(String, u32)> =
                    counts.into_iter().map(|(w, c)| (w.to_owned(), c)).collect();
                row.sort();
                for (word, tf) in &row {
                    postings.entry(word.clone()).or_default().push((doc, *tf));
                }
                rows.push(row);
                lengths.push(words.len());
                passages.push(VaultPassage {
                    path: path.clone(),
                    note_sha256: note.sha256.clone(),
                    start,
                    end,
                    text,
                });
            }
        }
        let n = passages.len() as f64;
        let norms = rows
            .iter()
            .map(|row| {
                row.iter()
                    .map(|(word, tf)| {
                        let w =
                            (1.0 + f64::from(*tf).ln()) * tfidf_idf(n, postings[word].len() as f64);
                        w * w
                    })
                    .sum::<f64>()
                    .sqrt()
            })
            .collect();
        let total: usize = lengths.iter().sum();
        let avg = if lengths.is_empty() {
            0.0
        } else {
            total as f64 / lengths.len() as f64
        };
        VaultPassages {
            passages,
            lengths,
            avg,
            postings,
            norms,
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

    /// Every passage, in path then start order.
    pub fn passages(&self) -> &[VaultPassage] {
        &self.passages
    }

    fn bm25(&self, terms: &BTreeSet<String>) -> Vec<f64> {
        let n = self.passages.len() as f64;
        let avg = if self.avg == 0.0 { 1.0 } else { self.avg };
        let mut scores = vec![0.0_f64; self.passages.len()];
        for term in terms {
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
        scores
    }

    fn tfidf(&self, terms: &BTreeSet<String>) -> Vec<f64> {
        let n = self.passages.len() as f64;
        let mut dots = vec![0.0_f64; self.passages.len()];
        let mut query_norm = 0.0_f64;
        for term in terms {
            let Some(posting) = self.postings.get(term) else {
                continue;
            };
            let idf = tfidf_idf(n, posting.len() as f64);
            query_norm += idf * idf;
            for &(doc, tf) in posting {
                dots[doc as usize] += idf * (1.0 + f64::from(tf).ln()) * idf;
            }
        }
        let query_norm = query_norm.sqrt();
        dots.iter()
            .zip(&self.norms)
            .map(|(dot, norm)| {
                if *dot > 0.0 && *norm > 0.0 && query_norm > 0.0 {
                    dot / (norm * query_norm)
                } else {
                    0.0
                }
            })
            .collect()
    }

    /// Passage indexes with a positive score, best first, with the rounded score.
    fn ranked(&self, scores: &[f64]) -> Vec<(usize, f64)> {
        let mut v: Vec<(usize, f64)> = scores
            .iter()
            .enumerate()
            .filter(|(_, s)| **s > 0.0)
            .map(|(d, s)| (d, round_to(*s, 8)))
            .collect();
        v.sort_by(|a, b| {
            b.1.total_cmp(&a.1).then_with(|| {
                let (x, y) = (&self.passages[a.0], &self.passages[b.0]);
                x.path.cmp(&y.path).then(x.start.cmp(&y.start))
            })
        });
        v
    }

    fn id(&self, d: usize) -> String {
        format!(
            "{}\u{0}{:012}",
            self.passages[d].path, self.passages[d].start
        )
    }

    /// The best `limit` passages for `query` under `scorer`.
    pub fn search(&self, query: &str, scorer: Scorer, limit: usize) -> Vec<VaultPassageHit> {
        let terms: BTreeSet<String> = tokens(query).into_iter().collect();
        let hit = |rank: usize, d: usize, score: f64| VaultPassageHit {
            passage: self.passages[d].clone(),
            score,
            rank: rank + 1,
        };
        let single = |scores: Vec<f64>| -> Vec<VaultPassageHit> {
            self.ranked(&scores)
                .into_iter()
                .take(limit)
                .enumerate()
                .map(|(r, (d, s))| hit(r, d, s))
                .collect()
        };
        match scorer {
            Scorer::Bm25 => single(self.bm25(&terms)),
            Scorer::TfIdf => single(self.tfidf(&terms)),
            Scorer::Fused => {
                let depth = FUSION_DEPTH.max(limit);
                let mut by_id: HashMap<String, usize> = HashMap::new();
                let mut channel = |name: &str, scores: Vec<f64>| Channel {
                    name: name.to_owned(),
                    weight: 1.0,
                    qualified: true,
                    items: self
                        .ranked(&scores)
                        .into_iter()
                        .take(depth)
                        .map(|(d, _)| {
                            let id = self.id(d);
                            by_id.insert(id.clone(), d);
                            id
                        })
                        .collect(),
                };
                let channels = [
                    channel("bm25", self.bm25(&terms)),
                    channel("tfidf", self.tfidf(&terms)),
                ];
                fuse_ranked(&channels, limit)
                    .into_iter()
                    .enumerate()
                    .map(|(r, f)| hit(r, by_id[&f.id], f.score))
                    .collect()
            }
        }
    }
}
