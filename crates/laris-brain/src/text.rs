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
    /// The content words of each clause, in order ([`CLAUSE_WORDS`] and `,` `;` `:` end a clause); clauses without
    /// content words are left out.
    pub clauses: Vec<BTreeSet<String>>,
    /// What the statement is about, when its form shows it ([`subject`]); `None` when it does not.
    pub subject: Option<BTreeSet<String>>,
    /// Each word of [`OPPOSITES`] used, with the content word after it ([`opposite_words`]).
    pub opposites: BTreeSet<(String, String)>,
}

/// Words that start a new clause: a statement that adds a clause the source does not hold is caught by the clause,
/// not by the whole statement's share of words.
pub const CLAUSE_WORDS: [&str; 10] = [
    "and",
    "but",
    "or",
    "while",
    "whereas",
    "which",
    "because",
    "so",
    "thus",
    "therefore",
];

/// Words that end the subject of a statement: copulas, auxiliaries, the verbs of definitions and of attribution. The
/// subject also ends at a number, a negation, a hedge and a word of [`OPPOSITES`].
pub const SUBJECT_ENDS: [&str; 34] = [
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "can",
    "could",
    "may",
    "might",
    "will",
    "would",
    "shall",
    "should",
    "must",
    "occurs",
    "occur",
    "describes",
    "describe",
    "means",
    "mean",
    "refers",
    "refer",
    "states",
    "state",
    "says",
    "holds",
];

/// Words that open a leading condition (`When r is positive, ...`); the condition is then the subject.
pub const CONDITION_WORDS: [&str; 5] = ["when", "if", "as", "once", "whenever"];

/// The longest subject, in words, that the form of a statement is trusted to show.
const SUBJECT_WORDS: usize = 12;

fn subject_word(raw: &str) -> String {
    raw.trim_matches(|c: char| !c.is_alphanumeric())
        .to_lowercase()
}

fn subject_set<'a>(raw: impl Iterator<Item = &'a str>) -> Option<BTreeSet<String>> {
    let out: BTreeSet<String> = raw
        .map(subject_word)
        .filter(|w| !w.is_empty() && !STOP_WORDS.contains(&w.as_str()))
        .collect();
    (!out.is_empty()).then_some(out)
}

/// What a statement is about: the words before its predicate, read from the form of the statement, in this order:
///
/// 1. a label: the words before the first `:` or ` | ` within the first 12 words (`term: text`, `name | formula`),
///    numbers included (`Type 1 error: ...`);
/// 2. a leading condition: from `when`, `if`, `as` ([`CONDITION_WORDS`]) to the first comma or `then`
///    (`When r is positive, ...`);
/// 3. the words before the first number (a table row, `name value unit`), `=`, or word of [`SUBJECT_ENDS`],
///    [`NEGATIONS`], [`HEDGES`] or [`OPPOSITES`].
///
/// Words are split at whitespace and lowered, so `step-up` and `step-down` stay different; stop words are dropped.
/// `None` when nothing ends it within 12 words or it would be empty: the statement's form then does not show its
/// subject, and the contradiction search compares the statements as before.
pub fn subject(text: &str) -> Option<BTreeSet<String>> {
    let tokens: Vec<&str> = text.split_whitespace().take(SUBJECT_WORDS + 1).collect();
    if let Some(at) = tokens
        .iter()
        .take(SUBJECT_WORDS)
        .position(|t| *t == "|" || t.ends_with(':'))
    {
        let mut label: Vec<&str> = tokens[..at].to_vec();
        if tokens[at] != "|" {
            label.push(tokens[at]);
        }
        return subject_set(label.into_iter());
    }
    let first = tokens.first().map(|t| subject_word(t)).unwrap_or_default();
    if CONDITION_WORDS.contains(&first.as_str()) {
        let mut condition = Vec::new();
        for t in tokens.iter().take(SUBJECT_WORDS).skip(1) {
            if subject_word(t) == "then" {
                return subject_set(condition.into_iter());
            }
            condition.push(*t);
            if t.ends_with(',') {
                return subject_set(condition.into_iter());
            }
        }
        return None;
    }
    let mut out = Vec::new();
    for raw in tokens.iter().take(SUBJECT_WORDS) {
        let word = subject_word(raw);
        let w = word.as_str();
        let number = raw
            .trim_start_matches(['-', '+', '\u{2212}', '(', '~'])
            .starts_with(|c: char| c.is_ascii_digit());
        if number
            || raw.starts_with('=')
            || SUBJECT_ENDS.contains(&w)
            || NEGATIONS.contains(&w)
            || HEDGES.contains(&w)
            || OPPOSITES.iter().any(|&(x, y)| w == x || w == y)
            || w.ends_with("n't")
            || w.ends_with("n\u{2019}t")
        {
            return subject_set(out.into_iter());
        }
        out.push(*raw);
    }
    None
}

/// True when both statements show their subject and the subjects differ: they speak of different things, so no
/// negation, opposite word or number can make them disagree.
pub fn different_subjects(a: &Facts, b: &Facts) -> bool {
    matches!((&a.subject, &b.subject), (Some(x), Some(y)) if x != y)
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
    out.clauses = clauses_of(text);
    out.subject = subject(text);
    out.opposites = directed(text);
    out
}

fn content_word(word: &str) -> bool {
    !(STOP_WORDS.contains(&word)
        || NEGATIONS.contains(&word)
        || HEDGES.contains(&word)
        || CLAUSE_WORDS.contains(&word)
        || word.chars().all(|c| c.is_ascii_digit())
        || word == "t")
}

fn clauses_of(text: &str) -> Vec<BTreeSet<String>> {
    let mut out = Vec::new();
    let mut current = BTreeSet::new();
    for piece in text.to_lowercase().split_inclusive([',', ';', ':']) {
        for word in words(piece) {
            if CLAUSE_WORDS.contains(&word.as_str()) {
                if !current.is_empty() {
                    out.push(std::mem::take(&mut current));
                }
            } else if content_word(&word) {
                current.insert(word);
            }
        }
        if piece.ends_with([',', ';', ':']) && !current.is_empty() {
            out.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        out.push(current);
    }
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

/// The opposite words of a statement with the content word that follows each (`increases voltage`), or an empty word
/// at the end of the statement.
fn directed(text: &str) -> BTreeSet<(String, String)> {
    let all = words(text);
    let mut out = BTreeSet::new();
    for (i, w) in all.iter().enumerate() {
        if OPPOSITES.iter().any(|&(x, y)| w == x || w == y) {
            let object = all[i + 1..]
                .iter()
                .find(|n| content_word(n))
                .cloned()
                .unwrap_or_default();
            out.insert((w.clone(), object));
        }
    }
    out
}

/// True when one statement says the opposite of the other about the same thing: it uses a word of [`OPPOSITES`]
/// before a content word (`decreases voltage`) where the other uses the word's opposite before the same content word
/// and never the word itself (`increases voltage`). A statement that holds both (`increases voltage and decreases
/// current`, `the increase, or decrease, of the size`) is not opposed by one that holds either; two identical
/// statements never are.
pub fn opposite_words(a: &Facts, b: &Facts) -> bool {
    let opposed = |x: &BTreeSet<(String, String)>, y: &BTreeSet<(String, String)>| {
        x.iter().any(|(w, object)| {
            OPPOSITES.iter().any(|&(p, q)| {
                let other = if w == p {
                    q
                } else if w == q {
                    p
                } else {
                    return false;
                };
                y.contains(&(other.to_string(), object.clone()))
                    && !y.contains(&(w.clone(), object.clone()))
                    && !x.contains(&(other.to_string(), object.clone()))
            })
        })
    };
    opposed(&a.opposites, &b.opposites) || opposed(&b.opposites, &a.opposites)
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
    let keep = |w: &String| !holder.contains(w) && !ATTRIBUTION_WORDS.contains(&w.as_str());
    out.content.retain(keep);
    for clause in &mut out.clauses {
        clause.retain(keep);
    }
    out.clauses.retain(|c| !c.is_empty());
    out
}

/// The quantifier or hedge rule of ADR-024 6.3, the same in the gate and the answer check: a statement may neither add
/// a quantifier or hedge its source does not use (`always`, `all`: a strengthened claim) nor drop one it uses (`may`,
/// `some`). The reason, or `None`.
pub fn hedge_change(statement: &Facts, source: &Facts) -> Option<String> {
    if let Some(h) = statement.hedges.difference(&source.hedges).next() {
        return Some(format!("the statement adds the quantifier or hedge `{h}`"));
    }
    if let Some(h) = source.hedges.difference(&statement.hedges).next() {
        return Some(format!("the statement drops the quantifier or hedge `{h}`"));
    }
    None
}

/// The appended-clause rule, the same in the gate and the answer check: every clause of the statement must have
/// `min_share` of its content words in the source, so a clause added to a supported statement (`... and prevents
/// heart attacks`) is caught even when the whole statement's share is high enough. Words for which `ignore` is true do
/// not count. The reason, or `None`.
pub fn uncovered_clause(
    statement: &Facts,
    source: &Facts,
    min_share: f64,
    ignore: &dyn Fn(&str) -> bool,
) -> Option<String> {
    for clause in &statement.clauses {
        let own: Vec<&String> = clause.iter().filter(|w| !ignore(w)).collect();
        if own.is_empty() {
            continue;
        }
        let held = own.iter().filter(|w| source.content.contains(**w)).count();
        let share = held as f64 / own.len() as f64;
        if share < min_share {
            let words: Vec<&str> = own.iter().map(|w| w.as_str()).collect();
            return Some(format!(
                "the clause `{}` has only {:.0} % of its content words in the source",
                words.join(" "),
                share * 100.0
            ));
        }
    }
    None
}

/// Why a quote does not support a statement; `None` when it does. A statement is supported when every number in it is
/// in the quote, its polarity matches, no opposite word is introduced and `min_coverage` of its content words occur
/// in the quote, it adds or drops no quantifier or hedge ([`hedge_change`]) and every clause reaches `min_coverage`
/// ([`uncovered_clause`]).
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
    if let Some(why) = hedge_change(statement, quote) {
        return Some(why);
    }
    let share = coverage(statement, quote);
    if share < min_coverage {
        return Some(format!(
            "only {:.0} % of the content words of the statement are in the quote",
            share * 100.0
        ));
    }
    uncovered_clause(statement, quote, min_coverage, &|_| false)
}

/// Two statements say the same thing: same numbers, same polarity, no opposites and `min_overlap` of content in common.
pub fn equivalent(a: &Facts, b: &Facts, min_overlap: f64) -> bool {
    a.quantities == b.quantities
        && a.negated == b.negated
        && !opposite_words(a, b)
        && overlap(a, b) >= min_overlap
}

/// Two statements on the same subject disagree: the subjects do not differ ([`different_subjects`]; the subject is
/// compared first), enough content is shared, and they differ in polarity, use opposite words or give clashing
/// quantities.
pub fn contradicts(a: &Facts, b: &Facts, min_overlap: f64) -> bool {
    if different_subjects(a, b) || overlap(a, b) < min_overlap {
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
