//! Steps 3 and 4: knowledge links over the extraction records, the gap rules G1–G4, their filters, and the ranking.
//!
//! Everything here is a function of the papers, the records, the topic and the policy: no model is called, and the
//! same input gives the same output. Every intermediate result is kept in [`Analysis`] so a person can check each
//! step: which term put which concept on which item, which candidate each rule produced, which filter removed it and
//! why, how each score was computed.
//!
//! # Rules (R is the set of papers read)
//!
//! * **G1 repeated limitation**: an issue concept `x` is on the limitation or future-work items of at least
//!   `rules.min_papers_g1` papers of R, with at least `rules.min_verified_g1` quotations found verbatim, and no
//!   *other* paper of R addresses `x` (its problem, method or result field carries `x`).
//! * **G2 unresolved conflict**: a claim `r = (p, c, −)` (a sentence of paper `p` with a negative cue that names
//!   method `c`: in its problem or result field, its limitation items, or verbatim in its abstract or introduction,
//!   where papers state what they take to be infeasible) and a claim `r′ = (q, c, +)` (paper `q ≠ p` uses `c` and its result has a positive cue) conflict,
//!   `r ⊥ r′`. The conflict is **explained**, and gives no gap, when (a) `p` and `q` share no setting concept (they
//!   speak of different hardware or data), or (b) `p` itself reports `c` working (its negative sentence is about
//!   another configuration), or (c) the setting of `p` is unknown (nothing to compare). Otherwise it is unexplained.
//! * **G3 untried combination**: method `m` and setting `s` both occur in R, no paper uses `m` on `s`, and (when
//!   `rules.g3_needs_common_issue`) the papers of `m` and of `s` state at least one common issue.
//! * **G4 weak evidence**: a method of R is used by one paper only.
//!
//! No rule concludes from absence alone: every statement says "among the papers read".
//!
//! # Ranking
//!
//! `s(g) = w1·|papers(g)| + w2·[g ∈ G1 ∪ G2] + w3·|verified quotes(g)| − w4·[|papers(g)| = 1]`, weights from the
//! policy. The score orders the presentation; it does not measure scientific value.

use crate::config::{Settings, Topic};
use crate::extract::{Paper, Record};
use crate::sections::{self, Section};
use crate::text::{contains_words, normalize, normalize_with_map, sentences};
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// How a quotation was found in its paper.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Found {
    /// The same characters, white space aside.
    Verbatim,
    /// The same words after normalisation (ligatures, hyphenation, punctuation).
    Normalized,
    /// Not in the paper.
    Missing,
    /// The model gave no quotation (or one shorter than five words).
    NoQuote,
}

impl Found {
    /// Whether the quotation counts as verified.
    pub fn verified(self) -> bool {
        matches!(self, Found::Verbatim | Found::Normalized)
    }
}

/// One extracted limitation or future-work item with its check.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Item {
    /// `P3-L1` (limitation) or `P3-F2` (future work).
    pub id: String,
    /// The paper.
    pub paper: String,
    /// `limitation` or `future_work`.
    pub kind: String,
    /// The paraphrase.
    pub text: String,
    /// The quotation.
    pub quote: String,
    /// How the quotation was found.
    pub found: Found,
    /// The section that holds the quotation (`unknown` when it was not found).
    pub section: String,
}

/// A concept put on a subject by a term.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tag {
    /// An item id, or `P3:method` for a field of a record.
    pub subject: String,
    /// The paper.
    pub paper: String,
    /// `problem`, `method`, `setting`, `result`, `limitation` or `future_work`.
    pub field: String,
    /// `method`, `setting` or `issue`.
    pub facet: String,
    /// The concept.
    pub concept: String,
    /// The term that matched.
    pub term: String,
}

/// A link with its source.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Edge {
    /// The paper.
    pub paper: String,
    /// `uses method`, `evaluated on`, `addresses`, `states limitation about`, `proposes future work on`.
    pub relation: String,
    /// The concept.
    pub concept: String,
    /// Its facet.
    pub facet: String,
    /// The subject the link came from (a field or an item id).
    pub via: String,
}

/// One piece of evidence of a candidate.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    /// The paper.
    pub paper: String,
    /// Item id or field.
    pub via: String,
    /// Section of the quotation, or the field name.
    pub section: String,
    /// The quotation, or the field text.
    pub text: String,
    /// Whether the quotation was found in the paper (`false` for a field).
    pub verified: bool,
}

/// A claim of rule G2.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Claim {
    /// The paper.
    pub paper: String,
    /// Field or item id the sentence is from.
    pub via: String,
    /// The sentence.
    pub sentence: String,
    /// The cue that matched.
    pub cue: String,
}

/// One pair `r ⊥ r′` of rule G2 with its explanation check.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Conflict {
    /// The method both claims are about.
    pub method: String,
    /// `r = (p, c, −)`.
    pub negative: Claim,
    /// `r′ = (q, c, +)`.
    pub positive: Claim,
    /// Setting concepts of `p`.
    pub settings_negative: Vec<String>,
    /// Setting concepts of `q`.
    pub settings_positive: Vec<String>,
    /// Whether condition (a), (b) or (c) holds.
    pub explained: bool,
    /// Which condition, in words.
    pub explanation: String,
}

/// A gap candidate of one rule, kept or filtered.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Candidate {
    /// `C1`, `C2`, ... in the order the rules produced them.
    pub id: String,
    /// `G1`, `G2`, `G3` or `G4`.
    pub rule: String,
    /// The gap in one sentence, limited to the papers read.
    pub statement: String,
    /// The concepts it is about.
    pub concepts: Vec<String>,
    /// Papers that support it.
    pub papers: Vec<String>,
    /// Its evidence.
    pub evidence: Vec<Evidence>,
    /// `kept` or `filtered`.
    pub status: String,
    /// Filter code (`g1_one_paper`, `g1_addressed`, `g1_unverified`, `g2_explained`, `g3_no_common_issue`) or empty.
    pub reason: String,
    /// The filter's reason in words, or empty.
    pub detail: String,
}

/// The score of a kept candidate and its parts.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Ranked {
    /// Rank, from 1.
    pub rank: usize,
    /// Gap id `KT1`, ...
    pub gap: String,
    /// Candidate id.
    pub candidate: String,
    /// Rule.
    pub rule: String,
    /// `|papers(g)|`.
    pub papers: usize,
    /// `[g ∈ G1 ∪ G2]`.
    pub primary: bool,
    /// `|verified quotes(g)|`.
    pub verified: usize,
    /// `[|papers(g)| = 1]`.
    pub single: bool,
    /// `w1·papers`, `w2·primary`, `w3·verified`, `−w4·single`.
    pub parts: [f64; 4],
    /// Their sum.
    pub score: f64,
}

/// Per-rule counts.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuleCount {
    /// Candidates produced.
    pub generated: usize,
    /// Kept.
    pub kept: usize,
    /// Filtered, by reason code.
    pub filtered: BTreeMap<String, usize>,
}

/// Summary counts of a run.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Counts {
    /// Papers given.
    pub papers: usize,
    /// Papers whose record parsed.
    pub papers_parsed: usize,
    /// Items extracted.
    pub items: usize,
    /// Items with a quotation of five words or more.
    pub quotes: usize,
    /// Quotations found verbatim.
    pub quotes_verbatim: usize,
    /// Quotations found after normalisation.
    pub quotes_normalized: usize,
    /// Quotations not found.
    pub quotes_missing: usize,
    /// Concept tags.
    pub tags: usize,
    /// Concept tags on limitation and future-work items (the ones a person judges).
    pub item_tags: usize,
    /// Links.
    pub edges: usize,
    /// Distinct concepts that occur.
    pub concepts: usize,
    /// G2 pairs found.
    pub conflict_pairs: usize,
    /// G2 pairs explained.
    pub conflict_pairs_explained: usize,
    /// Per rule.
    pub rules: BTreeMap<String, RuleCount>,
}

/// Per paper: whether its record parsed.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PaperStatus {
    /// Id.
    pub id: String,
    /// Title.
    pub title: String,
    /// Year.
    pub year: Option<u32>,
    /// How its text was read.
    pub read_by: String,
    /// Characters of text.
    pub chars: usize,
    /// The sections found.
    pub sections: Vec<String>,
    /// The record, when it parsed.
    pub record: Option<Record>,
    /// Why there is none.
    pub error: String,
}

/// Everything the analysis found.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Analysis {
    /// Version of the policy used.
    pub policy_version: String,
    /// Topic id.
    pub topic: String,
    /// Weights used.
    pub weights: crate::config::Weights,
    /// Rule parameters used.
    pub rules: crate::config::Rules,
    /// The papers.
    pub papers: Vec<PaperStatus>,
    /// Extracted items.
    pub items: Vec<Item>,
    /// Concept tags.
    pub tags: Vec<Tag>,
    /// Links.
    pub edges: Vec<Edge>,
    /// facet → concept → papers.
    pub concepts: BTreeMap<String, BTreeMap<String, Vec<String>>>,
    /// G2 pairs.
    pub conflicts: Vec<Conflict>,
    /// Every candidate.
    pub candidates: Vec<Candidate>,
    /// The ranking of the kept candidates.
    pub ranking: Vec<Ranked>,
    /// Counts.
    pub counts: Counts,
}

fn collapse(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Finds `quote` in `text`: how, and the byte offset when found.
pub fn find_quote(text: &str, quote: &str) -> (Found, Option<usize>) {
    if quote.split_whitespace().count() < 5 {
        return (Found::NoQuote, None);
    }
    let (norm, map) = normalize_with_map(text);
    let at = crate::text::locate(&norm, quote).and_then(|i| map.get(i).copied());
    if at.is_none() {
        return (Found::Missing, None);
    }
    let verbatim = collapse(text).contains(&collapse(quote));
    (
        if verbatim {
            Found::Verbatim
        } else {
            Found::Normalized
        },
        at,
    )
}

struct Lexicon {
    facet: String,
    concepts: Vec<(String, Vec<String>)>,
}

impl Lexicon {
    fn of(topic: &Topic, facet: &str) -> Lexicon {
        Lexicon {
            facet: facet.to_owned(),
            concepts: topic
                .facet(facet)
                .map(|(c, t)| (c.clone(), t.clone()))
                .collect(),
        }
    }

    /// `(concept, first matching term)` for every concept `text` carries.
    fn tag(&self, text: &str) -> Vec<(String, String)> {
        let n = normalize(text);
        self.concepts
            .iter()
            .filter_map(|(c, terms)| {
                terms
                    .iter()
                    .find(|t| contains_words(&n, t))
                    .map(|t| (c.clone(), t.clone()))
            })
            .collect()
    }
}

fn regexes(list: &[String]) -> Vec<(String, Regex)> {
    list.iter()
        .filter_map(|p| {
            RegexBuilder::new(p)
                .case_insensitive(true)
                .build()
                .ok()
                .map(|r| (p.clone(), r))
        })
        .collect()
}

fn ids(set: &BTreeSet<String>) -> String {
    set.iter().cloned().collect::<Vec<_>>().join(", ")
}

/// Runs steps 3 and 4. `records` holds, per paper id, the record or why there is none.
pub fn analyze(
    topic: &Topic,
    settings: &Settings,
    papers: &[Paper],
    records: &BTreeMap<String, Result<Record, String>>,
) -> Analysis {
    let method = Lexicon::of(topic, "method");
    let setting = Lexicon::of(topic, "setting");
    let issue = Lexicon::of(topic, "issue");
    let mut statuses = Vec::new();
    let mut items = Vec::new();
    let mut tags: Vec<Tag> = Vec::new();
    let mut parsed: BTreeMap<String, Record> = BTreeMap::new();
    for paper in papers {
        let secs: Vec<Section> = sections::split(&paper.text);
        let rec = records.get(&paper.id);
        statuses.push(PaperStatus {
            id: paper.id.clone(),
            title: paper.title.clone(),
            year: paper.year,
            read_by: paper.read_by.clone(),
            chars: paper.text.chars().count(),
            sections: secs.iter().map(|s| s.name.clone()).collect(),
            record: rec.and_then(|r| r.as_ref().ok()).cloned(),
            error: match rec {
                Some(Err(e)) => e.clone(),
                None => "no record".into(),
                Some(Ok(_)) => String::new(),
            },
        });
        let Some(Ok(record)) = rec else { continue };
        parsed.insert(paper.id.clone(), record.clone());
        for (kind, letter, list) in [
            ("limitation", 'L', &record.limitations),
            ("future_work", 'F', &record.future_work),
        ] {
            for (i, raw) in list.iter().enumerate() {
                let (found, at) = find_quote(&paper.text, &raw.quote);
                let id = format!("{}-{}{}", paper.id, letter, i + 1);
                for (lex, facet) in [(&issue, "issue")] {
                    for (concept, term) in lex.tag(&format!("{} {}", raw.text, raw.quote)) {
                        tags.push(Tag {
                            subject: id.clone(),
                            paper: paper.id.clone(),
                            field: kind.to_owned(),
                            facet: facet.to_owned(),
                            concept,
                            term,
                        });
                    }
                }
                items.push(Item {
                    id,
                    paper: paper.id.clone(),
                    kind: kind.to_owned(),
                    text: raw.text.clone(),
                    quote: raw.quote.clone(),
                    found,
                    section: at.map_or("unknown".to_owned(), |a| {
                        sections::section_at(&secs, a).to_owned()
                    }),
                });
            }
        }
        let fields = [
            ("problem", &record.problem),
            ("method", &record.method),
            ("setting", &record.setting),
            ("result", &record.result),
        ];
        for (field, value) in fields {
            let lexicons: Vec<&Lexicon> = match field {
                "method" => vec![&method, &issue],
                "problem" => vec![&method, &setting, &issue],
                "setting" => vec![&setting],
                _ => vec![&setting, &issue],
            };
            for lex in lexicons {
                for (concept, term) in lex.tag(value) {
                    tags.push(Tag {
                        subject: format!("{}:{}", paper.id, field),
                        paper: paper.id.clone(),
                        field: field.to_owned(),
                        facet: lex.facet.clone(),
                        concept,
                        term,
                    });
                }
            }
        }
    }

    // links
    let mut edges = Vec::new();
    let mut seen = BTreeSet::new();
    for t in &tags {
        let relation = match (t.facet.as_str(), t.field.as_str()) {
            ("method", _) => "uses method",
            ("setting", _) => "evaluated on",
            ("issue", "limitation") => "states limitation about",
            ("issue", "future_work") => "proposes future work on",
            ("issue", _) => "addresses",
            _ => continue,
        };
        if seen.insert((
            t.paper.clone(),
            relation,
            t.concept.clone(),
            t.subject.clone(),
        )) {
            edges.push(Edge {
                paper: t.paper.clone(),
                relation: relation.to_owned(),
                concept: t.concept.clone(),
                facet: t.facet.clone(),
                via: t.subject.clone(),
            });
        }
    }
    let mut concepts: BTreeMap<String, BTreeMap<String, BTreeSet<String>>> = BTreeMap::new();
    for e in &edges {
        let facet = if e.relation == "addresses" {
            "addressed"
        } else {
            e.facet.as_str()
        };
        concepts
            .entry(facet.to_owned())
            .or_default()
            .entry(e.concept.clone())
            .or_default()
            .insert(e.paper.clone());
    }
    let papers_of = |facet: &str, concept: &str| -> BTreeSet<String> {
        concepts
            .get(facet)
            .and_then(|m| m.get(concept))
            .cloned()
            .unwrap_or_default()
    };
    let issues_of = |ps: &BTreeSet<String>| -> BTreeSet<String> {
        concepts
            .get("issue")
            .map(|m| {
                m.iter()
                    .filter(|(_, v)| v.iter().any(|p| ps.contains(p)))
                    .map(|(k, _)| k.clone())
                    .collect()
            })
            .unwrap_or_default()
    };
    let item_by_id: BTreeMap<&str, &Item> = items.iter().map(|i| (i.id.as_str(), i)).collect();

    let mut candidates: Vec<Candidate> = Vec::new();
    let mut push = |rule: &str,
                    statement: String,
                    cs: Vec<String>,
                    ps: &BTreeSet<String>,
                    evidence: Vec<Evidence>,
                    reason: &str,
                    detail: String| {
        let n = candidates.len() + 1;
        candidates.push(Candidate {
            id: format!("C{n}"),
            rule: rule.to_owned(),
            statement,
            concepts: cs,
            papers: ps.iter().cloned().collect(),
            evidence,
            status: if reason.is_empty() {
                "kept".into()
            } else {
                "filtered".into()
            },
            reason: reason.to_owned(),
            detail,
        });
    };

    // G1
    if let Some(issue_map) = concepts.get("issue") {
        for (x, stating) in issue_map {
            let evidence: Vec<Evidence> = tags
                .iter()
                .filter(|t| {
                    t.facet == "issue"
                        && &t.concept == x
                        && (t.field == "limitation" || t.field == "future_work")
                })
                .filter_map(|t| item_by_id.get(t.subject.as_str()))
                .map(|i| Evidence {
                    paper: i.paper.clone(),
                    via: i.id.clone(),
                    section: i.section.clone(),
                    text: if i.quote.is_empty() {
                        i.text.clone()
                    } else {
                        i.quote.clone()
                    },
                    verified: i.found.verified(),
                })
                .collect();
            let verified = evidence.iter().filter(|e| e.verified).count();
            let addressed: BTreeSet<String> = papers_of("addressed", x)
                .difference(stating)
                .cloned()
                .collect();
            let statement = format!(
                "Among the papers read, the issue **{x}** is stated as a limitation or future work by {} papers ({}), and no other paper read addresses it.",
                stating.len(),
                ids(stating)
            );
            let (reason, detail) = if stating.len() < settings.rules.min_papers_g1 {
                (
                    "g1_one_paper",
                    format!(
                        "stated by {} paper(s) only; G1 needs {}",
                        stating.len(),
                        settings.rules.min_papers_g1
                    ),
                )
            } else if verified < settings.rules.min_verified_g1 {
                (
                    "g1_unverified",
                    format!(
                        "{verified} verified quotation(s); G1 needs {}",
                        settings.rules.min_verified_g1
                    ),
                )
            } else if !addressed.is_empty() {
                let how: Vec<String> = tags
                    .iter()
                    .filter(|t| {
                        t.facet == "issue"
                            && &t.concept == x
                            && addressed.contains(&t.paper)
                            && !t.subject.contains('-')
                    })
                    .map(|t| format!("{} ({} mentions `{}`)", t.paper, t.field, t.term))
                    .collect();
                (
                    "g1_addressed",
                    format!("addressed in R by {}", how.join("; ")),
                )
            } else {
                ("", String::new())
            };
            push(
                "G1",
                statement,
                vec![x.clone()],
                stating,
                evidence,
                reason,
                detail,
            );
        }
    }

    // G2
    let negative = regexes(&topic.conflict.negative);
    let positive = regexes(&topic.conflict.positive);
    let mut conflicts = Vec::new();
    let settings_of = |p: &str| -> Vec<String> {
        concepts
            .get("setting")
            .map(|m| {
                m.iter()
                    .filter(|(_, v)| v.contains(p))
                    .map(|(k, _)| k.clone())
                    .collect()
            })
            .unwrap_or_default()
    };
    let mut negatives: Vec<(String, Claim)> = Vec::new();
    let mut positives: Vec<(String, Claim)> = Vec::new();
    for (pid, rec) in &parsed {
        let mut texts: Vec<(String, String)> = vec![
            (format!("{pid}:problem"), rec.problem.clone()),
            (format!("{pid}:result"), rec.result.clone()),
        ];
        for i in items
            .iter()
            .filter(|i| &i.paper == pid && i.kind == "limitation")
        {
            texts.push((i.id.clone(), format!("{} {}", i.text, i.quote)));
        }
        // the paper's own words in its abstract and introduction, joined across line breaks
        if let Some(paper) = papers.iter().find(|p| &p.id == pid) {
            let secs = sections::split(&paper.text);
            for name in ["abstract", "introduction"] {
                let joined = sections::text_of(&paper.text, &secs, name)
                    .replace("-\n", "")
                    .split_whitespace()
                    .collect::<Vec<_>>()
                    .join(" ");
                if !joined.is_empty() {
                    texts.push((format!("{pid}:{name}"), joined));
                }
            }
        }
        for (via, text) in &texts {
            for sentence in sentences(text) {
                if sentence.len() > 400 {
                    continue;
                }
                if let Some((cue, _)) = negative.iter().find(|(_, r)| r.is_match(&sentence)) {
                    for (c, _) in method.tag(&sentence) {
                        negatives.push((
                            c,
                            Claim {
                                paper: pid.clone(),
                                via: via.clone(),
                                sentence: sentence.clone(),
                                cue: cue.clone(),
                            },
                        ));
                    }
                }
            }
        }
        if let Some((cue, _)) = positive.iter().find(|(_, r)| r.is_match(&rec.result)) {
            for t in tags
                .iter()
                .filter(|t| &t.paper == pid && t.facet == "method" && t.field == "method")
            {
                positives.push((
                    t.concept.clone(),
                    Claim {
                        paper: pid.clone(),
                        via: format!("{pid}:result"),
                        sentence: rec.result.clone(),
                        cue: cue.clone(),
                    },
                ));
            }
        }
    }
    positives.dedup();
    for (c, neg) in &negatives {
        for (c2, pos) in &positives {
            if c != c2 || neg.paper == pos.paper {
                continue;
            }
            // one pair per (method, p, q): the same claim may be in the problem field and in an item
            if conflicts.iter().any(|k: &Conflict| {
                &k.method == c && k.negative.paper == neg.paper && k.positive.paper == pos.paper
            }) {
                continue;
            }
            let sn = settings_of(&neg.paper);
            let sp = settings_of(&pos.paper);
            let shared: Vec<&String> = sn.iter().filter(|s| sp.contains(s)).collect();
            let own_positive = positives
                .iter()
                .any(|(c3, p)| c3 == c && p.paper == neg.paper);
            let (explained, explanation) = if sn.is_empty() {
                (
                    true,
                    format!(
                        "(c) the setting of {} is unknown, so the claims cannot be compared",
                        neg.paper
                    ),
                )
            } else if own_positive {
                (
                    true,
                    format!(
                        "(b) {} itself reports {c} working, so its negative sentence is about another configuration",
                        neg.paper
                    ),
                )
            } else if shared.is_empty() {
                (
                    true,
                    format!(
                        "(a) different settings: {} on {}, {} on {}",
                        neg.paper,
                        sn.join(", "),
                        pos.paper,
                        sp.join(", ")
                    ),
                )
            } else {
                (
                    false,
                    format!(
                        "not explained: both on {}",
                        shared
                            .iter()
                            .map(|s| s.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    ),
                )
            };
            conflicts.push(Conflict {
                method: c.clone(),
                negative: neg.clone(),
                positive: pos.clone(),
                settings_negative: sn,
                settings_positive: sp,
                explained,
                explanation,
            });
        }
    }
    let mut by_method: BTreeMap<String, Vec<&Conflict>> = BTreeMap::new();
    for k in &conflicts {
        by_method.entry(k.method.clone()).or_default().push(k);
    }
    for (c, pairs) in &by_method {
        let open: Vec<&&Conflict> = pairs.iter().filter(|k| !k.explained).collect();
        let ps: BTreeSet<String> = (if open.is_empty() {
            pairs.iter().collect::<Vec<_>>()
        } else {
            open.clone()
        })
        .iter()
        .flat_map(|k| [k.negative.paper.clone(), k.positive.paper.clone()])
        .collect();
        let evidence: Vec<Evidence> = (if open.is_empty() {
            pairs.iter().collect::<Vec<_>>()
        } else {
            open.clone()
        })
        .iter()
        .flat_map(|k| {
            [&k.negative, &k.positive].map(|cl| {
                let item = item_by_id.get(cl.via.as_str());
                // a sentence read from the abstract or introduction is the paper's own words
                let read = cl
                    .via
                    .rsplit_once(':')
                    .map(|(_, s)| s)
                    .filter(|s| ["abstract", "introduction"].contains(s));
                Evidence {
                    paper: cl.paper.clone(),
                    via: cl.via.clone(),
                    section: read.map_or_else(
                        || item.map_or("field".to_owned(), |i| i.section.clone()),
                        str::to_owned,
                    ),
                    text: cl.sentence.clone(),
                    verified: read.is_some() || item.is_some_and(|i| i.found.verified()),
                }
            })
        })
        .collect();
        let neg: BTreeSet<String> = open.iter().map(|k| k.negative.paper.clone()).collect();
        let pos: BTreeSet<String> = open.iter().map(|k| k.positive.paper.clone()).collect();
        let statement = format!(
            "Among the papers read, {} say {c} does not work or is not feasible, while {} report it working in the same setting class; no paper read compares them under the same conditions.",
            ids(&neg),
            ids(&pos)
        );
        let (reason, detail) = if open.is_empty() {
            (
                "g2_explained",
                pairs
                    .iter()
                    .map(|k| {
                        format!(
                            "{} vs {}: {}",
                            k.negative.paper, k.positive.paper, k.explanation
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("; "),
            )
        } else {
            ("", String::new())
        };
        push(
            "G2",
            statement,
            vec![c.clone()],
            &ps,
            evidence,
            reason,
            detail,
        );
    }

    // G3
    let empty = BTreeMap::new();
    let methods = concepts.get("method").unwrap_or(&empty).clone();
    let settings_map = concepts.get("setting").unwrap_or(&empty).clone();
    for (m, mp) in &methods {
        for (s, sp) in &settings_map {
            if mp.intersection(sp).next().is_some() {
                continue;
            }
            let common: BTreeSet<String> = issues_of(mp)
                .intersection(&issues_of(sp))
                .cloned()
                .collect();
            let all: BTreeSet<String> = mp.union(sp).cloned().collect();
            let evidence: Vec<Evidence> = tags
                .iter()
                .filter(|t| {
                    (t.facet == "method" && &t.concept == m)
                        || (t.facet == "setting" && &t.concept == s)
                })
                .map(|t| Evidence {
                    paper: t.paper.clone(),
                    via: t.subject.clone(),
                    section: t.field.clone(),
                    text: format!("{} `{}`", t.concept, t.term),
                    verified: false,
                })
                .collect();
            let statement = format!(
                "Among the papers read, {m} ({}) and {s} ({}) both occur, but no paper read uses {m} on {s}{}.",
                ids(mp),
                ids(sp),
                if common.is_empty() {
                    String::new()
                } else {
                    format!("; both groups state the issue {}", ids(&common))
                }
            );
            let (reason, detail) = if settings.rules.g3_needs_common_issue && common.is_empty() {
                (
                    "g3_no_common_issue",
                    "the papers of the method and the papers of the setting state no common issue"
                        .to_owned(),
                )
            } else {
                ("", String::new())
            };
            let mut cs = vec![m.clone(), s.clone()];
            cs.extend(common);
            push("G3", statement, cs, &all, evidence, reason, detail);
        }
    }

    // G4
    for (m, mp) in &methods {
        if mp.len() == 1 {
            let evidence = tags
                .iter()
                .filter(|t| t.facet == "method" && &t.concept == m)
                .map(|t| Evidence {
                    paper: t.paper.clone(),
                    via: t.subject.clone(),
                    section: t.field.clone(),
                    text: format!("{} `{}`", t.concept, t.term),
                    verified: false,
                })
                .collect();
            push(
                "G4",
                format!(
                    "Among the papers read, the evidence for {m} comes from one paper only ({}); it is not repeated on another setting.",
                    ids(mp)
                ),
                vec![m.clone()],
                mp,
                evidence,
                "",
                String::new(),
            );
        }
    }

    // ranking
    let w = settings.weights;
    let mut ranking: Vec<Ranked> = candidates
        .iter()
        .filter(|c| c.status == "kept")
        .map(|c| {
            let papers = c.papers.len();
            let primary = c.rule == "G1" || c.rule == "G2";
            let verified = c.evidence.iter().filter(|e| e.verified).count();
            let single = papers == 1;
            let parts = [
                w.w1 * papers as f64,
                if primary { w.w2 } else { 0.0 },
                w.w3 * verified as f64,
                if single { -w.w4 } else { 0.0 },
            ];
            Ranked {
                rank: 0,
                gap: String::new(),
                candidate: c.id.clone(),
                rule: c.rule.clone(),
                papers,
                primary,
                verified,
                single,
                parts,
                score: crate::text::round4(parts.iter().sum()),
            }
        })
        .collect();
    ranking.sort_by(|a, b| {
        b.score
            .total_cmp(&a.score)
            .then_with(|| a.rule.cmp(&b.rule))
            .then_with(|| a.candidate.cmp(&b.candidate))
    });
    for (i, r) in ranking.iter_mut().enumerate() {
        r.rank = i + 1;
        r.gap = format!("KT{}", i + 1);
    }

    let mut counts = Counts {
        papers: papers.len(),
        papers_parsed: parsed.len(),
        items: items.len(),
        quotes: items.iter().filter(|i| i.found != Found::NoQuote).count(),
        quotes_verbatim: items.iter().filter(|i| i.found == Found::Verbatim).count(),
        quotes_normalized: items
            .iter()
            .filter(|i| i.found == Found::Normalized)
            .count(),
        quotes_missing: items.iter().filter(|i| i.found == Found::Missing).count(),
        tags: tags.len(),
        item_tags: tags.iter().filter(|t| t.subject.contains('-')).count(),
        edges: edges.len(),
        concepts: concepts
            .iter()
            .filter(|(f, _)| *f != "addressed")
            .map(|(_, m)| m.len())
            .sum(),
        conflict_pairs: conflicts.len(),
        conflict_pairs_explained: conflicts.iter().filter(|k| k.explained).count(),
        rules: BTreeMap::new(),
    };
    for rule in ["G1", "G2", "G3", "G4"] {
        let mut rc = RuleCount::default();
        for c in candidates.iter().filter(|c| c.rule == rule) {
            rc.generated += 1;
            if c.status == "kept" {
                rc.kept += 1;
            } else {
                *rc.filtered.entry(c.reason.clone()).or_default() += 1;
            }
        }
        counts.rules.insert(rule.to_owned(), rc);
    }
    Analysis {
        policy_version: settings.version.clone(),
        topic: topic.id.clone(),
        weights: settings.weights,
        rules: settings.rules.clone(),
        papers: statuses,
        items,
        tags,
        edges,
        concepts: concepts
            .into_iter()
            .map(|(f, m)| {
                (
                    f,
                    m.into_iter()
                        .map(|(c, s)| (c, s.into_iter().collect()))
                        .collect(),
                )
            })
            .collect(),
        conflicts,
        candidates,
        ranking,
        counts,
    }
}

/// Reads an [`Analysis`] back from the JSON a run wrote.
pub fn from_json(value: &serde_json::Value) -> Result<Analysis, String> {
    serde_json::from_value(value.clone()).map_err(|e| format!("analysis.json: {e}"))
}
