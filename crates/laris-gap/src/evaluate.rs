//! Evaluation against people's judgements: extraction precision and recall against a gold standard, the precision
//! of concept tagging from a person's verdicts, expert ratings of gaps, and the time-split check.
//!
//! # Matching an extracted item to a gold item
//!
//! The score of a pair is the larger of (a) the token F1 of the two quotations and (b) the token F1 of the two
//! paraphrases, over normalised words longer than two characters. Pairs of the same paper are matched greedily from
//! the best score down, each item at most once, while the score is at least the threshold. Precision is matched
//! system items over system items; recall is matched gold items over gold items. Every pair and its score is kept,
//! so a person can overrule a match.

use crate::analyze::{Analysis, Item};
use crate::text::{round4, token_f1};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// One gold item.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GoldItem {
    /// Id within its paper.
    pub id: String,
    /// `limitation` or `future_work`.
    pub kind: String,
    /// Paraphrase.
    pub text: String,
    /// Quotation.
    pub quote: String,
    /// Section.
    #[serde(default)]
    pub section: String,
}

/// A matched pair.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Match {
    /// Paper id of the run.
    pub paper: String,
    /// System item id.
    pub system: String,
    /// Gold item id.
    pub gold: String,
    /// Pair score.
    pub score: f64,
}

/// Precision and recall of one paper or of all.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Pr {
    /// System items.
    pub system: usize,
    /// Gold items.
    pub gold: usize,
    /// Matched pairs.
    pub matched: usize,
    /// Precision.
    pub precision: f64,
    /// Recall.
    pub recall: f64,
    /// F1.
    pub f1: f64,
}

impl Pr {
    fn of(system: usize, gold: usize, matched: usize) -> Pr {
        let p = if system == 0 {
            0.0
        } else {
            matched as f64 / system as f64
        };
        let r = if gold == 0 {
            0.0
        } else {
            matched as f64 / gold as f64
        };
        let f = if p + r == 0.0 {
            0.0
        } else {
            2.0 * p * r / (p + r)
        };
        Pr {
            system,
            gold,
            matched,
            precision: round4(p),
            recall: round4(r),
            f1: round4(f),
        }
    }
}

/// The extraction evaluation.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ExtractionEval {
    /// Threshold used.
    pub threshold: f64,
    /// Per paper.
    pub papers: BTreeMap<String, Pr>,
    /// Over all papers.
    pub total: Pr,
    /// Per kind over all papers (`limitation`, `future_work`), matching within the same kind.
    pub by_kind: BTreeMap<String, Pr>,
    /// Matched pairs.
    pub matches: Vec<Match>,
    /// Gold items no system item matched, as `paper:gold id`.
    pub missed: Vec<String>,
    /// System items that matched no gold item.
    pub extra: Vec<String>,
}

fn pair_score(s: &Item, g: &GoldItem) -> f64 {
    token_f1(&s.quote, &g.quote).max(token_f1(&s.text, &g.text))
}

/// Evaluates the items of `analysis` against `gold` (run paper id → gold items).
pub fn extraction(
    analysis: &Analysis,
    gold: &BTreeMap<String, Vec<GoldItem>>,
    threshold: f64,
) -> ExtractionEval {
    let mut papers = BTreeMap::new();
    let mut matches = Vec::new();
    let mut missed = Vec::new();
    let mut extra = Vec::new();
    let (mut ts, mut tg, mut tm) = (0, 0, 0);
    let mut kinds: BTreeMap<String, (usize, usize, usize)> = BTreeMap::new();
    for (pid, gitems) in gold {
        let sitems: Vec<&Item> = analysis.items.iter().filter(|i| &i.paper == pid).collect();
        let mut pairs: Vec<(f64, usize, usize)> = Vec::new();
        for (a, s) in sitems.iter().enumerate() {
            for (b, g) in gitems.iter().enumerate() {
                let sc = pair_score(s, g);
                if sc >= threshold {
                    pairs.push((sc, a, b));
                }
            }
        }
        pairs.sort_by(|x, y| y.0.total_cmp(&x.0).then(x.1.cmp(&y.1)).then(x.2.cmp(&y.2)));
        let (mut used_s, mut used_g) = (BTreeSet::new(), BTreeSet::new());
        for (sc, a, b) in pairs {
            if used_s.contains(&a) || used_g.contains(&b) {
                continue;
            }
            used_s.insert(a);
            used_g.insert(b);
            matches.push(Match {
                paper: pid.clone(),
                system: sitems[a].id.clone(),
                gold: gitems[b].id.clone(),
                score: round4(sc),
            });
            if sitems[a].kind == gitems[b].kind {
                kinds.entry(gitems[b].kind.clone()).or_default().2 += 1;
            }
        }
        for (b, g) in gitems.iter().enumerate() {
            kinds.entry(g.kind.clone()).or_default().1 += 1;
            if !used_g.contains(&b) {
                missed.push(format!("{pid}:{}", g.id));
            }
        }
        for (a, s) in sitems.iter().enumerate() {
            kinds.entry(s.kind.clone()).or_default().0 += 1;
            if !used_s.contains(&a) {
                extra.push(s.id.clone());
            }
        }
        papers.insert(
            pid.clone(),
            Pr::of(sitems.len(), gitems.len(), used_s.len()),
        );
        ts += sitems.len();
        tg += gitems.len();
        tm += used_s.len();
    }
    ExtractionEval {
        threshold,
        papers,
        total: Pr::of(ts, tg, tm),
        by_kind: kinds
            .into_iter()
            .map(|(k, (s, g, m))| (k, Pr::of(s, g, m)))
            .collect(),
        matches,
        missed,
        extra,
    }
}

/// A person's verdict on one concept tag.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TagVerdict {
    /// Subject of the tag (item id or `P3:method`).
    pub subject: String,
    /// Concept.
    pub concept: String,
    /// Correct.
    pub correct: bool,
}

/// Precision of concept tagging over the judged tags.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TagPrecision {
    /// Tags in the run.
    pub tags: usize,
    /// Tags judged.
    pub judged: usize,
    /// Judged correct.
    pub correct: usize,
    /// Judged wrong.
    pub wrong: usize,
    /// correct / judged.
    pub precision: f64,
    /// Per facet: (judged, correct).
    pub by_facet: BTreeMap<String, (usize, usize)>,
}

/// Concept-tag precision of `analysis` from `verdicts`.
pub fn tag_precision(analysis: &Analysis, verdicts: &[TagVerdict]) -> TagPrecision {
    let mut by_facet: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    let (mut judged, mut correct) = (0, 0);
    for t in &analysis.tags {
        if let Some(v) = verdicts
            .iter()
            .find(|v| v.subject == t.subject && v.concept == t.concept)
        {
            judged += 1;
            let e = by_facet.entry(t.facet.clone()).or_default();
            e.0 += 1;
            if v.correct {
                correct += 1;
                e.1 += 1;
            }
        }
    }
    TagPrecision {
        tags: analysis.tags.len(),
        judged,
        correct,
        wrong: judged - correct,
        precision: if judged == 0 {
            0.0
        } else {
            round4(correct as f64 / judged as f64)
        },
        by_facet,
    }
}

/// One expert rating of one gap (blind: the rater does not see the source).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Rating {
    /// Rater name or code.
    pub rater: String,
    /// Blind id of the gap on the rating sheet.
    pub item: String,
    /// 1–5: how well the gap is grounded in the papers.
    pub grounded: u8,
    /// 1–5: how valuable the gap is for research.
    pub valuable: u8,
    /// Free comment.
    #[serde(default)]
    pub comment: String,
}

/// Mean, standard deviation and distribution of one criterion for one source.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Stat {
    /// Ratings.
    pub n: usize,
    /// Mean.
    pub mean: f64,
    /// Sample standard deviation.
    pub sd: f64,
    /// Count of each score 1–5.
    pub histogram: [usize; 5],
}

fn stat(values: &[u8]) -> Stat {
    let n = values.len();
    if n == 0 {
        return Stat::default();
    }
    let mean = values.iter().map(|v| f64::from(*v)).sum::<f64>() / n as f64;
    let var = if n > 1 {
        values
            .iter()
            .map(|v| (f64::from(*v) - mean).powi(2))
            .sum::<f64>()
            / (n - 1) as f64
    } else {
        0.0
    };
    let mut histogram = [0; 5];
    for v in values {
        if (1..=5).contains(v) {
            histogram[usize::from(*v) - 1] += 1;
        }
    }
    Stat {
        n,
        mean: round4(mean),
        sd: round4(var.sqrt()),
        histogram,
    }
}

/// Aggregates ratings per source; `source_of` maps a blind item id to its source (`system`, `closed`, ...).
pub fn ratings(
    ratings: &[Rating],
    source_of: &BTreeMap<String, String>,
) -> BTreeMap<String, (Stat, Stat)> {
    let mut by: BTreeMap<String, (Vec<u8>, Vec<u8>)> = BTreeMap::new();
    for r in ratings {
        let Some(src) = source_of.get(&r.item) else {
            continue;
        };
        let e = by.entry(src.clone()).or_default();
        e.0.push(r.grounded);
        e.1.push(r.valuable);
    }
    by.into_iter()
        .map(|(k, (g, v))| (k, (stat(&g), stat(&v))))
        .collect()
}

/// One gap of the time split and the later papers that close it.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TimeCheck {
    /// Gap id of the early run.
    pub gap: String,
    /// Rule.
    pub rule: String,
    /// Statement.
    pub statement: String,
    /// Later papers that address it, with the reason.
    pub addressed_by: Vec<String>,
}

/// For every ranked gap of `early` (the papers up to the cutoff), the papers `late_ids` of `late` (the analysis of
/// all papers, so the ids are the same) published after the cutoff that
/// address it: for G1, a later paper whose problem, method or result carries the issue; for G3, a later paper that
/// uses the method on the setting; for G4, a later paper that uses the method; for G2, a later paper that uses the
/// method on a setting of the conflict.
pub fn time_split(early: &Analysis, late: &Analysis, late_ids: &[String]) -> Vec<TimeCheck> {
    let has = |facet: &str, concept: &str, paper: &str| -> bool {
        late.tags.iter().any(|t| {
            t.paper == paper && t.facet == facet && t.concept == concept && !t.subject.contains('-')
        })
    };
    let late_papers = late_ids;
    let mut out = Vec::new();
    for r in &early.ranking {
        let Some(c) = early.candidates.iter().find(|c| c.id == r.candidate) else {
            continue;
        };
        let mut by = Vec::new();
        for p in late_papers {
            let hit = match c.rule.as_str() {
                "G1" => c.concepts.first().is_some_and(|x| has("issue", x, p)),
                "G3" => {
                    c.concepts.len() >= 2
                        && has("method", &c.concepts[0], p)
                        && has("setting", &c.concepts[1], p)
                }
                "G4" => c.concepts.first().is_some_and(|m| has("method", m, p)),
                "G2" => c.concepts.first().is_some_and(|m| has("method", m, p)),
                _ => false,
            };
            if hit {
                by.push(p.clone());
            }
        }
        out.push(TimeCheck {
            gap: r.gap.clone(),
            rule: c.rule.clone(),
            statement: c.statement.clone(),
            addressed_by: by,
        });
    }
    out
}
