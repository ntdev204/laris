//! The sections of a paper, found from its headings, so every extracted item can say where it was written.
//!
//! A heading is a short line, optionally numbered (`3.`, `IV.`, `2.1`, `A.`), whose words name a known section
//! (see [`canonical`]). PDF text often letter-spaces small capitals (`C ONCLUSION`); those spaces are closed first.
//! A heading that names no known section (a subsection title) keeps the section it is in. Text before the first
//! heading is `front` (title, authors, often the abstract). The section names are fixed so the reports and the gold
//! standard use the same words.

use regex::Regex;
use serde::Serialize;
use std::sync::OnceLock;

/// One section of a paper: its canonical name, the heading line as written and its byte span in the text.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Section {
    /// `front`, `abstract`, `introduction`, `related`, `method`, `experiments`, `results`, `discussion`,
    /// `limitations`, `conclusion`, `future_work`, `references`, `acknowledgements` or `appendix`.
    pub name: String,
    /// The heading line as it is in the text (empty for `front`).
    pub heading: String,
    /// Byte offset where the section starts (its heading line included).
    pub start: usize,
    /// Byte offset after its last byte.
    pub end: usize,
}

fn pattern(cell: &'static OnceLock<Regex>, source: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(source).unwrap_or_else(|e| panic!("bad pattern {source}: {e}")))
}

/// The canonical section a heading names, or `None` for a heading that names none.
pub fn canonical(heading: &str) -> Option<&'static str> {
    static SPACED: OnceLock<Regex> = OnceLock::new();
    static NUMBER: OnceLock<Regex> = OnceLock::new();
    let closed = pattern(&SPACED, r"\b([A-Z]) ([A-Z]{2,})\b").replace_all(heading.trim(), "$1$2");
    let bare = pattern(
        &NUMBER,
        r"^(?:[IVXL]+\.|\d+(?:\.\d+)*\.?|[A-H]\.|[A-H]\d*(?:\.\d+)*)\s*",
    )
    .replace(&closed, "");
    let h = bare.trim().trim_end_matches([':', '.']).to_lowercase();
    if h.is_empty() || h.len() > 60 {
        return None;
    }
    let starts = |words: &[&str]| {
        words
            .iter()
            .any(|w| h == *w || h.starts_with(&format!("{w} ")))
    };
    let has = |words: &[&str]| words.iter().any(|w| h.contains(w));
    Some(if starts(&["abstract"]) {
        "abstract"
    } else if starts(&["introduction", "motivation"]) {
        "introduction"
    } else if has(&[
        "related work",
        "background",
        "preliminar",
        "literature",
        "prior work",
    ]) {
        "related"
    } else if has(&["limitation", "threats to validity", "broader impact"]) {
        "limitations"
    } else if has(&[
        "future work",
        "future research",
        "outlook",
        "future direction",
    ]) {
        "future_work"
    } else if has(&["conclusion", "concluding", "summary"]) {
        "conclusion"
    } else if has(&["discussion"]) {
        "discussion"
    } else if has(&["result", "analysis", "ablation", "findings"]) {
        "results"
    } else if has(&[
        "experiment",
        "evaluation",
        "simulation",
        "setup",
        "implementation",
        "benchmark",
        "case study",
        "validation",
        "hardware",
    ]) {
        "experiments"
    } else if has(&[
        "method",
        "approach",
        "formulation",
        "proposed",
        "framework",
        "model predictive",
        "design",
        "architecture",
        "algorithm",
        "system",
        "problem",
        "dataset",
        "data",
        "task",
    ]) {
        "method"
    } else if starts(&["references", "bibliography"]) {
        "references"
    } else if starts(&["acknowledg"]) || h.starts_with("acknowledg") {
        "acknowledgements"
    } else if starts(&["appendix", "appendices", "supplementary"]) {
        "appendix"
    } else {
        return None;
    })
}

fn is_heading_line(line: &str) -> bool {
    let t = line.trim();
    if t.is_empty() || t.len() > 70 || t.ends_with(',') || t.ends_with(';') {
        return false;
    }
    if t.ends_with('.') || t.contains('—') || t.contains(" - ") {
        return false;
    }
    // a period inside the line is only allowed in the numbering ("IV. RESULTS", "3.2 Data")
    let after_number =
        t.trim_start_matches(|c: char| c.is_ascii_digit() || "IVXL.".contains(c) || c == ' ');
    if after_number.contains(". ") {
        return false;
    }
    let words = t.split_whitespace().count();
    if words > 9 {
        return false;
    }
    // a heading starts with a number, a capital letter, or is all capitals
    let first = t.chars().next().unwrap_or(' ');
    first.is_ascii_digit() || first.is_uppercase()
}

/// Whether a heading line is numbered (`3.`, `IV.`, `2.1`, `A.`) or written in capitals; such a line may name any
/// known section. Any other line must start with a word that only a heading starts with.
fn is_strong(line: &str) -> bool {
    static NUMBERED: OnceLock<Regex> = OnceLock::new();
    let t = line.trim();
    if pattern(&NUMBERED, r"^(?:[IVXL]+\.|\d+(?:\.\d+)*\.?|[A-H]\.)\s+\S").is_match(t) {
        return true;
    }
    let letters: Vec<char> = t.chars().filter(|c| c.is_alphabetic()).collect();
    if letters.len() >= 4 && letters.iter().all(|c| c.is_uppercase()) {
        return true;
    }
    let first = t.split_whitespace().next().unwrap_or("").to_lowercase();
    let words = t.split_whitespace().count();
    words <= 5
        && [
            "abstract",
            "introduction",
            "related",
            "background",
            "preliminaries",
            "methods",
            "methodology",
            "experiments",
            "experimental",
            "evaluation",
            "results",
            "discussion",
            "limitations",
            "limitation",
            "conclusion",
            "conclusions",
            "future",
            "references",
            "acknowledgments",
            "acknowledgements",
            "acknowledgment",
            "appendix",
            "ethics",
            "ethical",
            "broader",
        ]
        .contains(&first.as_str())
}

/// The sections of `text`, in order and covering all of it.
pub fn split(text: &str) -> Vec<Section> {
    let mut marks: Vec<(usize, String, &'static str)> = Vec::new();
    let mut offset = 0;
    for line in text.split_inclusive('\n') {
        let t = line.trim();
        if is_heading_line(t) && is_strong(t) {
            if let Some(name) = canonical(t) {
                // one section name opening twice in a row (a heading repeated by the page header) is kept once
                if marks
                    .last()
                    .is_none_or(|(_, _, last)| *last != name || name == "method")
                {
                    marks.push((offset, t.to_owned(), name));
                }
            }
        } else if let Some(rest) = t.strip_prefix("Abstract") {
            // "Abstract—We propose ..." on one line
            if rest.starts_with(['—', '-', ':', '.', ' '])
                && marks.iter().all(|m| m.2 != "abstract")
            {
                marks.push((offset, "Abstract".to_owned(), "abstract"));
            }
        }
        offset += line.len();
    }
    let mut out = Vec::new();
    let first = marks.first().map_or(text.len(), |m| m.0);
    if first > 0 {
        out.push(Section {
            name: "front".into(),
            heading: String::new(),
            start: 0,
            end: first,
        });
    }
    for (i, (start, heading, name)) in marks.iter().enumerate() {
        let end = marks.get(i + 1).map_or(text.len(), |m| m.0);
        out.push(Section {
            name: (*name).to_owned(),
            heading: heading.clone(),
            start: *start,
            end,
        });
    }
    out
}

/// The canonical name of the section that holds byte offset `at`.
pub fn section_at(sections: &[Section], at: usize) -> &str {
    sections
        .iter()
        .find(|s| s.start <= at && at < s.end)
        .map_or("front", |s| s.name.as_str())
}

/// The text of every section named `name`, joined by a blank line.
pub fn text_of(text: &str, sections: &[Section], name: &str) -> String {
    sections
        .iter()
        .filter(|s| s.name == name)
        .filter_map(|s| text.get(s.start..s.end))
        .collect::<Vec<_>>()
        .join("\n\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numbered_and_letter_spaced_headings_are_known() {
        assert_eq!(canonical("V. C ONCLUSION"), Some("conclusion"));
        assert_eq!(canonical("6 Limitations"), Some("limitations"));
        assert_eq!(canonical("2.1 Related Work"), Some("related"));
        assert_eq!(canonical("Conclusion and Future Work"), Some("future_work"));
        assert_eq!(canonical("Fig. 3 shows"), None);
    }

    #[test]
    fn a_paper_is_cut_at_its_headings() {
        let text = "Title\nAbstract—We do X.\nI. INTRODUCTION\nWhy.\nII. METHOD\nHow.\nV. C ONCLUSION\nDone. Future work is Y.\nREFERENCES\n[1] A.\n";
        let s = split(text);
        let names: Vec<&str> = s.iter().map(|x| x.name.as_str()).collect();
        assert_eq!(
            names,
            vec![
                "front",
                "abstract",
                "introduction",
                "method",
                "conclusion",
                "references"
            ]
        );
        let at = text.find("Future work").unwrap();
        assert_eq!(section_at(&s, at), "conclusion");
    }
}
