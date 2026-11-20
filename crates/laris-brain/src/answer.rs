//! Answer assembly from accepted Claims (SR-K4, ADR-024 section 6).
//!
//! The answer is built from stored notes, never from the advisor's text: [`compose`] picks accepted Claims (level
//! `sourced` or above, Source not retracted), puts a note id and the level on every sentence and presents open
//! Conflicts as conflicts. The advisor may [`Rephraser::rephrase`] a sentence; the rephrasing is kept only if the
//! outside-set check ([`check_sentence`]) passes, else the Claim's own wording stays. A [`Judge`] may veto a
//! rephrasing, never approve one.
//!
//! [`verify_answer`] checks a whole answer again from the notes, so a sentence inserted into an answer afterwards
//! (without a Claim, with a made-up id, or with words the cited Claims do not hold) is found.
//!
//! The check is a filter, not a proof. It compares vocabulary: numbers, negation, hedges, capitalised names, opposite
//! words and the share of content words found in the cited Claims. It cannot see a rearrangement that keeps every word
//! (`tests/answer.rs` measures this on a fixture, and the report states the miss rate).

use std::collections::BTreeSet;

use laris_retrieval::NoteSearch;
use laris_vault::brain::Level;
use laris_vault::index::VaultIndex;
use laris_vault::note::{Note, link_name};

use crate::text::{self, Facts};

/// The only system statement an answer may carry besides questions: the abstention.
pub const ABSTENTION: &str =
    "No accepted claim answers this question: the brain holds nothing that supports an answer.";

/// Words the composer and a rephrasing may add around Claim content.
pub const FRAME_WORDS: [&str; 24] = [
    "according",
    "sources",
    "source",
    "disagree",
    "but",
    "while",
    "whereas",
    "however",
    "also",
    "reports",
    "reported",
    "report",
    "states",
    "stated",
    "says",
    "said",
    "argues",
    "claims",
    "claim",
    "level",
    "evidence",
    "accepted",
    "conflict",
    "theory",
];

/// Settings of assembly, filled by the caller; there is no default.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AnswerSettings {
    /// Share of a sentence's content words that must occur in the Claims it cites (0 to 1).
    pub min_cover: f64,
    /// The lowest level a Claim may have to be used.
    pub min_level: Level,
    /// The most Claims and Theories in one answer.
    pub max_notes: usize,
}

/// What a sentence stands for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SentenceKind {
    /// A Claim's statement.
    Claim,
    /// An attributed position.
    Theory,
    /// A disagreement between stored notes, presented as one.
    Conflict,
    /// The abstention.
    System,
}

/// One sentence of an answer with the notes it rests on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sentence {
    /// What it stands for.
    pub kind: SentenceKind,
    /// The prose, without note ids.
    pub body: String,
    /// Titles of the notes it cites: the Claim or Theory, or both sides of a Conflict followed by the Conflict.
    pub cites: Vec<String>,
}

/// An answer.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Answer {
    /// The sentences in order.
    pub sentences: Vec<Sentence>,
}

impl Answer {
    /// True when the answer is the abstention.
    pub fn abstained(&self) -> bool {
        self.sentences.len() == 1 && self.sentences[0].kind == SentenceKind::System
    }

    /// The answer as text: every sentence with its note ids and, for a Claim, its level.
    pub fn render(&self, index: &VaultIndex) -> String {
        let mut lines = Vec::new();
        for s in &self.sentences {
            let ids: Vec<String> = s.cites.iter().map(|c| format!("[[{c}]]")).collect();
            let level = match s.kind {
                SentenceKind::Claim => s
                    .cites
                    .first()
                    .and_then(|c| index.find(&link_name(c)))
                    .map(|n| format!(" (level: {})", prop(n, "level"))),
                _ => None,
            };
            lines.push(if ids.is_empty() {
                s.body.clone()
            } else {
                format!("{} {}{}", s.body, ids.join(" "), level.unwrap_or_default())
            });
        }
        lines.join("\n")
    }
}

/// Wording help from the advisor. It sees one sentence and the statements it rests on and may only return wording.
pub trait Rephraser {
    /// A rewording of `body`, given the statements of the notes it cites.
    fn rephrase(&self, body: &str, cited: &[String]) -> Result<String, String>;
}

/// A second opinion that can only say no.
pub trait Judge {
    /// True to refuse the rephrasing.
    fn veto(&self, rephrased: &str, cited: &[String]) -> bool;
}

/// Why the Claim's own wording stayed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Replacement {
    /// Index of the sentence.
    pub sentence: usize,
    /// What failed.
    pub reason: String,
}

/// An answer with what assembly did to the advisor's wording.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Assembled {
    /// The answer.
    pub answer: Answer,
    /// Rephrasings that were refused, with the reason.
    pub replaced: Vec<Replacement>,
}

fn prop(note: &Note, name: &str) -> String {
    note.prop(name).map_or(String::new(), |v| v.py_str())
}

fn kind_of(note: &Note) -> String {
    prop(note, "type")
}

/// Whether a Claim or Theory may be used in an answer: its level is high enough and its Source is active.
fn accepted(index: &VaultIndex, note: &Note, settings: &AnswerSettings) -> bool {
    let source = index.find(&link_name(&prop(note, "source_ref")));
    let usable =
        source.is_some_and(|s| matches!(prop(s, "status").as_str(), "active" | "superseded"));
    match kind_of(note).as_str() {
        "claim" => {
            usable
                && Level::parse(&prop(note, "level"))
                    .is_some_and(|l| l >= settings.min_level.max(Level::Sourced))
        }
        "theory" => usable,
        _ => false,
    }
}

fn theory_body(note: &Note) -> String {
    format!(
        "According to {}, {}",
        prop(note, "attributed_to"),
        note.body.trim()
    )
}

fn conflict_body(index: &VaultIndex, sides: &[&Note]) -> String {
    let parts: Vec<String> = sides
        .iter()
        .map(|n| {
            let text = n.body.trim().trim_end_matches('.').to_string();
            if kind_of(n) == "theory" {
                theory_body(n).trim_end_matches('.').to_string()
            } else {
                text
            }
        })
        .collect();
    let _ = index;
    format!("The sources disagree: {}.", parts.join("; but "))
}

/// The open Conflicts that touch `notes`, with their sides, in title order.
fn conflicts_of<'a>(index: &'a VaultIndex, notes: &[&Note]) -> Vec<(&'a Note, Vec<&'a Note>)> {
    let wanted: BTreeSet<String> = notes.iter().map(|n| n.title.clone()).collect();
    let mut out = Vec::new();
    for conflict in index
        .notes
        .values()
        .filter(|n| kind_of(n) == "conflict" && prop(n, "status") == "open")
    {
        let sides: Vec<&Note> = conflict
            .prop_list("sides")
            .iter()
            .filter_map(|v| index.find(&link_name(v)))
            .collect();
        if sides.iter().any(|s| wanted.contains(&s.title)) {
            out.push((conflict, sides));
        }
    }
    out
}

/// Build an answer for `question` from the accepted Claims and Theories that match it. Nothing matching gives the
/// abstention. Every used Claim carries its note id and level; every open Conflict that touches a used note is stated.
pub fn compose(index: &VaultIndex, question: &str, settings: &AnswerSettings) -> Answer {
    let folders = ["Claims".to_string(), "Theories".to_string()];
    let search = NoteSearch::new(index, &folders);
    // stop words match every note and would answer anything
    let query = text::facts(question)
        .content
        .into_iter()
        .collect::<Vec<_>>()
        .join(" ");
    let used: Vec<&Note> = search
        .search(
            &query,
            settings.max_notes.saturating_mul(4).max(settings.max_notes),
        )
        .into_iter()
        .filter_map(|h| index.notes.get(&h.path))
        .filter(|n| accepted(index, n, settings))
        .take(settings.max_notes)
        .collect();
    if used.is_empty() {
        return Answer {
            sentences: vec![Sentence {
                kind: SentenceKind::System,
                body: ABSTENTION.to_string(),
                cites: vec![],
            }],
        };
    }
    let mut sentences = Vec::new();
    for note in &used {
        if kind_of(note) == "theory" {
            sentences.push(Sentence {
                kind: SentenceKind::Theory,
                body: theory_body(note),
                cites: vec![note.title.clone()],
            });
        } else {
            sentences.push(Sentence {
                kind: SentenceKind::Claim,
                body: note.body.trim().to_string(),
                cites: vec![note.title.clone()],
            });
        }
    }
    for (conflict, sides) in conflicts_of(index, &used) {
        if sides.iter().all(|s| accepted(index, s, settings)) && sides.len() >= 2 {
            let mut cites: Vec<String> = sides.iter().map(|s| s.title.clone()).collect();
            cites.push(conflict.title.clone());
            sentences.push(Sentence {
                kind: SentenceKind::Conflict,
                body: conflict_body(index, &sides),
                cites,
            });
        }
    }
    Answer { sentences }
}

/// The statements a sentence rests on (the Claim or Theory notes among its cites).
fn cited_notes<'a>(index: &'a VaultIndex, s: &Sentence) -> Result<Vec<&'a Note>, String> {
    let mut out = Vec::new();
    for title in &s.cites {
        let Some(note) = index.find(&link_name(title)) else {
            return Err(format!("{title} is not a note of the brain"));
        };
        out.push(note);
    }
    Ok(out)
}

fn merged(notes: &[&Note]) -> Facts {
    let mut out = Facts::default();
    let mut negations = BTreeSet::new();
    for n in notes {
        let text = if kind_of(n) == "theory" {
            format!("{} {}", prop(n, "attributed_to"), n.body)
        } else {
            n.body.clone()
        };
        let f = text::facts(&text);
        out.quantities.extend(f.quantities.clone());
        out.content.extend(f.content.clone());
        out.all.extend(f.all.clone());
        out.hedges.extend(f.hedges.clone());
        negations.insert(f.negated);
    }
    // `negated` is only meaningful per note; callers read it through `polarities`
    out.negated = negations.len() == 1 && negations.contains(&true);
    out
}

fn polarities(notes: &[&Note]) -> BTreeSet<bool> {
    notes.iter().map(|n| text::facts(&n.body).negated).collect()
}

/// The outside-set check of ADR-024 6.3 for one Claim or Theory sentence: it must cite accepted notes, and every
/// number, name, negation and hedge in it must occur in them, with no opposite word and enough shared content.
pub fn check_sentence(
    index: &VaultIndex,
    s: &Sentence,
    settings: &AnswerSettings,
) -> Result<(), String> {
    if s.cites.is_empty() {
        return Err("the sentence cites no note".into());
    }
    let notes = cited_notes(index, s)?;
    for n in &notes {
        if !matches!(kind_of(n).as_str(), "claim" | "theory") {
            return Err(format!(
                "{} is a {}, not a claim or theory",
                n.title,
                kind_of(n)
            ));
        }
        if !accepted(index, n, settings) {
            return Err(format!("{} is not an accepted note", n.title));
        }
    }
    let cited = merged(&notes);
    let said = text::facts(&s.body);
    if let Some(q) = said
        .quantities
        .iter()
        .find(|q| !cited.quantities.iter().any(|c| c.value == q.value))
    {
        return Err(format!("the number {} is not in the cited notes", q.value));
    }
    if !polarities(&notes).contains(&said.negated) {
        return Err("the sentence flips the polarity of the cited notes".into());
    }
    if let Some(h) = said.hedges.difference(&cited.hedges).next() {
        return Err(format!("the sentence adds the quantifier or hedge `{h}`"));
    }
    if let Some(h) = cited.hedges.difference(&said.hedges).next() {
        return Err(format!("the sentence drops the quantifier or hedge `{h}`"));
    }
    if let Some(w) = said.all.iter().find(|w| {
        !cited.all.contains(*w)
            && text::OPPOSITES.iter().any(|&(x, y)| {
                (w.as_str() == x && cited.all.contains(y))
                    || (w.as_str() == y && cited.all.contains(x))
            })
    }) {
        return Err(format!(
            "the sentence uses the opposite of a cited word (`{w}`)"
        ));
    }
    for word in s.body.split(|c: char| !c.is_alphanumeric()) {
        let lower = word.to_lowercase();
        if word.chars().next().is_some_and(char::is_uppercase)
            && !text::STOP_WORDS.contains(&lower.as_str())
            && !FRAME_WORDS.contains(&lower.as_str())
            && !cited.all.contains(&lower)
        {
            return Err(format!("the name `{word}` is not in the cited notes"));
        }
    }
    let own: Vec<&String> = said
        .content
        .iter()
        .filter(|w| !FRAME_WORDS.contains(&w.as_str()))
        .collect();
    if own.is_empty() {
        return Err("the sentence has no content".into());
    }
    let share =
        own.iter().filter(|w| cited.content.contains(**w)).count() as f64 / own.len() as f64;
    if share < settings.min_cover {
        return Err(format!(
            "only {:.0} % of the content words are in the cited notes",
            share * 100.0
        ));
    }
    Ok(())
}

/// Check a whole answer against the notes: the problems found, each with the index of its sentence. An empty list means
/// every sentence is mapped to accepted notes and passes the check.
pub fn verify_answer(
    index: &VaultIndex,
    answer: &Answer,
    settings: &AnswerSettings,
) -> Vec<(usize, String)> {
    let mut problems = Vec::new();
    for (i, s) in answer.sentences.iter().enumerate() {
        let outcome = match s.kind {
            SentenceKind::System => {
                if s.body == ABSTENTION && s.cites.is_empty() {
                    Ok(())
                } else {
                    Err("a system sentence may only be the abstention".to_string())
                }
            }
            SentenceKind::Claim | SentenceKind::Theory => check_sentence(index, s, settings),
            SentenceKind::Conflict => check_conflict(index, s, settings),
        };
        if let Err(why) = outcome {
            problems.push((i, why));
        }
    }
    problems
}

fn check_conflict(
    index: &VaultIndex,
    s: &Sentence,
    settings: &AnswerSettings,
) -> Result<(), String> {
    let notes = cited_notes(index, s)?;
    let Some((conflict, sides)) = notes.split_last() else {
        return Err("a conflict sentence cites its sides and the conflict".into());
    };
    if kind_of(conflict) != "conflict" || sides.len() < 2 {
        return Err("a conflict sentence cites two sides and the conflict".into());
    }
    if sides.iter().any(|n| !accepted(index, n, settings)) {
        return Err("a side of the conflict is not an accepted note".into());
    }
    let titles: BTreeSet<String> = sides.iter().map(|n| n.title.clone()).collect();
    let stored: BTreeSet<String> = conflict
        .prop_list("sides")
        .iter()
        .filter_map(|v| index.find(&link_name(v)))
        .map(|n| n.title.clone())
        .collect();
    if titles != stored {
        return Err("the sentence does not present every side of the conflict".into());
    }
    if s.body != conflict_body(index, sides) {
        return Err("the conflict is not stated in the notes' own words".into());
    }
    Ok(())
}

/// Compose, then offer each Claim and Theory sentence to the advisor for rewording. A rewording is used only if the
/// advisor produced one, the outside-set check passes and the judge (if any) does not veto; otherwise the notes' own
/// wording stays and the reason is reported. The result always passes [`verify_answer`].
pub fn assemble(
    index: &VaultIndex,
    question: &str,
    settings: &AnswerSettings,
    rephraser: &dyn Rephraser,
    judge: Option<&dyn Judge>,
) -> Assembled {
    let mut answer = compose(index, question, settings);
    let mut replaced = Vec::new();
    for (i, s) in answer.sentences.iter_mut().enumerate() {
        if !matches!(s.kind, SentenceKind::Claim | SentenceKind::Theory) {
            continue;
        }
        let Ok(notes) = cited_notes(index, s) else {
            continue;
        };
        let statements: Vec<String> = notes.iter().map(|n| n.body.trim().to_string()).collect();
        let candidate = match rephraser.rephrase(&s.body, &statements) {
            Ok(text) => text,
            Err(e) => {
                replaced.push(Replacement {
                    sentence: i,
                    reason: format!("the advisor failed: {e}"),
                });
                continue;
            }
        };
        let trial = Sentence {
            kind: s.kind,
            body: candidate.trim().to_string(),
            cites: s.cites.clone(),
        };
        if let Err(why) = check_sentence(index, &trial, settings) {
            replaced.push(Replacement {
                sentence: i,
                reason: why,
            });
        } else if judge.is_some_and(|j| j.veto(&trial.body, &statements)) {
            replaced.push(Replacement {
                sentence: i,
                reason: "the judge vetoed the rewording".into(),
            });
        } else {
            s.body = trial.body;
        }
    }
    Assembled { answer, replaced }
}
