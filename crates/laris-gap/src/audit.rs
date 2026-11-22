//! The citation audit, the same for the system's report and for every baseline answer.
//!
//! For one answer it lists:
//!
//! * **citations**: register ids (`[P3]`, `(P2, P5)`) and author–year or title references. A register id that is
//!   not in the register is *nonexistent*. An author–year or title reference that matches no paper of the register
//!   is *unresolved*; whether it exists elsewhere is checked by the caller against the works index
//!   ([`Citation::exists_externally`]), and one that is found nowhere is nonexistent too.
//! * **quotations** in double quotes of five words or more: *fabricated* when no paper of the register holds them.
//! * **claims**: sentences of the answer body of six words or more that are not headings. A claim with no citation
//!   is *uncited*. A claim matching an absence pattern ("no prior work", "chưa ai làm") is an *absence claim*; it
//!   is *unscoped* when it does not also match a scope pattern ("among the papers read").
//!
//! These are text rules: an uncited claim may be true, and a cited one may not be supported by its source. The
//! audit lists every flagged sentence so a person can judge it.

use crate::config::Settings;
use crate::extract::Paper;
use crate::text::{normalize, sentences, token_f1};
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::sync::OnceLock;

/// One citation in an answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Citation {
    /// As written.
    pub text: String,
    /// `register` (a `Pn` id) or `reference` (author–year or title).
    pub kind: String,
    /// The register id it resolves to, when it does.
    pub resolved: Option<String>,
    /// For an unresolved reference: whether the works index knows it (`None` until checked).
    #[serde(default)]
    pub exists_externally: Option<bool>,
    /// What the works index answered, for the person who checks.
    #[serde(default)]
    pub external_match: String,
}

impl Citation {
    /// Nonexistent: a register id outside the register, or a reference found neither in the register nor in the
    /// works index.
    pub fn nonexistent(&self) -> bool {
        self.resolved.is_none()
            && (self.kind == "register" || self.exists_externally == Some(false))
    }
}

/// One quotation of an answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Quotation {
    /// The quotation.
    pub text: String,
    /// The paper that holds it, when one does.
    pub found_in: Option<String>,
}

/// One claim of an answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ClaimCheck {
    /// The sentence.
    pub sentence: String,
    /// It carries a citation.
    pub cited: bool,
    /// It is a claim from absence.
    pub absence: bool,
    /// It limits itself to the papers read.
    pub scoped: bool,
}

/// Counts of one audit.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct AuditCounts {
    /// Citations.
    pub citations: usize,
    /// Of which nonexistent (after the external check, when it ran).
    pub citations_nonexistent: usize,
    /// References not in the register and not yet checked externally.
    pub citations_unchecked: usize,
    /// Quotations.
    pub quotations: usize,
    /// Quotations no paper holds.
    pub quotations_fabricated: usize,
    /// Claims.
    pub claims: usize,
    /// Claims without a citation.
    pub claims_uncited: usize,
    /// Claims from absence.
    pub absence_claims: usize,
    /// Claims from absence not limited to the papers read.
    pub absence_unscoped: usize,
}

/// The audit of one answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Audit {
    /// Citations.
    pub citations: Vec<Citation>,
    /// Quotations.
    pub quotations: Vec<Quotation>,
    /// Claims.
    pub claims: Vec<ClaimCheck>,
    /// Counts.
    pub counts: AuditCounts,
}

fn re(cell: &'static OnceLock<Regex>, source: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(source).unwrap_or_else(|e| panic!("{source}: {e}")))
}

fn regexes(list: &[String]) -> Vec<Regex> {
    list.iter()
        .filter_map(|p| RegexBuilder::new(p).case_insensitive(true).build().ok())
        .collect()
}

/// Audits `answer` against the register `papers`.
pub fn audit(answer: &str, papers: &[Paper], settings: &Settings) -> Audit {
    static REG: OnceLock<Regex> = OnceLock::new();
    static AUTHOR: OnceLock<Regex> = OnceLock::new();
    static QUOTE: OnceLock<Regex> = OnceLock::new();
    let reg = re(&REG, r"\bP(\d{1,3})\b");
    let author = re(
        &AUTHOR,
        r"\b([A-Z][A-Za-zÀ-ž'\-]+)(?: et al\.?| and [A-Z][A-Za-zÀ-ž'\-]+)?,? \(?((?:19|20)\d{2})[a-z]?\)?",
    );
    let quote = re(&QUOTE, r#"["“]([^"”\n]{20,400})["”]"#);
    static TITLE: OnceLock<Regex> = OnceLock::new();
    // a title given as `Title: ...` or in single-star italics, as a closed-book answer names its sources
    let title = re(
        &TITLE,
        r"(?m)(?:\bTitle\b\**:\**[ \t]*\**([^*\n]{12,220}?)\**[ \t]*$)|(?:(?:^|[^*\w])\*([A-Z][^*\n]{12,220}?)\*(?:[^*\w]|$))",
    );
    let mut citations = Vec::new();
    for m in reg.captures_iter(answer) {
        let id = format!("P{}", &m[1]);
        let known = papers.iter().any(|p| p.id == id);
        citations.push(Citation {
            text: id.clone(),
            kind: "register".into(),
            resolved: known.then_some(id),
            exists_externally: None,
            external_match: String::new(),
        });
    }
    // the span of every quotation found in a paper: a reference inside it is that paper's, not the answer's
    let quoted: Vec<(usize, usize)> = quote
        .captures_iter(answer)
        .filter_map(|m| m.get(1))
        .filter(|g| {
            papers
                .iter()
                .any(|p| crate::text::locate(&normalize(&p.text), g.as_str()).is_some())
        })
        .map(|g| (g.start(), g.end()))
        .collect();
    for m in author.captures_iter(answer) {
        let at = m.get(0).map_or(0, |g| g.start());
        if quoted.iter().any(|(a, b)| *a <= at && at < *b) {
            continue;
        }
        let name = m[1].to_lowercase();
        if [
            "figure", "table", "section", "in", "since", "by", "from", "until", "the",
        ]
        .contains(&name.as_str())
        {
            continue;
        }
        let resolved = papers
            .iter()
            .find(|p| {
                let head = normalize(p.text.get(..p.text.len().min(3000)).unwrap_or(""));
                head.contains(&normalize(&name)) && p.year.is_none_or(|y| y.to_string() == m[2])
            })
            .map(|p| p.id.clone());
        citations.push(Citation {
            text: m[0].to_owned(),
            kind: "reference".into(),
            resolved,
            exists_externally: None,
            external_match: String::new(),
        });
    }
    let mut titles: Vec<String> = Vec::new();
    for m in title.captures_iter(answer) {
        let t = m.get(1).or(m.get(2)).map_or("", |x| x.as_str()).trim();
        let t = t
            .trim_matches(|c: char| c == '"' || c == '“' || c == '”' || c == '.')
            .trim();
        // a phrase, not a title: too short, or a label of the answer itself
        if t.split_whitespace().count() < 3
            || t.ends_with(':')
            || titles.iter().any(|x| normalize(x) == normalize(t))
        {
            continue;
        }
        titles.push(t.to_owned());
        let resolved = papers
            .iter()
            .find(|p| token_f1(&p.title, t) > 0.8)
            .map(|p| p.id.clone());
        citations.push(Citation {
            text: t.to_owned(),
            kind: "reference".into(),
            resolved,
            exists_externally: None,
            external_match: String::new(),
        });
    }
    let mut quotations = Vec::new();
    for m in quote.captures_iter(answer) {
        let q = m[1].trim();
        if q.split_whitespace().count() < 5 {
            continue;
        }
        if titles.iter().any(|t| normalize(t) == normalize(q)) {
            continue;
        }
        // a quoted title of a paper of the register is a citation, not a quotation
        if let Some(p) = papers.iter().find(|p| token_f1(&p.title, q) > 0.8) {
            citations.push(Citation {
                text: q.to_owned(),
                kind: "reference".into(),
                resolved: Some(p.id.clone()),
                exists_externally: None,
                external_match: String::new(),
            });
            continue;
        }
        let found_in = papers
            .iter()
            .find(|p| crate::text::locate(&normalize(&p.text), q).is_some())
            .map(|p| p.id.clone());
        quotations.push(Quotation {
            text: q.to_owned(),
            found_in,
        });
    }
    let absence = regexes(&settings.absence_patterns);
    let scope = regexes(&settings.scope_patterns);
    let mut claims = Vec::new();
    for line in answer.lines() {
        let t = line.trim();
        if t.is_empty() || t.starts_with('#') || t.starts_with('|') {
            continue;
        }
        let body = t
            .trim_start_matches(['-', '*', ' '])
            .trim_start_matches(|c: char| c.is_ascii_digit() || c == '.')
            .trim();
        for s in sentences(body) {
            if s.split_whitespace().count() < 6 {
                continue;
            }
            let cited = reg.is_match(&s) || author.is_match(&s) || s.contains('[');
            let is_absence = absence.iter().any(|r| r.is_match(&s));
            let scoped = scope.iter().any(|r| r.is_match(&s));
            claims.push(ClaimCheck {
                sentence: s,
                cited,
                absence: is_absence,
                scoped,
            });
        }
    }
    let mut a = Audit {
        citations,
        quotations,
        claims,
        counts: AuditCounts::default(),
    };
    recount(&mut a);
    a
}

/// Recomputes the counts, e.g. after the external check filled `exists_externally`.
pub fn recount(a: &mut Audit) {
    a.counts = AuditCounts {
        citations: a.citations.len(),
        citations_nonexistent: a.citations.iter().filter(|c| c.nonexistent()).count(),
        citations_unchecked: a
            .citations
            .iter()
            .filter(|c| {
                c.kind == "reference" && c.resolved.is_none() && c.exists_externally.is_none()
            })
            .count(),
        quotations: a.quotations.len(),
        quotations_fabricated: a.quotations.iter().filter(|q| q.found_in.is_none()).count(),
        claims: a.claims.len(),
        claims_uncited: a.claims.iter().filter(|c| !c.cited).count(),
        absence_claims: a.claims.iter().filter(|c| c.absence).count(),
        absence_unscoped: a.claims.iter().filter(|c| c.absence && !c.scoped).count(),
    };
}
