//! The gate: checks an answer against the evidence of its turn and marks what does not hold.

use crate::citation::{self, Target};
use crate::evidence::Evidence;
use crate::text::{Sentence, mask_code, quote_in, sentences};
use regex::Regex;
use std::ops::Range;
use std::sync::LazyLock;

/// What a finding is about.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FindingKind {
    /// A citation names no evidence of this turn.
    FabricatedCitation,
    /// A quote before a citation is not in the evidence it cites.
    SpanMissing,
    /// A statement cites nothing and is not marked as assumed or speculative (rules E-2, E-6).
    UnsupportedStatement,
    /// A conclusion of absence that does not say what was searched (rule E-5).
    AbsenceClaim,
}

impl FindingKind {
    /// A stable code for logs.
    pub fn code(self) -> &'static str {
        match self {
            Self::FabricatedCitation => "fabricated_citation",
            Self::SpanMissing => "span_missing",
            Self::UnsupportedStatement => "unsupported_statement",
            Self::AbsenceClaim => "absence_claim",
        }
    }
}

/// One thing the gate found.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Finding {
    /// What it is.
    pub kind: FindingKind,
    /// The citation or sentence, as written.
    pub text: String,
    /// Where it stands in the answer (bytes).
    pub range: Range<usize>,
}

/// The marks put into an answer next to what was found.
#[derive(Clone, Debug)]
pub struct Marks {
    /// After a citation that names no evidence.
    pub fabricated: String,
    /// After a citation whose quote is not in its evidence.
    pub span_missing: String,
    /// After a statement with no citation.
    pub unsupported: String,
    /// After a conclusion of absence.
    pub absence: String,
}

impl Default for Marks {
    fn default() -> Self {
        Self {
            fabricated: " [citation not found in the evidence]".into(),
            span_missing: " [quote not found in the cited evidence]".into(),
            unsupported: " [unsupported: no citation, not marked as assumed]".into(),
            absence: " [absence of a hit is not evidence of absence: state what was searched]"
                .into(),
        }
    }
}

/// The gate's settings.
#[derive(Clone, Debug)]
pub struct Config {
    /// Fewest words a sentence needs to count as a statement.
    pub min_words: usize,
    /// Fewest characters a quote needs to be compared with its source.
    pub min_quote_chars: usize,
    /// Treat every answer as a research answer. Otherwise statements are held to a citation only when the turn
    /// retrieved evidence or the answer cites something.
    pub always: bool,
    /// The marks.
    pub marks: Marks,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            min_words: 6,
            min_quote_chars: 8,
            always: false,
            marks: Marks::default(),
        }
    }
}

/// The result of a check.
#[derive(Clone, Debug)]
pub struct Verdict {
    /// What was found, in the order of the answer.
    pub findings: Vec<Finding>,
    /// The answer with a mark next to each finding; the answer itself, unchanged, when there is none.
    pub text: String,
}

impl Verdict {
    /// Whether the answer passed.
    pub fn is_clean(&self) -> bool {
        self.findings.is_empty()
    }

    /// Whether something of `kind` was found.
    pub fn has(&self, kind: FindingKind) -> bool {
        self.findings.iter().any(|f| f.kind == kind)
    }
}

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("valid gate pattern")
}

/// A sentence that concludes that something is missing from the literature.
static ABSENCE: LazyLock<Regex> = LazyLock::new(|| {
    re(
        r"(?i)\bno (evidence|studies|study|papers?|research|literature|work|publications?|reports?|data|sources?|mention|one has)\b|\b(nobody|no one) has\b|\b(has|have) (never|not) been (studied|explored|investigated|reported|tested|done|addressed)\b|\bdoes not exist\b|\b(research|knowledge|literature) gaps?\b|\bgaps? in the (literature|research)\b|\bunder-?explored\b|\blacks? (any )?(evidence|studies|research)\b|\bnot (mentioned|covered|addressed|discussed) (in|by)\b|không có (bằng chứng|nghiên cứu|công trình|tài liệu)|khoảng trống nghiên cứu|chưa (có|được) (nghiên cứu|công bố)",
    )
});

/// Words that say what was searched, which is what makes a statement of absence acceptable.
static SCOPE: LazyLock<Regex> = LazyLock::new(|| {
    re(
        r"(?i)\b(searched|search|retrieved|retrieval|quer(y|ies)|corpus|the (provided|returned|retrieved|given) (documents|sources|excerpts|passages|results)|did not (find|return|surface)|found no|no (hits|matches))\b|đã tìm|kho tài liệu|truy xuất",
    )
});

/// A statement marked as not backed by a source (rule E-6).
static MARKED: LazyLock<Regex> = LazyLock::new(|| {
    re(
        r"(?i)\b(assumed|assumption|speculative|speculation|hypothesis|hypothesi[sz]e[sd]?|unverified|uncertain|not (from|in) the (corpus|documents|sources))\b|giả định|suy đoán|giả thuyết|chưa kiểm chứng",
    )
});

/// A sentence that talks about the answer or the user, not about the world.
static META: LazyLock<Regex> = LazyLock::new(|| {
    re(
        r"(?i)^\W*(i|i'm|i've|i'll|let me|let's|here|below|above|note|next|please|you|would you|do you|if you|sure|thanks)\b",
    )
});

/// A line that names a closing block of an answer (Assumptions | Uncertainties | Next step | Sources).
static LABEL: LazyLock<Regex> = LazyLock::new(|| {
    re(
        r"(?i)^\s*(?:[-*]\s*)?(?:\*\*|__)?(assumptions?|uncertainties|uncertainty|next steps?|sources?|references?|limitations?|giả định|điểm chưa chắc chắn|bước tiếp theo|nguồn)(?:\*\*|__)?\s*(?:[:|]|$)",
    )
});
static HEADING: LazyLock<Regex> = LazyLock::new(|| re(r"^\s*#{1,6}\s+(.*)$"));
static LIST_ITEM: LazyLock<Regex> = LazyLock::new(|| re(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+"));
static RULE_LINE: LazyLock<Regex> = LazyLock::new(|| re(r"^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$"));

/// The evidence gate.
#[derive(Clone, Debug, Default)]
pub struct Gate {
    config: Config,
}

impl Gate {
    /// A gate with the default settings.
    pub fn new() -> Self {
        Self::default()
    }

    /// A gate with these settings.
    pub fn with_config(config: Config) -> Self {
        Self { config }
    }

    /// A gate that holds every answer to the research rules, retrieved evidence or not.
    pub fn strict() -> Self {
        Self {
            config: Config {
                always: true,
                ..Config::default()
            },
        }
    }

    /// Checks `answer` against `evidence`.
    pub fn check(&self, answer: &str, evidence: &Evidence) -> Verdict {
        let masked = mask_code(answer);
        let cites = citation::parse_masked(answer, &masked);
        let mut findings: Vec<Finding> = Vec::new();
        let mut marks: Vec<(usize, &str)> = Vec::new();

        for cite in &cites {
            let range = cite.start..cite.end;
            let (kind, mark) = match &cite.target {
                Target::Workspace { source, rank } => {
                    let hits = evidence.matching(source, *rank);
                    if hits.is_empty() {
                        (
                            FindingKind::FabricatedCitation,
                            &self.config.marks.fabricated,
                        )
                    } else {
                        let missing = cite.quote.as_deref().is_some_and(|q| {
                            q.chars().count() >= self.config.min_quote_chars
                                && !hits.iter().any(|h| quote_in(q, &h.text))
                        });
                        if !missing {
                            continue;
                        }
                        (FindingKind::SpanMissing, &self.config.marks.span_missing)
                    }
                }
                Target::Brain { title } => {
                    if evidence.has_brain(title) {
                        continue;
                    }
                    (
                        FindingKind::FabricatedCitation,
                        &self.config.marks.fabricated,
                    )
                }
            };
            findings.push(Finding {
                kind,
                text: answer[range.clone()].to_string(),
                range,
            });
            marks.push((cite.end, mark));
        }

        let strict = self.config.always || !evidence.is_empty() || !cites.is_empty();
        let inside = |at: usize| cites.iter().any(|c| c.start <= at && at < c.end);
        let cite_at = |at: usize| cites.iter().find(|c| c.start == at).map(|c| c.end);
        for unit in units(&masked) {
            if unit.exempt {
                continue;
            }
            for Sentence { range } in sentences(&masked, unit.range.clone(), &inside, &cite_at) {
                let sentence = &answer[range.clone()];
                let cited = cites
                    .iter()
                    .any(|c| c.start >= range.start && c.end <= range.end);
                let absence = ABSENCE.is_match(sentence);
                let kind = if absence && SCOPE.is_match(sentence) {
                    // A report of what a search returned, not a claim about the world.
                    continue;
                } else if absence {
                    FindingKind::AbsenceClaim
                } else if strict
                    && !cited
                    && self.is_statement(sentence)
                    && !MARKED.is_match(sentence)
                {
                    FindingKind::UnsupportedStatement
                } else {
                    continue;
                };
                let mark = if kind == FindingKind::AbsenceClaim {
                    &self.config.marks.absence
                } else {
                    &self.config.marks.unsupported
                };
                marks.push((range.end, mark));
                findings.push(Finding {
                    kind,
                    text: sentence.to_string(),
                    range,
                });
            }
        }

        findings.sort_by_key(|f| f.range.start);
        if findings.is_empty() {
            return Verdict {
                findings,
                text: answer.to_string(),
            };
        }
        marks.sort_by_key(|(at, _)| *at);
        let mut text = answer.to_string();
        for (at, mark) in marks.into_iter().rev() {
            text.insert_str(at, mark);
        }
        Verdict { findings, text }
    }

    /// Whether a sentence is a statement about the world that needs a source.
    fn is_statement(&self, sentence: &str) -> bool {
        let words = sentence
            .split_whitespace()
            .filter(|w| w.chars().any(char::is_alphanumeric))
            .count();
        words >= self.config.min_words
            && !sentence.trim_end().ends_with('?')
            && !META.is_match(sentence)
    }
}

/// A run of text checked together: a paragraph or one list item.
struct Unit {
    range: Range<usize>,
    /// Inside a closing block (Assumptions, Sources, ...), a heading, a table or a rule: not checked.
    exempt: bool,
}

/// Splits the masked answer into paragraphs and list items, and marks the closing blocks as exempt.
fn units(masked: &str) -> Vec<Unit> {
    let mut out: Vec<Unit> = Vec::new();
    let mut open: Option<usize> = None; // index of the unit a wrapped line would continue
    let mut block = false;
    let mut offset = 0;
    for line in masked.split_inclusive('\n') {
        let start = offset;
        offset += line.len();
        let body = line.trim_end_matches(['\n', '\r']);
        let end = start + body.len();
        let single = |out: &mut Vec<Unit>, exempt: bool| {
            out.push(Unit {
                range: start..end,
                exempt,
            })
        };
        if body.trim().is_empty() {
            block = false;
            open = None;
        } else if let Some(caps) = HEADING.captures(body) {
            block = LABEL.is_match(&caps[1]);
            single(&mut out, true);
            open = None;
        } else if LABEL.is_match(body) {
            block = true;
            single(&mut out, true);
            open = None;
        } else if body.trim_start().starts_with('|') || RULE_LINE.is_match(body) {
            single(&mut out, true);
            open = None;
        } else if LIST_ITEM.is_match(body) {
            let skip = LIST_ITEM.find(body).map_or(0, |m| m.end());
            out.push(Unit {
                range: start + skip..end,
                exempt: block,
            });
            open = Some(out.len() - 1);
        } else if let Some(i) = open {
            out[i].range.end = end;
        } else {
            out.push(Unit {
                range: start..end,
                exempt: block,
            });
            open = Some(out.len() - 1);
        }
    }
    out
}
