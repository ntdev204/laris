//! The decision dataset (SR-K6, ADR-024 section 9.1).
//!
//! An [`Example`] is `(state signals, candidate list, chosen action, outcome)` with provenance and a checksum. Two
//! origins exist and are never mixed up:
//!
//! * `log`: a decision recorded by [`crate::seam::Brain::log`] (see [`decision_line`]) joined with an outcome that the
//!   system measured ([`outcome_line`]: the gate accepted the Claim, the answer passed the outside-set check, the user
//!   did not retract). The label comes from the outcome, never from the rule decider's own choice.
//! * `scenario`: the same state replayed with every legal candidate against the scenario oracle
//!   ([`scenario_examples`]). These prove mechanics, not real-world behaviour; the manifest reports their share.
//!
//! An example written by a model, or labelled by one, is excluded ([`Excluded`]), and so is any line whose origin or
//! evidence is not one of the closed sets below. [`training_text`] draws the text that may reach ResearchLLM training
//! from the brain: Source texts and the verified quotes of Claims, never a Claim's own wording, which an advisor wrote.
//!
//! The held-out split is decided by a hash of the example group, so a group never straddles two splits, and is
//! sealed ([`write`]) before any network exists: [`verify`] finds a changed file, a changed id or a leaked group.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

use laris_vault::brain::{Level, resolve_span, sha256_hex};
use laris_vault::index::VaultIndex;
use laris_vault::note::{Note, link_name};
use serde_json::{Value, json};

use crate::answer::prop;
use crate::decide::{Act, CallState, RuleSettings, Signals, hard_limit, legal};

/// The version of the example format.
pub const SCHEMA: u32 = 1;

/// The evidence kinds an outcome may rest on. Each one is something the system measured.
pub const EVIDENCE: [&str; 9] = [
    "gate_accepted",
    "gate_refused",
    "check_passed",
    "check_failed",
    "user_retracted",
    "user_kept",
    "tool_ok",
    "tool_error",
    "scenario_oracle",
];

/// Where an example came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Origin {
    /// A recorded decision with a measured outcome.
    Log,
    /// A counterfactual from the scenario oracle.
    Scenario,
}

impl Origin {
    fn as_str(self) -> &'static str {
        match self {
            Origin::Log => "log",
            Origin::Scenario => "scenario",
        }
    }
}

/// What happened after the chosen action.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outcome {
    /// Whether the action was right: the label.
    pub good: bool,
    /// One of [`EVIDENCE`].
    pub evidence: String,
}

/// One training example.
#[derive(Debug, Clone, PartialEq)]
pub struct Example {
    /// Examples of one state share a group; a group is never split.
    pub group: String,
    /// Where it came from.
    pub origin: Origin,
    /// The advisor that made the proposals of this turn, as a categorical key.
    pub advisor: Option<String>,
    /// The state.
    pub signals: Signals,
    /// The legal actions.
    pub candidates: Vec<Act>,
    /// The action that was taken (log) or replayed (scenario).
    pub action: Act,
    /// What happened.
    pub outcome: Outcome,
    /// Where to find it again: session and sequence, or scenario and index.
    pub provenance: Value,
}

impl Example {
    /// The content that the id hashes: everything but the id and the split.
    fn content(&self) -> Value {
        json!({
            "schema": SCHEMA,
            "group": self.group,
            "origin": self.origin.as_str(),
            "advisor": self.advisor,
            "signals": self.signals.to_json(),
            "candidates": self.candidates.iter().map(|a| a.as_str()).collect::<Vec<_>>(),
            "action": self.action.as_str(),
            "outcome": {"good": self.outcome.good, "evidence": self.outcome.evidence},
            "provenance": self.provenance,
        })
    }

    /// The checksum of the content.
    pub fn id(&self) -> String {
        sha256_hex(self.content().to_string().as_bytes())
    }

    fn line(&self, split: Split) -> String {
        let mut v = self.content();
        v["id"] = json!(self.id());
        v["split"] = json!(split.as_str());
        v.to_string()
    }

    /// Reads one line written by [`Example::line`].
    fn parse(line: &str) -> Option<(Example, String, String)> {
        let v: Value = serde_json::from_str(line).ok()?;
        let candidates = v
            .get("candidates")?
            .as_array()?
            .iter()
            .map(|a| Act::parse(a.as_str()?))
            .collect::<Option<Vec<_>>>()?;
        let origin = match v.get("origin")?.as_str()? {
            "log" => Origin::Log,
            "scenario" => Origin::Scenario,
            _ => return None,
        };
        let outcome = v.get("outcome")?;
        let example = Example {
            group: v.get("group")?.as_str()?.to_owned(),
            origin,
            advisor: v.get("advisor")?.as_str().map(str::to_owned),
            signals: Signals::from_json(v.get("signals")?)?,
            candidates,
            action: Act::parse(v.get("action")?.as_str()?)?,
            outcome: Outcome {
                good: outcome.get("good")?.as_bool()?,
                evidence: outcome.get("evidence")?.as_str()?.to_owned(),
            },
            provenance: v.get("provenance")?.clone(),
        };
        Some((
            example,
            v.get("id")?.as_str()?.to_owned(),
            v.get("split")?.as_str()?.to_owned(),
        ))
    }
}

/// Why a line or an example was left out. Every exclusion is counted in the manifest.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Excluded {
    /// The line is not valid or lacks a field.
    Malformed,
    /// A model wrote the example, or its origin is not `log`.
    ModelGenerated,
    /// The outcome was judged by a model or rests on evidence outside [`EVIDENCE`].
    UnmeasuredOutcome,
    /// The chosen action is not among the candidates.
    IllegalChoice,
    /// A decision without an outcome yet.
    NoOutcome,
}

impl Excluded {
    /// The name used in the manifest.
    pub fn as_str(self) -> &'static str {
        match self {
            Excluded::Malformed => "malformed",
            Excluded::ModelGenerated => "model_generated",
            Excluded::UnmeasuredOutcome => "unmeasured_outcome",
            Excluded::IllegalChoice => "illegal_choice",
            Excluded::NoOutcome => "no_outcome",
        }
    }
}

/// The decision-log line for one choice. `seq` counts the decisions of the session.
pub fn decision_line(
    session: &str,
    seq: u64,
    advisor: Option<&str>,
    choice: &crate::decide::Choice,
) -> String {
    json!({
        "kind": "decision",
        "origin": "log",
        "session": session,
        "seq": seq,
        "advisor": advisor,
        "action": choice.act.as_str(),
        "candidates": choice.candidates.iter().map(|a| a.as_str()).collect::<Vec<_>>(),
        "rule": choice.rule,
        "signals": choice.signals.to_json(),
    })
    .to_string()
}

/// The outcome line for the decision `seq` of `session`. `evidence` is one of [`EVIDENCE`]; the judge is always the
/// system.
pub fn outcome_line(session: &str, seq: u64, good: bool, evidence: &str) -> String {
    json!({
        "kind": "outcome",
        "session": session,
        "seq": seq,
        "good": good,
        "evidence": evidence,
        "judge": "system",
    })
    .to_string()
}

/// The examples in a decision log and what was left out. `log_name` goes into the provenance together with the
/// checksum of `text`.
pub fn from_log(text: &str, log_name: &str) -> (Vec<Example>, BTreeMap<Excluded, usize>) {
    let log_sha = sha256_hex(text.as_bytes());
    let mut left_out: BTreeMap<Excluded, usize> = BTreeMap::new();
    let mut leave = |why: Excluded| *left_out.entry(why).or_insert(0) += 1;
    let mut decisions: BTreeMap<(String, u64), Value> = BTreeMap::new();
    let mut outcomes: BTreeMap<(String, u64), Value> = BTreeMap::new();
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let Ok(v) = serde_json::from_str::<Value>(line) else {
            leave(Excluded::Malformed);
            continue;
        };
        let key = match (
            v.get("session").and_then(Value::as_str),
            v.get("seq").and_then(Value::as_u64),
        ) {
            (Some(s), Some(n)) => (s.to_owned(), n),
            _ => {
                leave(Excluded::Malformed);
                continue;
            }
        };
        match v.get("kind").and_then(Value::as_str) {
            Some("decision") => {
                // only a decision the system recorded itself is data; anything else is not what it claims to be
                if v.get("origin").and_then(Value::as_str) != Some("log") {
                    leave(Excluded::ModelGenerated);
                } else {
                    decisions.insert(key, v);
                }
            }
            Some("outcome") => {
                outcomes.insert(key, v);
            }
            _ => leave(Excluded::Malformed),
        }
    }
    let mut examples = Vec::new();
    for (key, d) in decisions {
        let Some(o) = outcomes.get(&key) else {
            leave(Excluded::NoOutcome);
            continue;
        };
        let evidence = o.get("evidence").and_then(Value::as_str).unwrap_or("");
        if o.get("judge").and_then(Value::as_str) != Some("system") || !EVIDENCE.contains(&evidence)
        {
            leave(Excluded::UnmeasuredOutcome);
            continue;
        }
        let (Some(signals), Some(action), Some(good)) = (
            d.get("signals").and_then(Signals::from_json),
            d.get("action").and_then(Value::as_str).and_then(Act::parse),
            o.get("good").and_then(Value::as_bool),
        ) else {
            leave(Excluded::Malformed);
            continue;
        };
        let Some(candidates) = d.get("candidates").and_then(Value::as_array).and_then(|a| {
            a.iter()
                .map(|x| Act::parse(x.as_str()?))
                .collect::<Option<Vec<_>>>()
        }) else {
            leave(Excluded::Malformed);
            continue;
        };
        if !candidates.contains(&action) {
            leave(Excluded::IllegalChoice);
            continue;
        }
        examples.push(Example {
            group: format!("log:{}:{}", key.0, key.1),
            origin: Origin::Log,
            advisor: d.get("advisor").and_then(Value::as_str).map(str::to_owned),
            signals,
            candidates,
            action,
            outcome: Outcome {
                good,
                evidence: evidence.to_owned(),
            },
            provenance: json!({
                "log": log_name,
                "log_sha256": log_sha,
                "session": key.0,
                "seq": key.1,
            }),
        });
    }
    (examples, left_out)
}

/// What the scenario oracle says about `act` in `s`, as `(good, evidence)`. It is written from what each action is
/// for, not from the order of the rule decider.
pub fn scenario_outcome(s: &Signals, act: Act, cfg: &RuleSettings) -> Outcome {
    let blocked_by_limit = hard_limit(s, cfg).is_some();
    let covered = s.accepted > 0
        && s.coverage >= cfg.min_coverage
        && s.best_level.is_some_and(|l| l >= cfg.required_level);
    let options = legal(s, cfg);
    let can_get_evidence = [Act::Verify, Act::Acquire, Act::AskAdvisor, Act::RunTool]
        .iter()
        .any(|a| options.contains(a))
        || (s.fresh_since_retrieve && options.contains(&Act::Retrieve));
    let open = !blocked_by_limit && s.missing_slot.is_none();
    let good = match act {
        Act::Stop => blocked_by_limit,
        Act::AskUser => !blocked_by_limit && s.missing_slot.is_some(),
        Act::Answer => open && covered,
        Act::Abstain => open && !covered && !can_get_evidence,
        Act::Verify => open && !covered && (s.pending_candidates > 0 || s.below_required > 0),
        Act::Retrieve => open && !covered && s.fresh_since_retrieve,
        Act::Acquire => open && !covered,
        Act::RunTool => open && !covered && s.call == CallState::Legal,
        Act::AskAdvisor => open && !covered && s.call != CallState::Legal,
    };
    Outcome {
        good,
        evidence: "scenario_oracle".to_owned(),
    }
}

/// Counterfactual examples over a fixed grid of states: for every state, one example per legal candidate. The grid is
/// versioned (`grid-v1`); the same call always gives the same examples.
pub fn scenario_examples(cfg: &RuleSettings) -> Vec<Example> {
    let mut out = Vec::new();
    let mut index = 0u64;
    let covers = [
        (0usize, None, 0.0),
        (1, Some(Level::Sourced), 0.4),
        (1, Some(Level::Sourced), 1.0),
        (2, Some(Level::Verified), 1.0),
    ];
    for missing in [None, Some("slot".to_owned())] {
        for (accepted, best, coverage) in covers {
            for below in [0usize, 1] {
                for pending in [0usize, 1] {
                    for conflicts in [0usize, 1] {
                        for acquisition in [false, true] {
                            for asks in [0u32, cfg.max_advisor_asks] {
                                for call in [CallState::None, CallState::Legal, CallState::Refused]
                                {
                                    for (steps, repeats) in
                                        [(6u32, 0u32), (0, 0), (6, cfg.max_repeats)]
                                    {
                                        for fresh in [false, true] {
                                            let mut s = Signals::empty(steps, 120.0);
                                            s.missing_slot = missing.clone();
                                            s.accepted = accepted;
                                            s.best_level = best;
                                            s.coverage = coverage;
                                            s.below_required = below;
                                            s.pending_candidates = pending;
                                            s.open_conflicts = conflicts;
                                            s.acquisition_allowed = acquisition;
                                            s.advisor_asks = asks;
                                            s.call = call;
                                            s.repeats = repeats;
                                            s.fresh_since_retrieve = fresh;
                                            let group = format!("scenario:grid-v1:{index}");
                                            let candidates = legal(&s, cfg);
                                            for act in &candidates {
                                                out.push(Example {
                                                    group: group.clone(),
                                                    origin: Origin::Scenario,
                                                    advisor: None,
                                                    signals: s.clone(),
                                                    candidates: candidates.clone(),
                                                    action: *act,
                                                    outcome: scenario_outcome(&s, *act, cfg),
                                                    provenance: json!({
                                                        "scenario": "grid-v1",
                                                        "index": index,
                                                    }),
                                                });
                                            }
                                            index += 1;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    out
}

/// The split an example belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Split {
    /// Fits the network.
    Train,
    /// Fits the calibration and the abstention threshold.
    Validation,
    /// Sealed; measured once, in T171.
    Heldout,
    /// Sealed; every example of the withheld advisor (gate N5).
    UnseenAdvisor,
}

impl Split {
    /// The name used in files and the manifest.
    pub fn as_str(self) -> &'static str {
        match self {
            Split::Train => "train",
            Split::Validation => "validation",
            Split::Heldout => "heldout",
            Split::UnseenAdvisor => "heldout-unseen-advisor",
        }
    }

    const ALL: [Split; 4] = [
        Split::Train,
        Split::Validation,
        Split::Heldout,
        Split::UnseenAdvisor,
    ];
}

/// How the groups are divided. Percentages are of groups.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SplitSettings {
    /// Share of groups for validation (0 to 100).
    pub validation_pct: u64,
    /// Share of groups held out (0 to 100).
    pub heldout_pct: u64,
    /// An advisor whose examples are kept out of training and validation altogether.
    pub withheld_advisor: Option<String>,
}

/// The split of an example, by a hash of its group so the same group always falls in the same place.
pub fn split_of(example: &Example, settings: &SplitSettings) -> Split {
    if let (Some(withheld), Some(advisor)) = (&settings.withheld_advisor, &example.advisor)
        && withheld == advisor
    {
        return Split::UnseenAdvisor;
    }
    let digest = sha256_hex(example.group.as_bytes());
    let bucket = u64::from_str_radix(&digest[..8], 16).unwrap_or(0) % 100;
    if bucket < settings.heldout_pct {
        Split::Heldout
    } else if bucket < settings.heldout_pct + settings.validation_pct {
        Split::Validation
    } else {
        Split::Train
    }
}

/// What [`write`] returns and writes as `manifest.json`.
#[derive(Debug, Clone, PartialEq)]
pub struct Manifest(pub Value);

/// An error of writing or checking a dataset.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DatasetError(pub String);

impl std::fmt::Display for DatasetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for DatasetError {}

fn io(e: std::io::Error) -> DatasetError {
    DatasetError(e.to_string())
}

fn digest_of_ids(mut ids: Vec<String>) -> String {
    ids.sort();
    sha256_hex(ids.join("\n").as_bytes())
}

/// Writes the splits, the manifest and the seal into `dir`. `inputs` names the logs the examples came from (with
/// their checksums), `left_out` counts what was excluded and `date` is the day written on the manifest.
pub fn write(
    dir: &Path,
    examples: &[Example],
    settings: &SplitSettings,
    inputs: &[(String, String)],
    left_out: &BTreeMap<Excluded, usize>,
    date: &str,
) -> Result<Manifest, DatasetError> {
    fs::create_dir_all(dir).map_err(io)?;
    let mut by_split: BTreeMap<Split, Vec<&Example>> = BTreeMap::new();
    for e in examples {
        by_split.entry(split_of(e, settings)).or_default().push(e);
    }
    let mut files = serde_json::Map::new();
    let mut counts = serde_json::Map::new();
    let mut sealed_ids = Vec::new();
    for split in Split::ALL {
        let Some(list) = by_split.get(&split) else {
            continue;
        };
        let mut lines: Vec<String> = list.iter().map(|e| e.line(split)).collect();
        lines.sort();
        let body = lines.join("\n") + "\n";
        let name = format!("{}.jsonl", split.as_str());
        fs::write(dir.join(&name), &body).map_err(io)?;
        let scenario = list.iter().filter(|e| e.origin == Origin::Scenario).count();
        files.insert(
            name,
            json!({"sha256": sha256_hex(body.as_bytes()), "examples": list.len()}),
        );
        counts.insert(
            split.as_str().to_owned(),
            json!({
                "examples": list.len(),
                "groups": list.iter().map(|e| e.group.as_str()).collect::<BTreeSet<_>>().len(),
                "scenario_share": scenario as f64 / list.len() as f64,
            }),
        );
        if matches!(split, Split::Heldout | Split::UnseenAdvisor) {
            sealed_ids.extend(list.iter().map(|e| e.id()));
        }
    }
    let manifest = Manifest(json!({
        "schema": SCHEMA,
        "date": date,
        "settings": {
            "validation_pct": settings.validation_pct,
            "heldout_pct": settings.heldout_pct,
            "withheld_advisor": settings.withheld_advisor,
        },
        "files": files,
        "splits": counts,
        "inputs": inputs.iter().map(|(n, s)| json!({"name": n, "sha256": s})).collect::<Vec<_>>(),
        "excluded": left_out.iter().map(|(k, n)| (k.as_str().to_owned(), json!(n))).collect::<serde_json::Map<_, _>>(),
    }));
    fs::write(
        dir.join("manifest.json"),
        serde_json::to_string_pretty(&manifest.0).unwrap_or_default() + "\n",
    )
    .map_err(io)?;
    // the seal: the hash of the sealed ids and of the sealed files, written with the data so a later change shows
    let sealed_files: Vec<String> = ["heldout.jsonl", "heldout-unseen-advisor.jsonl"]
        .iter()
        .filter_map(|n| {
            files
                .get(*n)
                .map(|f| format!("{n}:{}", f["sha256"].as_str().unwrap_or("")))
        })
        .collect();
    let seal = json!({
        "date": date,
        "sealed_examples": sealed_ids.len(),
        "ids_sha256": digest_of_ids(sealed_ids),
        "files_sha256": sha256_hex(sealed_files.join("\n").as_bytes()),
    });
    fs::write(
        dir.join("seal.json"),
        serde_json::to_string_pretty(&seal).unwrap_or_default() + "\n",
    )
    .map_err(io)?;
    Ok(manifest)
}

/// Checks a dataset directory against its manifest and seal. Returns every problem found; empty means intact.
///
/// It finds: a file whose checksum differs, an example whose id is not the hash of its content, an example filed in
/// another split than the one its group belongs to, a group in two splits (a leak into the held-out set) and a seal
/// that no longer matches.
pub fn verify(dir: &Path, settings: &SplitSettings) -> Result<Vec<String>, DatasetError> {
    let mut problems = Vec::new();
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(dir.join("manifest.json")).map_err(io)?)
            .map_err(|e| DatasetError(e.to_string()))?;
    let seal: Value = serde_json::from_str(&fs::read_to_string(dir.join("seal.json")).map_err(io)?)
        .map_err(|e| DatasetError(e.to_string()))?;
    let mut home: BTreeMap<String, Split> = BTreeMap::new();
    let mut sealed_ids = Vec::new();
    let mut sealed_files = Vec::new();
    for split in Split::ALL {
        let name = format!("{}.jsonl", split.as_str());
        let path = dir.join(&name);
        let Some(entry) = manifest["files"].get(&name) else {
            if path.exists() {
                problems.push(format!("{name} is not in the manifest"));
            }
            continue;
        };
        let body = fs::read_to_string(&path).map_err(io)?;
        if entry["sha256"].as_str() != Some(&sha256_hex(body.as_bytes())) {
            problems.push(format!("{name}: checksum differs from the manifest"));
        }
        for line in body.lines() {
            let Some((example, id, filed)) = Example::parse(line) else {
                problems.push(format!("{name}: a line does not parse"));
                continue;
            };
            if id != example.id() {
                problems.push(format!("{name}: id {id} is not the hash of its content"));
            }
            if filed != split.as_str() || split_of(&example, settings) != split {
                problems.push(format!("{name}: {id} is filed in the wrong split"));
            }
            if let Some(other) = home.insert(example.group.clone(), split)
                && other != split
            {
                problems.push(format!(
                    "group {} is in {} and {}",
                    example.group,
                    other.as_str(),
                    split.as_str()
                ));
            }
            if matches!(split, Split::Heldout | Split::UnseenAdvisor) {
                sealed_ids.push(example.id());
            }
        }
        if matches!(split, Split::Heldout | Split::UnseenAdvisor) {
            sealed_files.push(format!("{name}:{}", sha256_hex(body.as_bytes())));
        }
    }
    if seal["ids_sha256"].as_str() != Some(&digest_of_ids(sealed_ids)) {
        problems.push("the sealed ids differ from the seal".to_owned());
    }
    if seal["files_sha256"].as_str() != Some(&sha256_hex(sealed_files.join("\n").as_bytes())) {
        problems.push("the sealed files differ from the seal".to_owned());
    }
    Ok(problems)
}

/// One piece of text that may be used to train ResearchLLM.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TextItem {
    /// `source` or `claim_quote`.
    pub kind: &'static str,
    /// The note it comes from.
    pub title: String,
    /// The text.
    pub text: String,
    /// The checksum of the text.
    pub sha256: String,
}

/// The text of the brain that may reach ResearchLLM training, and what was left out and why.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct TextCorpus {
    /// The usable text.
    pub items: Vec<TextItem>,
    /// `(note title, reason)` of every note that was not used.
    pub left_out: Vec<(String, String)>,
}

/// Source texts that are not retracted, and the verified quote of every Claim whose span resolves in such a Source.
///
/// A Claim's statement is not used: an advisor wrote it, and the quote is what the gate verified. Theories, Conflicts
/// and Open questions are not used either (their words are the brain's own or an advisor's, not a Source's). A note
/// that sits in the vault without the properties the gate writes is reported, not used.
pub fn training_text(index: &VaultIndex) -> TextCorpus {
    let mut corpus = TextCorpus::default();
    let mut usable: BTreeMap<String, &Note> = BTreeMap::new();
    for note in index.notes.values() {
        match prop(note, "type").as_str() {
            "source" => {
                let status = prop(note, "status");
                let sealed = prop(note, "sha256") == sha256_hex(note.body.as_bytes());
                if status == "retracted" {
                    corpus
                        .left_out
                        .push((note.title.clone(), "source is retracted".into()));
                } else if !sealed {
                    corpus.left_out.push((
                        note.title.clone(),
                        "source text does not match its sha256".into(),
                    ));
                } else {
                    usable.insert(note.title.clone(), note);
                    corpus.items.push(TextItem {
                        kind: "source",
                        title: note.title.clone(),
                        text: note.body.clone(),
                        sha256: sha256_hex(note.body.as_bytes()),
                    });
                }
            }
            "claim" => {}
            "theory" => corpus.left_out.push((
                note.title.clone(),
                "theory wording is not a source's".into(),
            )),
            "conflict" | "open-question" => {
                corpus
                    .left_out
                    .push((note.title.clone(), "note text is the brain's own".into()));
            }
            _ => corpus.left_out.push((
                note.title.clone(),
                "note is outside the brain profile".into(),
            )),
        }
    }
    for note in index.notes.values().filter(|n| prop(n, "type") == "claim") {
        let source = usable.get(&link_name(&prop(note, "source_ref")));
        let span = (
            note.prop("span_start")
                .and_then(|v| v.py_str().parse::<i64>().ok()),
            note.prop("span_end")
                .and_then(|v| v.py_str().parse::<i64>().ok()),
        );
        let (Some(source), (Some(start), Some(end))) = (source, span) else {
            corpus
                .left_out
                .push((note.title.clone(), "no usable source or span".into()));
            continue;
        };
        match resolve_span(&source.body, start, end, &prop(note, "span_sha256")) {
            Ok(quote) => corpus.items.push(TextItem {
                kind: "claim_quote",
                title: note.title.clone(),
                text: quote.to_owned(),
                sha256: sha256_hex(quote.as_bytes()),
            }),
            Err(_) => corpus
                .left_out
                .push((note.title.clone(), "span does not resolve".into())),
        }
    }
    corpus
        .items
        .sort_by(|a, b| (a.kind, &a.title).cmp(&(b.kind, &b.title)));
    corpus
}
