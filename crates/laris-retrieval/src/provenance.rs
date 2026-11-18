//! Span provenance: where in the note a result was found, checkable against the note itself.
//!
//! A span is a byte range of the note body, cut at paragraph boundaries, with the verbatim text and the SHA-256 of
//! the whole note. [`verify_span`] fails closed: a missing note, a changed note or a range that does not hold the
//! text is an error, and an answer must not cite it.

use laris_vault::VaultIndex;

use crate::graph::RetrievalResult;
use crate::text::tokens;

/// Longest snippet kept, in characters. A longer paragraph is cut at a character boundary.
pub const MAX_SNIPPET_CHARS: usize = 400;

/// A byte range of a note's body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Span {
    /// Vault-relative path.
    pub path: String,
    /// SHA-256 of the note text when the span was taken.
    pub note_sha256: String,
    /// Byte offset of the first byte, in the body.
    pub start: usize,
    /// Byte offset after the last byte, in the body.
    pub end: usize,
    /// The text of `body[start..end]`.
    pub snippet: String,
}

/// A result with the span that supports it. `span` is `None` for a note whose body holds none of the query words
/// (a link result, a corpus result); the result is then usable for navigation, not as a quotation.
#[derive(Debug, Clone, PartialEq)]
pub struct Cited {
    /// The result.
    pub result: RetrievalResult,
    /// The best paragraph for the query, when there is one.
    pub span: Option<Span>,
}

/// Attaches to each result the paragraph of its note that holds the most distinct query words (earliest on a tie).
pub fn cite(results: &[RetrievalResult], index: &VaultIndex, query: &str) -> Vec<Cited> {
    let terms: std::collections::BTreeSet<String> = tokens(query).into_iter().collect();
    results
        .iter()
        .map(|result| Cited {
            result: result.clone(),
            span: index
                .notes
                .get(&result.path)
                .and_then(|note| best_span(&note.path, &note.sha256, &note.body, &terms)),
        })
        .collect()
}

fn best_span(
    path: &str,
    sha: &str,
    body: &str,
    terms: &std::collections::BTreeSet<String>,
) -> Option<Span> {
    let mut best: Option<(usize, usize, usize)> = None; // (matches, start, end)
    for (start, end) in paragraphs(body) {
        let words: std::collections::BTreeSet<String> =
            tokens(&body[start..end]).into_iter().collect();
        let matches = terms.iter().filter(|t| words.contains(*t)).count();
        if matches > 0 && best.is_none_or(|(m, _, _)| matches > m) {
            best = Some((matches, start, end));
        }
    }
    best.map(|(_, start, end)| {
        let cut = body[start..end]
            .char_indices()
            .nth(MAX_SNIPPET_CHARS)
            .map_or(end, |(i, _)| start + i);
        Span {
            path: path.to_string(),
            note_sha256: sha.to_string(),
            start,
            end: cut,
            snippet: body[start..cut].to_string(),
        }
    })
}

/// Byte ranges of the non-blank paragraphs of `body`, trimmed, split at blank lines.
fn paragraphs(body: &str) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start: Option<usize> = None;
    let mut end = 0;
    let mut offset = 0;
    for line in body.split_inclusive('\n') {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            if let Some(s) = start.take() {
                out.push((s, end));
            }
        } else {
            let lead = line.len() - line.trim_start().len();
            if start.is_none() {
                start = Some(offset + lead);
            }
            end = offset + line.trim_end().len();
        }
        offset += line.len();
    }
    if let Some(s) = start {
        out.push((s, end));
    }
    out
}

/// Why a span cannot be cited.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SpanError {
    /// The note is not in the index.
    MissingNote,
    /// The note changed since the span was taken.
    ChangedNote,
    /// The range is outside the body or not on character boundaries.
    BadRange,
    /// The range does not hold the snippet.
    SnippetMismatch,
}

impl std::fmt::Display for SpanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            SpanError::MissingNote => "the note is not in the index",
            SpanError::ChangedNote => "the note changed since the span was taken",
            SpanError::BadRange => "the range is outside the note body",
            SpanError::SnippetMismatch => "the range does not hold the snippet",
        })
    }
}

impl std::error::Error for SpanError {}

/// Checks a span against the index; the only way to a citation.
pub fn verify_span(index: &VaultIndex, span: &Span) -> Result<(), SpanError> {
    let note = index.notes.get(&span.path).ok_or(SpanError::MissingNote)?;
    if note.sha256 != span.note_sha256 {
        return Err(SpanError::ChangedNote);
    }
    let text = note
        .body
        .get(span.start..span.end)
        .ok_or(SpanError::BadRange)?;
    if text != span.snippet {
        return Err(SpanError::SnippetMismatch);
    }
    Ok(())
}
