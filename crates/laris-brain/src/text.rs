//! The rule check on statements (ADR-024 sections 4 and 6.3): normalisation, numbers with units, negation, opposite
//! words and content words, all against closed lexicons. It is a filter, not a proof: it reads vocabulary, not
//! meaning, and its miss rate is measured on fixtures (`tests/gate.rs`) and stated.
//!
//! The write gate uses it to decide whether a quote supports a statement, whether two statements say the same thing and
//! whether they contradict each other; the answer check (T166) uses it to decide whether a sentence stays inside the
//! Claims it cites.

use std::collections::BTreeSet;
use std::sync::LazyLock;

use regex::Regex;

/// Words that turn a statement around.
pub const NEGATIONS: [&str; 12] = [
    "not", "no", "never", "cannot", "without", "neither", "nor", "none", "fails", "failed",
    "nothing", "nobody",
];

/// Opposite pairs; a statement with one word and a statement with the other disagree on that point.
pub const OPPOSITES: [(&str, &str); 14] = [
    ("increase", "decrease"),
    ("increases", "decreases"),
    ("increased", "decreased"),
    ("raises", "lowers"),
    ("raised", "lowered"),
    ("higher", "lower"),
    ("more", "fewer"),
    ("greater", "smaller"),
    ("above", "below"),
    ("before", "after"),
    ("safe", "unsafe"),
    ("effective", "ineffective"),
    ("true", "false"),
    ("present", "absent"),
];

/// Words that carry no subject; they are ignored when the content of two statements is compared.
pub const STOP_WORDS: [&str; 34] = [
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "of", "in", "on", "at", "to",
    "for", "by", "with", "and", "or", "it", "its", "this", "that", "these", "those", "as", "from",
    "has", "have", "had", "can", "may", "will", "than",
];

/// Quantifiers and hedges, matched against a closed lexicon (ADR-024 6.3).
pub const HEDGES: [&str; 14] = [
    "all",
    "every",
    "always",
    "most",
    "some",
    "many",
    "few",
    "often",
    "sometimes",
    "usually",
    "may",
    "might",
    "possibly",
    "probably",
];

static NUMBER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\d+(?:[.,]\d+)*").expect("static pattern"));

/// `text` with every run of whitespace folded to one space and the ends trimmed.
pub fn fold_whitespace(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Lower-cased words (runs of letters and digits).
pub fn words(text: &str) -> Vec<String> {
    laris_retrieval::tokens(text)
}

/// A number with the word that follows it, which is its unit when it is not a stop word.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Quantity {
    /// The digits, with a decimal comma read as a point and thousands separators removed.
    pub value: String,
    /// The word after the number, lower-cased; empty at the end of the text or before a stop word.
    pub unit: String,
}

fn normal_number(raw: &str) -> String {
    let mut text = raw.to_string();
    if text.matches(',').count() == 1 && text.rsplit(',').next().is_some_and(|t| t.len() != 3) {
        text = text.replace(',', ".");
    } else {
        text = text.replace(',', "");
    }
    if text.contains('.') {
        text = text.trim_end_matches('0').trim_end_matches('.').to_string();
    }
    text
}

/// What a statement says, in the parts the rule check compares.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Facts {
    /// The numbers with their units.
    pub quantities: BTreeSet<Quantity>,
    /// True when the number of negation words is odd.
    pub negated: bool,
    /// Content words: every word except stop words, negations, hedges and numbers.
    pub content: BTreeSet<String>,
    /// All words, including the ones above.
    pub all: BTreeSet<String>,
    /// The hedges and quantifiers used.
    pub hedges: BTreeSet<String>,
}

/// The facts of `text`.
pub fn facts(text: &str) -> Facts {
    let mut out = Facts::default();
    let lowered = text.to_lowercase();
    for m in NUMBER.find_iter(&lowered) {
        let after = lowered[m.end()..]
            .trim_start()
            .split(|c: char| !c.is_alphanumeric() && c != '%')
            .next()
            .unwrap_or("");
        let unit = if STOP_WORDS.contains(&after) || after.chars().all(|c| c.is_ascii_digit()) {
            ""
        } else {
            after
        };
        out.quantities.insert(Quantity {
            value: normal_number(m.as_str()),
            unit: unit.to_string(),
        });
    }
    let mut negations = 0;
    for word in words(text) {
        if NEGATIONS.contains(&word.as_str()) {
            negations += 1;
        }
        if word.ends_with("nt")
            && [
                "isn", "aren", "wasn", "weren", "doesn", "don", "didn", "won", "can", "couldn",
                "hasn", "haven",
            ]
            .iter()
            .any(|p| word.starts_with(p))
        {
            negations += 1; // isn't, doesn't, ...
        }
        if HEDGES.contains(&word.as_str()) {
            out.hedges.insert(word.clone());
        }
        let skip = STOP_WORDS.contains(&word.as_str())
            || NEGATIONS.contains(&word.as_str())
            || HEDGES.contains(&word.as_str())
            || word.chars().all(|c| c.is_ascii_digit())
            || word == "t";
        if !skip {
            out.content.insert(word.clone());
        }
        out.all.insert(word);
    }
    out.negated = negations % 2 == 1;
    out
}

/// The share of `a`'s content words that also occur among `b`'s content words (0 when `a` has none).
pub fn coverage(a: &Facts, b: &Facts) -> f64 {
    if a.content.is_empty() {
        return 0.0;
    }
    a.content.intersection(&b.content).count() as f64 / a.content.len() as f64
}

/// Jaccard similarity of the content words.
pub fn overlap(a: &Facts, b: &Facts) -> f64 {
    let union = a.content.union(&b.content).count();
    if union == 0 {
        return 0.0;
    }
    a.content.intersection(&b.content).count() as f64 / union as f64
}

/// True when one statement uses a word whose opposite the other uses.
pub fn opposite_words(a: &Facts, b: &Facts) -> bool {
    OPPOSITES.iter().any(|&(x, y)| {
        (a.all.contains(x) && b.all.contains(y)) || (a.all.contains(y) && b.all.contains(x))
    })
}

/// The support check's form of [`opposite_words`]: the statement uses a word whose opposite is in the quote while the
/// quote never uses the word itself. A quote that says both ("below 2000 ... above 3000") supports a statement that
/// says both; the contradiction search between two statements keeps [`opposite_words`].
pub fn opposite_to_quote(statement: &Facts, quote: &Facts) -> bool {
    OPPOSITES.iter().any(|&(x, y)| {
        (statement.all.contains(x) && quote.all.contains(y) && !quote.all.contains(x))
            || (statement.all.contains(y) && quote.all.contains(x) && !quote.all.contains(y))
    })
}

/// True when the quantities cannot all hold: a number of one statement is missing from the other, which names a
/// different number with the same unit that the first lacks (`120 patients` against `80 patients`).
pub fn quantities_clash(a: &Facts, b: &Facts) -> bool {
    a.quantities.difference(&b.quantities).any(|x| {
        b.quantities
            .difference(&a.quantities)
            .any(|y| x.unit == y.unit)
    })
}

/// Words that introduce an attribution and say nothing about the subject.
pub const ATTRIBUTION_WORDS: [&str; 8] = [
    "argues",
    "claims",
    "states",
    "holds",
    "suggests",
    "proposes",
    "believes",
    "maintains",
];

/// The facts of a position stated with its holder: the holder's words and the attribution verbs are not content.
pub fn attributed_facts(text: &str, holder: &str) -> Facts {
    let mut out = facts(text);
    let holder = words(holder);
    out.content
        .retain(|w| !holder.contains(w) && !ATTRIBUTION_WORDS.contains(&w.as_str()));
    out
}

/// Why a quote does not support a statement; `None` when it does. A statement is supported when every number in it is
/// in the quote, its polarity matches, no opposite word is introduced and `min_coverage` of its content words occur
/// in the quote.
pub fn unsupported(statement: &Facts, quote: &Facts, min_coverage: f64) -> Option<String> {
    if let Some(extra) = statement
        .quantities
        .iter()
        .find(|q| !quote.quantities.iter().any(|r| r.value == q.value))
    {
        return Some(format!("the number {} is not in the quote", extra.value));
    }
    if statement.negated != quote.negated {
        return Some("the statement and the quote differ in polarity".to_string());
    }
    if opposite_to_quote(statement, quote) {
        return Some("the statement uses the opposite of a word of the quote".to_string());
    }
    let share = coverage(statement, quote);
    if share < min_coverage {
        return Some(format!(
            "only {:.0} % of the content words of the statement are in the quote",
            share * 100.0
        ));
    }
    None
}

/// Two statements say the same thing: same numbers, same polarity, no opposites and `min_overlap` of content in common.
pub fn equivalent(a: &Facts, b: &Facts, min_overlap: f64) -> bool {
    a.quantities == b.quantities
        && a.negated == b.negated
        && !opposite_words(a, b)
        && overlap(a, b) >= min_overlap
}

/// Two statements on the same subject disagree: enough shared content, and they differ in polarity, use opposite words
/// or give clashing quantities.
pub fn contradicts(a: &Facts, b: &Facts, min_overlap: f64) -> bool {
    if overlap(a, b) < min_overlap {
        return false;
    }
    a.negated != b.negated || opposite_words(a, b) || quantities_clash(a, b)
}

/// Where `quote` occurs in `text`, as byte offsets: exact first, then with whitespace folded on both sides. The
/// first occurrence wins.
pub fn locate(text: &str, quote: &str) -> Option<(usize, usize)> {
    if quote.trim().is_empty() {
        return None;
    }
    if let Some(start) = text.find(quote) {
        return Some((start, start + quote.len()));
    }
    // folded search: map every folded byte back to an original offset
    let mut folded = String::new();
    let mut origin: Vec<usize> = Vec::new();
    let mut gap = false;
    for (at, c) in text.char_indices() {
        if c.is_whitespace() {
            gap = !folded.is_empty();
            continue;
        }
        if gap {
            folded.push(' ');
            origin.push(at);
            gap = false;
        }
        for _ in 0..c.len_utf8() {
            origin.push(at);
        }
        folded.push(c);
    }
    let wanted = fold_whitespace(quote);
    let start = folded.find(&wanted)?;
    let end = start + wanted.len();
    let last_char = folded[..end].chars().last()?;
    let first = origin[start];
    let last = origin[end - 1]
        + text[origin[end - 1]..]
            .chars()
            .next()
            .map_or(last_char.len_utf8(), char::len_utf8);
    Some((first, last))
}
