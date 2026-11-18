//! Text helpers: code masking, folding for comparison, sentence splitting.

use std::ops::Range;

/// `text` with code (fenced blocks and inline spans) blanked out, byte for byte, so offsets stay valid.
pub(crate) fn mask_code(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut fenced = false;
    for line in text.split_inclusive('\n') {
        let body = line.trim_end_matches(['\n', '\r']);
        let trimmed = body.trim_start();
        if trimmed.starts_with("```") || trimmed.starts_with("~~~") {
            fenced = !fenced;
            blank(&mut out, line);
            continue;
        }
        if fenced {
            blank(&mut out, line);
            continue;
        }
        let mut inline = false;
        for ch in line.chars() {
            if ch == '`' {
                inline = !inline;
                out.push(' ');
            } else if inline && ch != '\n' && ch != '\r' {
                push_blank(&mut out, ch);
            } else {
                out.push(ch);
            }
        }
        // An unclosed backtick is not code: put the line back.
        if inline {
            out.truncate(out.len() - line.len());
            out.push_str(line);
        }
    }
    out
}

fn blank(out: &mut String, line: &str) {
    for ch in line.chars() {
        if ch == '\n' || ch == '\r' {
            out.push(ch);
        } else {
            push_blank(out, ch);
        }
    }
}

fn push_blank(out: &mut String, ch: char) {
    for _ in 0..ch.len_utf8() {
        out.push(' ');
    }
}

/// Lower-cased, whitespace and typography folded, so a quote matches its source despite line breaks and curly marks.
pub(crate) fn fold(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut space = true;
    for ch in text.chars() {
        let ch = match ch {
            '\u{2018}' | '\u{2019}' => '\'',
            '\u{201C}' | '\u{201D}' => '"',
            '\u{2010}'..='\u{2015}' | '\u{2212}' => '-',
            c => c,
        };
        if ch.is_whitespace() {
            if !space {
                out.push(' ');
            }
            space = true;
        } else {
            for lower in ch.to_lowercase() {
                out.push(lower);
            }
            space = false;
        }
    }
    out.trim_end().to_string()
}

/// Whether every fragment of `quote` (split at an ellipsis) occurs in `source`, both folded.
pub(crate) fn quote_in(quote: &str, source: &str) -> bool {
    let source = fold(source);
    let quote = fold(quote).replace("[...]", "…").replace("...", "…");
    quote
        .split('…')
        .map(|part| part.trim().trim_matches(['.', ',', ';', ':', ' ']))
        .filter(|part| !part.is_empty())
        .all(|part| source.contains(part))
}

/// A sentence: its byte range in the text.
pub(crate) struct Sentence {
    pub range: Range<usize>,
}

const ABBREVIATIONS: &[&str] = &[
    "e.g", "i.e", "al", "fig", "figs", "eq", "eqs", "vs", "cf", "no", "dr", "approx", "ca", "sec",
    "ref",
];

/// Where the next sentence of `masked[from..to]` ends, as a byte offset, or `to`.
fn sentence_end(masked: &str, from: usize, to: usize, inside: &dyn Fn(usize) -> bool) -> usize {
    let slice = &masked[from..to];
    let mut chars = slice.char_indices().peekable();
    while let Some((i, ch)) = chars.next() {
        if !matches!(ch, '.' | '!' | '?') || inside(from + i) {
            continue;
        }
        let mut end = i + ch.len_utf8();
        // Closing marks that belong to the sentence.
        while let Some(&(j, c)) = chars.peek() {
            if matches!(
                c,
                '"' | '\u{201D}' | ')' | ']' | '*' | '\'' | '.' | '!' | '?'
            ) && !inside(from + j)
            {
                end = j + c.len_utf8();
                chars.next();
            } else {
                break;
            }
        }
        let next = slice[end..].chars().next();
        if next.is_some_and(|c| !c.is_whitespace()) {
            continue;
        }
        if ch == '.' && abbreviation(&slice[..i]) {
            continue;
        }
        return from + end;
    }
    to
}

fn abbreviation(before: &str) -> bool {
    let word: String = before
        .chars()
        .rev()
        .take_while(|c| c.is_alphabetic() || *c == '.')
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    let lower = word.to_lowercase();
    word.chars().count() == 1 || ABBREVIATIONS.contains(&lower.as_str())
}

/// Splits `masked[range]` into sentences. A citation that stands after the full stop belongs to the sentence before
/// it, and no stop inside a citation ends one (`inside` says whether an offset is within a citation, `cite_at` gives
/// the end of a citation that starts at an offset).
pub(crate) fn sentences(
    masked: &str,
    range: Range<usize>,
    inside: &dyn Fn(usize) -> bool,
    cite_at: &dyn Fn(usize) -> Option<usize>,
) -> Vec<Sentence> {
    let mut out = Vec::new();
    let mut start = range.start;
    let end = range.end;
    while start < end {
        let lead = masked[start..end].len() - masked[start..end].trim_start().len();
        start += lead;
        if start >= end {
            break;
        }
        let mut stop = sentence_end(masked, start, end, inside);
        // Citations after the stop, then their own full stop.
        loop {
            let gap = masked[stop..end].len() - masked[stop..end].trim_start().len();
            match cite_at(stop + gap) {
                Some(cite_end) => stop = cite_end,
                None => break,
            }
            if masked[stop..end].starts_with(['.', '!', '?']) {
                stop += 1;
            }
        }
        let text = &masked[start..stop];
        let trimmed = text.trim_end();
        if !trimmed.is_empty() {
            out.push(Sentence {
                range: start..start + trimmed.len(),
            });
        }
        start = stop;
    }
    out
}
