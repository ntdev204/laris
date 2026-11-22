//! What the analysis is told: the server's policy for research gaps ([`Settings`], `.laris/gap.toml`) and the
//! vocabulary of one topic ([`Topic`], a file next to the papers). Nothing in the analysis is a constant of the code:
//! the rule parameters, the ranking weights, the cue words and the prompts are all read from these two files.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Weights of the ranking score `s(g) = w1·papers + w2·[G1 or G2] + w3·verified quotes − w4·[one paper]`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Weights {
    /// Per paper that supports the gap.
    pub w1: f64,
    /// For a gap of rule G1 (repeated limitation) or G2 (unresolved conflict).
    pub w2: f64,
    /// Per quotation of the evidence found verbatim in its paper.
    pub w3: f64,
    /// Subtracted when the gap rests on one paper only.
    pub w4: f64,
}

/// Parameters of the gap rules.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Rules {
    /// G1: least number of papers that must state the same issue.
    pub min_papers_g1: usize,
    /// G1 needs at least this many of its quotations found verbatim.
    pub min_verified_g1: usize,
    /// G3 keeps a method × setting pair only when the papers of the method and the papers of the setting state at
    /// least one common issue (`true`), or keeps every pair (`false`).
    pub g3_needs_common_issue: bool,
}

/// The prompts the server sends to the model. `{...}` marks are filled by the server.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Prompts {
    /// Per paper: return the JSON record. Marks: `{excerpts}`.
    pub extract: String,
    /// Baseline (a): the question alone. Marks: `{question}`.
    pub closed: String,
    /// Baseline (a2): the question with excerpts of every paper. Marks: `{question}`, `{register}`, `{excerpts}`.
    pub context: String,
    /// Baseline (b): the question with the passages retrieval found. Marks: `{question}`, `{register}`, `{passages}`.
    pub rag: String,
}

/// Limits of what is sent to the model.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Budget {
    /// Most characters of excerpts per paper for the extraction.
    pub extract_chars: usize,
    /// Most characters of excerpts over all papers for baseline (a2).
    pub context_chars: usize,
    /// Passages baseline (b) sends.
    pub rag_passages: usize,
    /// Longest passage of the retrieval index, in characters.
    pub passage_chars: usize,
}

/// The server's policy for research gaps (`.laris/gap.toml`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Settings {
    /// Version of this policy; written into every run.
    pub version: String,
    /// Ranking weights.
    pub weights: Weights,
    /// Rule parameters.
    pub rules: Rules,
    /// Size limits.
    pub budget: Budget,
    /// Regular expressions (case-insensitive) that mark a sentence about a limitation or future work; such
    /// sentences from every section are added to the extraction excerpts.
    pub limitation_cues: Vec<String>,
    /// Queries of baseline (b), each one a retrieval channel fused by reciprocal rank; `{question}` is the question.
    pub rag_queries: Vec<String>,
    /// Regular expressions (case-insensitive) of a claim from absence ("no prior work", "chưa ai làm").
    pub absence_patterns: Vec<String>,
    /// Regular expressions (case-insensitive) that limit such a claim to the papers read ("among the papers read").
    pub scope_patterns: Vec<String>,
    /// The prompts.
    pub prompts: Prompts,
}

impl Settings {
    /// Reads the policy from TOML.
    pub fn from_toml(text: &str) -> Result<Settings, String> {
        toml::from_str(text).map_err(|e| format!("gap policy: {e}"))
    }
}

/// Cue words of the conflict rule G2 for one topic.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct ConflictCues {
    /// A sentence that says a method does not work, is infeasible or fails (case-insensitive regular expressions).
    pub negative: Vec<String>,
    /// A result that says a method works (case-insensitive regular expressions).
    pub positive: Vec<String>,
}

/// One topic: its question and the vocabulary that links papers to concepts.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Topic {
    /// Short id (`mpc`, `rag-halluc`).
    pub id: String,
    /// Title for people.
    pub title: String,
    /// The question asked to the system and to the baselines.
    pub question: String,
    /// Papers published up to this year form the corpus of the time-split evaluation; later ones are the "future".
    #[serde(default)]
    pub cutoff_year: Option<u32>,
    /// `method`, `setting` and `issue` concepts, each a name with the terms that mark it (whole words,
    /// case-insensitive).
    pub concepts: BTreeMap<String, BTreeMap<String, Vec<String>>>,
    /// Cue words of rule G2.
    #[serde(default)]
    pub conflict: ConflictCues,
}

impl Topic {
    /// Reads a topic from TOML and checks it has the three facets.
    pub fn from_toml(text: &str) -> Result<Topic, String> {
        let topic: Topic = toml::from_str(text).map_err(|e| format!("topic: {e}"))?;
        for facet in ["method", "setting", "issue"] {
            if topic.concepts.get(facet).is_none_or(BTreeMap::is_empty) {
                return Err(format!("topic {}: no `{facet}` concepts", topic.id));
            }
        }
        Ok(topic)
    }

    /// The concepts of one facet.
    pub fn facet(&self, name: &str) -> impl Iterator<Item = (&String, &Vec<String>)> {
        self.concepts.get(name).into_iter().flat_map(|m| m.iter())
    }
}
