//! Settings of the STEM profile (T284). The profile reads the very file the Python runner reads,
//! `configs/stem-benchmarks.json`: its `baseline` (model, modes, prompts), `harness` (the frozen candidate: thinking
//! budget, conclusion, self-consistency, notes, formalisation) and `server_profile` (what only the server needs). So
//! the web client, the terminal client and the benchmark runner are answered under one configuration.
//!
//! The server's own settings are `LARIS_SERVER__STEM_*` variables. A lever the server does not carry (escalation,
//! repetition watch, a router network, the deterministic-only analysis path) is refused when it is on, so the server
//! never runs a configuration other than the one it says it runs.

use crate::config::ConfigError;
use regex::Regex;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Which turns the profile answers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Entry {
    /// No turn.
    Off,
    /// Only requests that carry an item (`laris.stem`, the benchmark runner).
    Request,
    /// Those, and a chat turn whose question passes the prompt filter with a STEM signal (owner 2026-11-27).
    Auto,
}

/// Sampling of one mode (`baseline.modes`).
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Mode {
    /// Thinking in the chat template.
    pub enable_thinking: bool,
    /// Most tokens of a reply.
    pub max_new_tokens: u32,
    /// Temperature.
    pub temperature: f64,
    /// Nucleus share.
    pub top_p: f64,
    /// Top-k.
    pub top_k: i64,
}

/// The benchmark prompts of T275 (`baseline.prompts`).
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct BasePrompts {
    /// Open questions.
    pub math: String,
    /// Multiple choice.
    pub choice: String,
}

/// The `baseline` section.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Baseline {
    /// The model the engine serves.
    pub model_id: String,
    /// The generation seed every item seed starts from.
    pub generation_seed: u64,
    /// Sampling modes by name.
    pub modes: BTreeMap<String, Mode>,
    /// Prompts.
    pub prompts: BasePrompts,
}

/// `harness.router`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct RouterCfg {
    /// Share of options with a digit that makes a question computable.
    pub numeric_option_share: f64,
    /// Longest question (words) of the knowledge class.
    pub knowledge_max_question_words: usize,
    /// A router network (not carried by the server).
    #[serde(default)]
    pub network: Option<serde_json::Value>,
}

/// `harness.filter`.
#[derive(Debug, Clone, PartialEq, Deserialize, Default)]
pub struct FilterCfg {
    /// Every prompt passes the filter first.
    #[serde(default)]
    pub enabled: bool,
}

/// `harness.brain_only`.
#[derive(Debug, Clone, PartialEq, Deserialize, Default)]
pub struct BrainOnlyCfg {
    /// Answer from one certain Claim alone.
    #[serde(default)]
    pub enabled: bool,
    /// Fewest content words an option needs.
    #[serde(default)]
    pub min_option_words: usize,
}

/// `harness.retrieval`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct RetrievalCfg {
    /// Classes that get notes.
    pub classes: Vec<String>,
    /// Passages per item.
    pub k: usize,
    /// Characters shown of one passage.
    pub max_chars_per_note: usize,
    /// The brain configuration (gate thresholds, data folder), relative to the root.
    pub brain_config: String,
    /// The frozen snapshot.
    pub snapshot: String,
    /// Source classes that make a Claim certain (T285); none: no hit is certain.
    #[serde(default)]
    pub source_classes: Option<String>,
}

/// `harness.draft.escalate`.
#[derive(Debug, Clone, PartialEq, Deserialize, Default)]
pub struct EscalateCfg {
    /// Escalation of an unread draft to a thinking call (not carried by the server).
    #[serde(default)]
    pub enabled: bool,
}

/// `harness.draft`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct DraftCfg {
    /// Retries of an unread or cut draft.
    pub max_retries: u32,
    /// Thinking budget by class; a class without one drafts with thinking off.
    #[serde(default)]
    pub thinking: BTreeMap<String, u32>,
    /// Most tokens of the answer after a thinking budget ran out.
    #[serde(default = "answer_tokens")]
    pub answer_tokens: u32,
    /// Escalation.
    #[serde(default)]
    pub escalate: EscalateCfg,
}

fn answer_tokens() -> u32 {
    1024
}

fn always() -> String {
    "always".to_owned()
}

fn yes() -> bool {
    true
}

/// `harness.formalise`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct FormaliseCfg {
    /// Classes formalised.
    pub classes: Vec<String>,
    /// Most tokens of the formalisation reply.
    pub max_tokens: u32,
    /// `always` or `uncertain` (no readable draft, or a retried one).
    #[serde(default = "always")]
    pub when: String,
    /// Review the draft on a disagreement with the solver.
    #[serde(default = "yes")]
    pub review: bool,
}

/// `harness.self_consistency`.
#[derive(Debug, Clone, PartialEq, Deserialize, Default)]
pub struct ConsistencyCfg {
    /// On.
    #[serde(default)]
    pub enabled: bool,
    /// More drafts drawn.
    #[serde(default)]
    pub samples: u32,
    /// `disagree`, `retried`.
    #[serde(default)]
    pub when: Vec<String>,
}

/// `harness.conclude`.
#[derive(Debug, Clone, PartialEq, Deserialize, Default)]
pub struct ConcludeCfg {
    /// On.
    #[serde(default)]
    pub enabled: bool,
    /// A cut draft is concluded in place of the keep-it-short retry.
    #[serde(default)]
    pub replace_retry: bool,
    /// Cut samples are concluded too.
    #[serde(default)]
    pub samples: bool,
    /// Most tokens of a concluded letter.
    #[serde(default)]
    pub max_tokens_choice: u32,
    /// Most tokens of a concluded open answer.
    #[serde(default)]
    pub max_tokens_math: u32,
}

/// `harness.repetition`.
#[derive(Debug, Clone, PartialEq, Deserialize, Default)]
pub struct RepetitionCfg {
    /// The repetition watch (not carried by the server).
    #[serde(default)]
    pub enabled: bool,
}

/// `harness.solver_check`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct SolverCheckCfg {
    /// Relative tolerance of an option matching the solver's value.
    pub option_rel_tol: f64,
    /// Solver calls at once.
    pub max_concurrency: usize,
}

/// `harness.notes_check`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct NotesCheckCfg {
    /// On.
    pub enabled: bool,
    /// Fewest content words an option needs.
    pub min_option_words: usize,
}

/// `harness.prompts`.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Prompts {
    /// Notes before the benchmark prompt (`{notes}`).
    pub notes_prefix: String,
    /// Added to the prompt of a retry.
    pub retry_suffix: String,
    /// Opening of a concluded open answer.
    pub conclude_math: String,
    /// Opening of a concluded letter.
    pub conclude_choice: String,
    /// Formalisation of an open question.
    pub formalise_math: String,
    /// Formalisation of a multiple-choice question.
    pub formalise_choice: String,
    /// Review against the solver.
    pub review_solver: String,
    /// Review against the notes.
    pub review_notes: String,
}

/// The `harness` section: the frozen candidate.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct HarnessCfg {
    /// The mode of plain drafts (`baseline.modes`).
    pub mode: String,
    /// Requests to the engine at once.
    pub concurrency: usize,
    /// Added to every item seed (repeated seeds of one configuration).
    #[serde(default)]
    pub seed_offset: u64,
    /// Prompt filter.
    #[serde(default)]
    pub filter: FilterCfg,
    /// Router.
    pub router: RouterCfg,
    /// The model-free path.
    pub model_free: bool,
    /// The brain-only path.
    #[serde(default)]
    pub brain_only: BrainOnlyCfg,
    /// Notes.
    pub retrieval: RetrievalCfg,
    /// Drafts.
    pub draft: DraftCfg,
    /// Formalisation.
    pub formalise: FormaliseCfg,
    /// Self-consistency.
    #[serde(default)]
    pub self_consistency: ConsistencyCfg,
    /// Conclusion of a cut reply.
    #[serde(default)]
    pub conclude: ConcludeCfg,
    /// Repetition watch.
    #[serde(default)]
    pub repetition: RepetitionCfg,
    /// Solver answers.
    pub solver_check: SolverCheckCfg,
    /// Cross-check of the formalisation (`record` or `gate`); absent: none.
    #[serde(default)]
    pub formalisation_check: Option<serde_json::Value>,
    /// Notes check.
    pub notes_check: NotesCheckCfg,
    /// The analysis path without the model.
    #[serde(default)]
    pub deterministic_only: bool,
    /// Prompts.
    pub prompts: Prompts,
}

/// `server_profile.chat`: how a chat turn becomes an item and how its answer is shown.
#[derive(Debug, Clone, Deserialize)]
pub struct ChatCfg {
    /// A line read as an option: group 1 the letter, group 2 the text.
    pub option_line: String,
    /// Fewest option lines that make a question multiple choice.
    pub min_options: usize,
    /// The answer line after the draft (`{answer}`, `{from}`).
    pub answer_line: String,
    /// How an answer written in LaTeX is put in the answer line (`{answer}`): as Markdown math, so a client typesets
    /// it and Markdown does not eat its backslashes (T291).
    pub answer_math: String,
    /// Characters that mark an answer as LaTeX.
    pub math_marks: String,
    /// The text of a turn that ended with no answer.
    pub no_answer: String,
    /// Names of where the final answer came from, by `final_from`.
    pub from: BTreeMap<String, String>,
}

/// The `server_profile` section.
#[derive(Debug, Clone, Deserialize)]
pub struct ServerProfileCfg {
    /// The model's opening reasoning tag.
    pub think_open: String,
    /// The model's closing reasoning tag.
    pub think_close: String,
    /// Closing sentence and tag of a thinking budget that ran out (`cost.FORCE_ANSWER`).
    pub force_answer: String,
    /// Function words left out of content words (`harness._STOP`).
    pub stop_words: Vec<String>,
    /// Milliseconds between keep-alive events while a step runs.
    pub heartbeat_ms: u64,
    /// Chat.
    pub chat: ChatCfg,
}

/// The parts of `configs/stem-benchmarks.json` the profile reads.
#[derive(Debug, Clone, Deserialize)]
struct File {
    baseline: Baseline,
    harness: HarnessCfg,
    server_profile: ServerProfileCfg,
    engine: EngineFile,
}

#[derive(Debug, Clone, Deserialize)]
struct EngineFile {
    timeout_s: f64,
}

/// Gate thresholds of the brain configuration (`configs/stem-brain.json`).
#[derive(Debug, Clone, Deserialize)]
struct BrainFile {
    data_dir: String,
    gate: GateFile,
}

#[derive(Debug, Clone, Deserialize)]
struct GateFile {
    min_support: f64,
    min_equivalence: f64,
    subject_overlap: f64,
    search_depth: usize,
    max_bytes: usize,
}

/// The STEM profile's settings.
#[derive(Debug, Clone)]
pub struct StemConfig {
    /// Which turns it answers.
    pub entry: Entry,
    /// The engine's OpenAI-compatible address (`LARIS_SERVER__STEM_ENGINE_URL`), `/v1/...` added.
    pub engine_url: String,
    /// Longest one engine request may take.
    pub engine_timeout: Duration,
    /// Baseline section.
    pub baseline: Baseline,
    /// Harness section.
    pub harness: HarnessCfg,
    /// Server section.
    pub server: ServerProfileCfg,
    /// The plain-draft mode.
    pub mode: Mode,
    /// The thinking mode (`baseline.modes.thinking_on`), used by thinking budgets.
    pub thinking: Mode,
    /// The option-line pattern.
    pub option_line: Regex,
    /// The frozen snapshot's vault and gate.
    pub brain: crate::mainbrain::MainBrainConfig,
    /// SHA-256 of the snapshot (`snapshot.json`), recorded with every answer.
    pub snapshot_sha256: String,
    /// Source classes, when certain Claims count.
    pub admissible: Option<laris_brain::certain::Admissibility>,
    /// SHA-256 of the configuration file, recorded with every answer.
    pub config_sha256: String,
}

impl StemConfig {
    /// Reads the settings; `None` unless `LARIS_SERVER__STEM_PROFILE` is `auto` or `request`.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Option<Self>, ConfigError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let invalid =
            |name: &'static str, reason: &'static str| ConfigError::Invalid { name, reason };
        let entry = match get("LARIS_SERVER__STEM_PROFILE") {
            None | Some("off") => return Ok(None),
            Some("auto") => Entry::Auto,
            Some("request") => Entry::Request,
            Some(_) => {
                return Err(invalid(
                    "LARIS_SERVER__STEM_PROFILE",
                    "expected off, request or auto",
                ));
            }
        };
        let text = |name: &'static str| get(name).ok_or(ConfigError::Missing(name));
        let path = PathBuf::from(text("LARIS_SERVER__STEM_CONFIG")?);
        let root = PathBuf::from(text("LARIS_SERVER__STEM_ROOT")?);
        let url = text("LARIS_SERVER__STEM_ENGINE_URL")?.trim_end_matches('/');
        if !(url.starts_with("http://") || url.starts_with("https://")) {
            return Err(invalid(
                "LARIS_SERVER__STEM_ENGINE_URL",
                "expected an http:// or https:// address",
            ));
        }
        let bytes = std::fs::read(&path).map_err(|_| {
            invalid(
                "LARIS_SERVER__STEM_CONFIG",
                "expected a readable configuration file",
            )
        })?;
        let mut cfg = Self::parse(entry, url, &bytes, &root)?;
        if let Some(ms) = get("LARIS_SERVER__STEM_ENGINE_TIMEOUT_MS") {
            cfg.engine_timeout = Duration::from_millis(
                ms.parse::<u64>().ok().filter(|n| *n >= 1).ok_or(invalid(
                    "LARIS_SERVER__STEM_ENGINE_TIMEOUT_MS",
                    "expected a whole number in range",
                ))?,
            );
        }
        Ok(Some(cfg))
    }

    /// The settings from the configuration file's bytes; relative paths start at `root`.
    pub fn parse(entry: Entry, url: &str, bytes: &[u8], root: &Path) -> Result<Self, ConfigError> {
        const NAME: &str = "LARIS_SERVER__STEM_CONFIG";
        let invalid = |reason: &'static str| ConfigError::Invalid { name: NAME, reason };
        let file: File = serde_json::from_slice(bytes)
            .map_err(|_| invalid("the STEM configuration does not parse"))?;
        let h = &file.harness;
        // levers the server does not carry: refused, never silently ignored
        if h.draft.escalate.enabled {
            return Err(invalid(
                "draft.escalate is not carried by the server profile",
            ));
        }
        if h.repetition.enabled {
            return Err(invalid("repetition is not carried by the server profile"));
        }
        if h.router.network.as_ref().is_some_and(|v| !v.is_null()) {
            return Err(invalid("a router network is not promoted (T287)"));
        }
        if h.deterministic_only {
            return Err(invalid("deterministic_only is an analysis path"));
        }
        if h.brain_only.enabled && h.retrieval.source_classes.is_none() {
            return Err(invalid("brain_only needs retrieval.source_classes"));
        }
        let mode = file
            .baseline
            .modes
            .get(&h.mode)
            .cloned()
            .ok_or(invalid("harness.mode names no baseline mode"))?;
        let thinking = file
            .baseline
            .modes
            .get("thinking_on")
            .cloned()
            .ok_or(invalid("baseline.modes has no thinking_on"))?;
        let option_line = Regex::new(&file.server_profile.chat.option_line)
            .map_err(|_| invalid("server_profile.chat.option_line is not a pattern"))?;
        let brain_bytes = std::fs::read(root.join(&h.retrieval.brain_config))
            .map_err(|_| invalid("retrieval.brain_config cannot be read"))?;
        let brain: BrainFile = serde_json::from_slice(&brain_bytes)
            .map_err(|_| invalid("retrieval.brain_config does not parse"))?;
        let folder = root
            .join(&brain.data_dir)
            .join("snapshots")
            .join(&h.retrieval.snapshot);
        let snapshot: serde_json::Value = std::fs::read(folder.join("snapshot.json"))
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .ok_or(invalid("the snapshot has no readable snapshot.json"))?;
        let snapshot_sha256 = snapshot["snapshot_sha256"]
            .as_str()
            .ok_or(invalid("snapshot.json has no snapshot_sha256"))?
            .to_owned();
        let admissible = match &h.retrieval.source_classes {
            None => None,
            Some(p) => Some(
                laris_brain::certain::Admissibility::load(&root.join(p))
                    .map_err(|_| invalid("retrieval.source_classes cannot be read"))?,
            ),
        };
        if !(file.engine.timeout_s > 0.0 && file.engine.timeout_s.is_finite()) {
            return Err(invalid("engine.timeout_s must be positive"));
        }
        Ok(Self {
            entry,
            engine_url: url.to_owned(),
            engine_timeout: Duration::from_secs_f64(file.engine.timeout_s),
            mode,
            thinking,
            option_line,
            brain: crate::mainbrain::MainBrainConfig {
                dir: folder.join("vault"),
                gate: laris_brain::gate::GateSettings {
                    min_support: brain.gate.min_support,
                    min_equivalence: brain.gate.min_equivalence,
                    subject_overlap: brain.gate.subject_overlap,
                    search_depth: brain.gate.search_depth,
                    max_bytes: brain.gate.max_bytes,
                },
            },
            snapshot_sha256,
            admissible,
            config_sha256: Sha256::digest(bytes)
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect(),
            baseline: file.baseline,
            harness: file.harness,
            server: file.server_profile,
        })
    }
}
