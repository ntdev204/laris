//! The text rules of the STEM profile, each the counterpart of a function of the Python reference (T278) named in its
//! comment: answer extraction (`answers.extract_choice`, `answers.extract_math_answer`), the reasoning split
//! (`open_llm.split_reasoning`), the router (`router.route`), content words and the first JSON object of a reply
//! (`harness.content_words`, `harness.first_json_object`). None reads a gold answer.

use regex::Regex;
use serde::Serialize;
use serde_json::{Map, Value};
use std::sync::LazyLock;

/// Option letters, in order (`data.LETTERS`).
pub const LETTERS: &str = "ABCDEFGHIJ";

/// The class a question is routed to.
pub const COMPUTABLE: &str = "computable";
/// A short question with word options.
pub const KNOWLEDGE: &str = "knowledge";
/// A long question with word options.
pub const REASONING: &str = "reasoning";

/// The first `n` option letters.
pub fn letters(n: usize) -> &'static str {
    &LETTERS[..n.min(LETTERS.len())]
}

/// `(reasoning, answer)`: the `<think>` section of a reply and what follows it (`split_reasoning`).
pub fn split_reasoning<'a>(text: &'a str, open: &str, close: &str) -> (String, String) {
    let start = text.find(open);
    let end = text.find(close);
    match (start, end) {
        (s, Some(e)) => {
            // the opening tag may sit in the prompt (the template adds it)
            let opened = s.filter(|&s| s < e);
            let begin = opened.map_or(0, |s| s + open.len());
            let before: &'a str = opened.map_or("", |s| &text[..s]);
            (
                text[begin..e].trim().to_owned(),
                format!("{before}{}", &text[e + close.len()..]),
            )
        }
        (Some(s), None) => (
            text[s + open.len()..].trim().to_owned(),
            text[..s].to_owned(),
        ),
        (None, None) => (String::new(), text.to_owned()),
    }
}

/// `(content, end)` of the brace group opening at byte `start` (`answers._braced`).
fn braced(text: &str, start: usize) -> Option<(&str, usize)> {
    let bytes = text.as_bytes();
    if bytes.get(start) != Some(&b'{') {
        return None;
    }
    let mut depth = 0i64;
    for (i, &b) in bytes.iter().enumerate().skip(start) {
        if b == b'{' {
            depth += 1;
        } else if b == b'}' {
            depth -= 1;
            if depth == 0 {
                return Some((&text[start + 1..i], i + 1));
            }
        }
    }
    None
}

static BOXED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\\(?:boxed|fbox)\s*").expect("regex"));
static BARE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^([^\s$]+)").expect("regex"));
static FINAL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)final answer\s*(?:is|:)\s*:?\s*(.+)").expect("regex"));
static TRAILING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[.\s]+$").expect("regex"));
static CHOICE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)answer\s*(?:is|:)?\s*[:\-]?\s*(?:\*\*)?\s*[\(\[]?\s*(?:\\boxed\{|\\text\{|\\textbf\{|\\mathrm\{|\$)*\s*([A-Z])\b",
    )
    .expect("regex")
});
static BOXED_LETTER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\\text\{|\\textbf\{|\\mathrm\{|[{}()\s.$]").expect("regex"));
static LAST_LINE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[*()\[\].:\s$]").expect("regex"));
static WORD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[a-z][a-z-]{2,}").expect("regex"));
static DIGIT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d").expect("regex"));

/// The content of the last `\boxed{...}` / `\fbox{...}` (or `\boxed 5`), trimmed (`answers.last_boxed`).
pub fn last_boxed(text: &str) -> Option<String> {
    let mut best: Option<&str> = None;
    for m in BOXED.find_iter(text) {
        let end = m.end();
        if let Some((group, _)) = braced(text, end) {
            best = Some(group);
        } else if end < text.len()
            && !text[end..].starts_with('{')
            && let Some(bare) = BARE.captures(&text[end..])
        {
            best = bare.get(1).map(|g| g.as_str());
        }
    }
    best.map(|b| py_strip(b).to_owned())
}

/// Python's `str.strip()`: Unicode white space and the separators Python also counts (`\x1c` to `\x1f`).
pub fn py_strip(text: &str) -> &str {
    text.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// Python's `str.splitlines()` (without the line ends).
fn py_lines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        let end = match c {
            '\r' => {
                if let Some(&(_, '\n')) = chars.peek() {
                    chars.next();
                    Some(i + 2)
                } else {
                    Some(i + 1)
                }
            }
            '\n' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}'
            | '\u{2029}' => Some(i + c.len_utf8()),
            _ => None,
        };
        if let Some(next) = end {
            out.push(&text[start..i]);
            start = next;
        }
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

/// The answer of an open (MATH) reply: the last box, else the text after the last "final answer is"
/// (`answers.extract_math_answer`).
pub fn extract_math_answer(text: &str) -> Option<String> {
    if let Some(boxed) = last_boxed(text) {
        return Some(boxed);
    }
    let last = FINAL.captures_iter(text).last()?;
    let answer = last.get(1).map_or("", |g| g.as_str()).replace('$', "");
    let answer = TRAILING.replace(py_strip(&answer), "").into_owned();
    (!answer.is_empty()).then_some(answer)
}

/// The chosen option letter among `letters`, or `None` when the text states none (`answers.extract_choice`).
pub fn extract_choice(text: &str, letters: &str) -> Option<String> {
    let allowed = |s: &str| s.chars().count() == 1 && letters.contains(s);
    let found: Vec<&str> = CHOICE
        .captures_iter(text)
        .filter_map(|c| c.get(1).map(|g| g.as_str()))
        .filter(|s| allowed(s))
        .collect();
    if let Some(last) = found.last() {
        return Some((*last).to_owned());
    }
    if let Some(boxed) = last_boxed(text) {
        let letter = BOXED_LETTER.replace_all(&boxed, "").into_owned();
        if allowed(&letter) {
            return Some(letter);
        }
    }
    let lines: Vec<&str> = py_lines(py_strip(text))
        .into_iter()
        .map(py_strip)
        .filter(|l| !l.is_empty())
        .collect();
    if let Some(line) = lines.last() {
        let last = LAST_LINE.replace_all(line, "").into_owned();
        if allowed(&last) {
            return Some(last);
        }
    }
    None
}

/// The answer of a reply to an item with `options` options (none: an open question).
pub fn extract(text: &str, options: usize) -> Option<String> {
    if options > 0 {
        extract_choice(text, letters(options))
    } else {
        extract_math_answer(text)
    }
}

/// Lowercase words of three letters or more, without the configured function words (`harness.content_words`).
pub fn content_words(text: &str, stop: &[String]) -> Vec<String> {
    let lowered = text.to_lowercase();
    WORD.find_iter(&lowered)
        .map(|m| m.as_str().to_owned())
        .filter(|w| !stop.iter().any(|s| s == w))
        .collect()
}

/// The first balanced `{...}` of `text` that parses as a JSON object (`harness.first_json_object`).
pub fn first_json_object(text: &str) -> Option<Map<String, Value>> {
    let bytes = text.as_bytes();
    let mut start = text.find('{');
    while let Some(s) = start {
        let (mut depth, mut quoted, mut escaped) = (0i64, false, false);
        for (end, &b) in bytes.iter().enumerate().skip(s) {
            if quoted {
                if escaped {
                    escaped = false;
                } else if b == b'\\' {
                    escaped = true;
                } else if b == b'"' {
                    quoted = false;
                }
            } else if b == b'"' {
                quoted = true;
            } else if b == b'{' {
                depth += 1;
            } else if b == b'}' {
                depth -= 1;
                if depth == 0 {
                    return match serde_json::from_str::<Value>(&text[s..=end]) {
                        Ok(Value::Object(map)) => Some(map),
                        Ok(_) => None,
                        Err(_) => break,
                    };
                }
            }
        }
        start = text[s + 1..].find('{').map(|i| s + 1 + i);
    }
    None
}

/// What the router read, recorded with every decision (no text).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Features {
    /// Number of options.
    pub options: usize,
    /// Share of options holding a digit, rounded to four places.
    pub numeric_option_share: f64,
    /// Words of the question.
    pub question_words: usize,
}

/// A route decision: class, the rule that decided and what it read (`router.Route`).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Route {
    /// `computable`, `knowledge` or `reasoning`.
    pub cls: &'static str,
    /// The rule that decided.
    pub rule: &'static str,
    /// What the rules read.
    pub features: Features,
}

/// The share of options that hold a digit (`router.numeric_share`).
pub fn numeric_share(options: &[String]) -> f64 {
    if options.is_empty() {
        return 0.0;
    }
    options.iter().filter(|o| DIGIT.is_match(o)).count() as f64 / options.len() as f64
}

/// The class of an item under the router thresholds (`router.route`).
pub fn route(
    question: &str,
    options: &[String],
    numeric_option_share: f64,
    knowledge_max_question_words: usize,
) -> Route {
    let share = numeric_share(options);
    let features = Features {
        options: options.len(),
        numeric_option_share: (share * 10_000.0).round() / 10_000.0,
        question_words: question.split_whitespace().count(),
    };
    let (cls, rule) = if options.is_empty() {
        (COMPUTABLE, "open_answer")
    } else if share >= numeric_option_share {
        (COMPUTABLE, "numeric_options")
    } else if features.question_words <= knowledge_max_question_words {
        (KNOWLEDGE, "word_options_short_question")
    } else {
        (REASONING, "word_options_long_question")
    };
    Route {
        cls,
        rule,
        features,
    }
}

/// The option lines of an item (`harness.options_block`): `A. text`, one per line.
pub fn options_block(options: &[String]) -> String {
    options
        .iter()
        .zip(LETTERS.chars())
        .map(|(o, l)| format!("{l}. {o}"))
        .collect::<Vec<_>>()
        .join("\n")
}

/// `template` with each `{name}` replaced by its value; no other brace is touched (`harness.fill`).
pub fn fill(template: &str, values: &[(&str, &str)]) -> String {
    let mut out = template.to_owned();
    for (name, value) in values {
        out = out.replace(&format!("{{{name}}}"), value);
    }
    out
}

/// A chat message read as an item: trailing lines that the configured pattern reads as options in letter order
/// (`A`, `B`, ...; at least `min_options`) become the options, the rest is the question.
pub fn chat_item(message: &str, option_line: &Regex, min_options: usize) -> (String, Vec<String>) {
    let lines: Vec<&str> = message.lines().collect();
    let mut options: Vec<String> = Vec::new();
    let mut first = lines.len();
    for (i, line) in lines.iter().enumerate().rev() {
        if line.trim().is_empty() && options.is_empty() {
            first = i;
            continue;
        }
        match option_line.captures(line) {
            Some(c) => {
                let (Some(letter), Some(text)) = (c.get(1), c.get(2)) else {
                    break;
                };
                options.insert(0, text.as_str().trim().to_owned());
                let _ = letter;
                first = i;
            }
            None => break,
        }
    }
    // the letters must run A, B, C... from the first option line
    let in_order = lines[first..]
        .iter()
        .filter_map(|l| option_line.captures(l))
        .zip(LETTERS.chars())
        .all(|(c, l)| {
            c.get(1)
                .is_some_and(|g| g.as_str().eq_ignore_ascii_case(&l.to_string()))
        });
    if options.len() < min_options || options.len() > LETTERS.len() || !in_order {
        return (message.trim().to_owned(), Vec::new());
    }
    (lines[..first].join("\n").trim().to_owned(), options)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boxed_answers_are_read_like_the_reference() {
        assert_eq!(
            last_boxed(r"so \boxed{\frac{1}{2}} and \boxed{3}"),
            Some("3".into())
        );
        assert_eq!(last_boxed(r"\boxed{x^{2}+1}"), Some("x^{2}+1".into()));
        assert_eq!(last_boxed(r"\boxed 5 done"), Some("5".into()));
        assert_eq!(last_boxed(r"\boxed{open"), None);
        assert_eq!(
            extract_math_answer("The final answer is: $42$."),
            Some("42".into())
        );
        assert_eq!(extract_math_answer("nothing here"), None);
    }

    #[test]
    fn choices_are_read_like_the_reference() {
        assert_eq!(extract_choice("Answer: C", "ABCD"), Some("C".into()));
        assert_eq!(
            extract_choice("the answer is (B)\nAnswer: **D**", "ABCD"),
            Some("D".into())
        );
        assert_eq!(
            extract_choice(r"\boxed{\text{B}}", "ABCD"),
            Some("B".into())
        );
        assert_eq!(extract_choice("so it is\n(A).", "ABCD"), Some("A".into()));
        assert_eq!(extract_choice("Answer: E", "ABCD"), None);
        // a lowercase letter is matched case-blind but is not an allowed letter
        assert_eq!(extract_choice("answer: b", "ABCD"), None);
    }

    #[test]
    fn reasoning_is_split_like_the_reference() {
        let (r, a) = split_reasoning("<think>\nx\n</think>\n\nAnswer: A", "<think>", "</think>");
        assert_eq!((r.as_str(), a.as_str()), ("x", "\n\nAnswer: A"));
        let (r, a) = split_reasoning("x</think>A", "<think>", "</think>");
        assert_eq!((r.as_str(), a.as_str()), ("x", "A"));
        let (r, a) = split_reasoning("pre<think>cut", "<think>", "</think>");
        assert_eq!((r.as_str(), a.as_str()), ("cut", "pre"));
        let (r, a) = split_reasoning("plain", "<think>", "</think>");
        assert_eq!((r.as_str(), a.as_str()), ("", "plain"));
    }

    #[test]
    fn the_router_reads_item_shape_only() {
        let opts = |v: &[&str]| v.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>();
        assert_eq!(route("Solve x", &[], 0.5, 40).rule, "open_answer");
        assert_eq!(
            route("q", &opts(&["1 m", "2 m", "red", "blue"]), 0.5, 40).rule,
            "numeric_options"
        );
        let r = route("short one", &opts(&["red", "blue", "green"]), 0.5, 40);
        assert_eq!((r.cls, r.features.numeric_option_share), (KNOWLEDGE, 0.0));
        let long = "w ".repeat(41);
        assert_eq!(
            route(&long, &opts(&["red", "blue"]), 0.5, 40).cls,
            REASONING
        );
        assert_eq!(numeric_share(&opts(&["1", "a", "b"])), 1.0 / 3.0);
    }

    #[test]
    fn the_first_json_object_is_found() {
        let m = first_json_object(r#"Call: {"operation": "evaluate", "expression": "{x}"} done"#)
            .expect("object");
        assert_eq!(m["expression"], "{x}");
        // a group that does not parse is passed over, as in the reference
        let next = first_json_object("{not json} {\"a\": 1}").expect("the next object");
        assert_eq!(next["a"], 1);
        assert!(first_json_object("none").is_none());
    }

    #[test]
    fn content_words_drop_short_and_stop_words() {
        let stop = vec!["the".to_owned(), "and".to_owned()];
        assert_eq!(
            content_words("The Krebs-cycle and ATP of it", &stop),
            vec!["krebs-cycle", "atp"]
        );
    }

    #[test]
    fn a_chat_message_with_lettered_lines_becomes_an_item() {
        let re = Regex::new(r"^\s*\(?([A-Ja-j])[\).:]\s+(.+?)\s*$").expect("regex");
        let (q, o) = chat_item("Which is a noble gas?\nA. Neon\nB) Iron\n(C) Tin\n", &re, 2);
        assert_eq!(q, "Which is a noble gas?");
        assert_eq!(o, vec!["Neon", "Iron", "Tin"]);
        let (q, o) = chat_item("List:\nB. one\nC. two", &re, 2);
        assert_eq!((q.as_str(), o.len()), ("List:\nB. one\nC. two", 0));
        let (_, o) = chat_item("Compute 2+2.", &re, 2);
        assert!(o.is_empty());
    }

    #[test]
    fn python_line_splitting_is_kept() {
        assert_eq!(py_lines("a\r\nb\rc\u{2028}d"), vec!["a", "b", "c", "d"]);
        assert_eq!(
            fill("{a} {b} {c}", &[("a", "1"), ("b", "{c}")]),
            "1 {c} {c}"
        );
    }
}
