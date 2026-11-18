//! The policy gateway of the server (SR-S4): the system prompt, rules, workflows and help text come from `.laris/`
//! and are composed on the server only; the integrity lock is checked before the server listens; what the model
//! says is guarded on its way out; the model's reasoning is kept for the operator and never sent to a client.
//!
//! * [`integrity`]: the lock, `.laris/integrity.toml`.
//! * [`compose`]: the system prompt.
//! * [`workflows`]: narrowing procedures.
//! * [`guard`]: secrets, leaks, the canary.
//! * [`reasoning`]: where the reasoning goes.
//! * [`gateway`]: the [`PolicyGateway`] backend that puts them around the model.

pub mod compose;
pub mod gateway;
pub mod guard;
pub mod integrity;
pub mod reasoning;
pub mod reasoning_pg;
mod routes;
pub mod skills;
pub mod workflows;

pub use compose::{Composed, Composer, PromptError, PromptSettings};
pub use gateway::{PLAN_TOOL, Policy, PolicyGateway};
pub use guard::{GuardSettings, LeakDetector, SecretRedactor, StreamGuard};
pub use integrity::{IntegrityError, Snapshot};
pub use reasoning::{
    DiscardReasoning, MemoryReasoning, ReasoningRecord, ReasoningSink, ReasoningStore,
    ThinkSplitter,
};
pub use reasoning_pg::PgReasoning;
pub use routes::{help, reasoning as reasoning_route, workflows as workflows_route};
pub use skills::{Selection, Skill, SkillSettings, Skills, Why};
pub use workflows::{Workflow, WorkflowError, Workflows};

use guard::Guard;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

/// A policy that cannot be loaded. The message names a file or a setting, never content.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PolicyError {
    /// A required variable is not set.
    #[error("{0} is required")]
    Missing(&'static str),
    /// A variable has a value of the wrong form.
    #[error("{name} is invalid: {reason}")]
    Invalid {
        /// Variable name.
        name: &'static str,
        /// What is wrong.
        reason: &'static str,
    },
    /// The protected files are unreadable or differ from the lock.
    #[error(transparent)]
    Integrity(#[from] IntegrityError),
    /// The prompt cannot be composed.
    #[error(transparent)]
    Prompt(#[from] PromptError),
    /// A workflow file does not load.
    #[error(transparent)]
    Workflow(#[from] WorkflowError),
    /// The guard cannot be built.
    #[error("guard: {0}")]
    Guard(String),
    /// No source of randomness.
    #[error("no source of randomness")]
    Random,
}

/// Settings of the policy gateway, from `LARIS_SERVER__*` variables.
#[derive(Debug, Clone)]
pub struct PolicyConfig {
    /// The project root that holds `LARIS.md` and `.laris/` (`LARIS_SERVER__POLICY_ROOT`, required).
    pub root: PathBuf,
    /// Prompt names and limits.
    pub prompt: PromptSettings,
    /// Guard settings.
    pub guard: GuardSettings,
    /// Tags that wrap inline reasoning (`LARIS_SERVER__THINK_TAGS`, JSON list of `[open, close]`).
    pub think_tags: Vec<(String, String)>,
    /// Choosing a skill for each turn.
    pub skills: SkillSettings,
}

impl PolicyConfig {
    /// A configuration with the defaults.
    pub fn with_root(root: impl Into<PathBuf>) -> Self {
        Self {
            root: root.into(),
            prompt: PromptSettings::default(),
            guard: GuardSettings::default(),
            think_tags: vec![("<think>".to_owned(), "</think>".to_owned())],
            skills: SkillSettings::default(),
        }
    }

    /// Reads the settings from `env` (variable name to value).
    pub fn from_env(env: &HashMap<String, String>) -> Result<Self, PolicyError> {
        let get = |name: &'static str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let root_name = "LARIS_SERVER__POLICY_ROOT";
        let mut cfg = Self::with_root(get(root_name).ok_or(PolicyError::Missing(root_name))?);
        let number = |name: &'static str, min: usize| -> Result<Option<usize>, PolicyError> {
            match get(name) {
                None => Ok(None),
                Some(v) => match v.parse::<usize>() {
                    Ok(n) if n >= min => Ok(Some(n)),
                    _ => Err(PolicyError::Invalid {
                        name,
                        reason: "expected a whole number in range",
                    }),
                },
            }
        };
        let flag = |name: &'static str| -> Result<Option<bool>, PolicyError> {
            match get(name) {
                None => Ok(None),
                Some("true" | "1") => Ok(Some(true)),
                Some("false" | "0") => Ok(Some(false)),
                Some(_) => Err(PolicyError::Invalid {
                    name,
                    reason: "expected true or false",
                }),
            }
        };
        if let Some(v) = get("LARIS_SERVER__ASSISTANT_NAME") {
            cfg.prompt.assistant_name = v.to_owned();
        }
        if let Some(v) = get("LARIS_SERVER__REPLY_LANGUAGE") {
            cfg.prompt.reply_language = v.to_owned();
        }
        let p = &mut cfg.prompt;
        for (name, slot, min) in [
            (
                "LARIS_SERVER__MAX_INSTRUCTION_CHARS",
                &mut p.max_instruction_chars,
                1,
            ),
            ("LARIS_SERVER__MAX_MEMORY_CHARS", &mut p.max_memory_chars, 0),
            (
                "LARIS_SERVER__SKILLS_INDEX_CHARS",
                &mut p.skills_index_chars,
                0,
            ),
            (
                "LARIS_SERVER__USER_PREFERENCES_MAX_CHARS",
                &mut p.user_preferences_max_chars,
                0,
            ),
            (
                "LARIS_SERVER__WORKFLOW_MAX_CHARS",
                &mut p.workflow_max_chars,
                1,
            ),
        ] {
            if let Some(n) = number(name, min)? {
                *slot = n;
            }
        }
        let g = &mut cfg.guard;
        for (name, slot, min) in [
            (
                "LARIS_SERVER__LEAK_SHINGLE_WORDS",
                &mut g.leak_shingle_words,
                1,
            ),
            (
                "LARIS_SERVER__LEAK_MIN_SHINGLES",
                &mut g.leak_min_shingles,
                1,
            ),
            (
                "LARIS_SERVER__LEAK_MAX_SHINGLES",
                &mut g.leak_max_shingles,
                1,
            ),
            (
                "LARIS_SERVER__STREAM_HOLDBACK_CHARS",
                &mut g.stream_holdback_chars,
                0,
            ),
        ] {
            if let Some(n) = number(name, min)? {
                *slot = n;
            }
        }
        if let Some(b) = flag("LARIS_SERVER__LEAK_DETECTION")? {
            g.leak_detection = b;
        }
        if let Some(b) = flag("LARIS_SERVER__CANARY")? {
            g.canary_enabled = b;
        }
        if let Some(list) = get("LARIS_SERVER__EXTRA_SECRET_ENV") {
            g.extra_secret_env = list
                .split(',')
                .map(|s| s.trim().to_owned())
                .filter(|s| !s.is_empty())
                .collect();
        }
        if let Some(b) = flag("LARIS_SERVER__SKILL_SELECTION")? {
            cfg.skills.enabled = b;
        }
        if let Some(n) = number("LARIS_SERVER__SKILL_MAX_CHARS", 1)? {
            cfg.skills.max_chars = n;
        }
        for (name, slot) in [
            ("LARIS_SERVER__SKILL_MIN_SCORE", &mut cfg.skills.min_score),
            ("LARIS_SERVER__SKILL_MARGIN", &mut cfg.skills.margin),
        ] {
            if let Some(v) = get(name) {
                *slot = v
                    .parse::<f64>()
                    .ok()
                    .filter(|n| n.is_finite() && *n >= 0.0)
                    .ok_or(PolicyError::Invalid {
                        name,
                        reason: "expected a number of 0 or more",
                    })?;
            }
        }
        if let Some(text) = get("LARIS_SERVER__THINK_TAGS") {
            cfg.think_tags = serde_json::from_str::<Vec<(String, String)>>(text).map_err(|_| {
                PolicyError::Invalid {
                    name: "LARIS_SERVER__THINK_TAGS",
                    reason: "expected a JSON list of [open, close] pairs",
                }
            })?;
        }
        Ok(cfg)
    }
}

impl Policy {
    /// Checks the policy against its lock and builds it. `environ` is the process environment, read for the
    /// secrets the guard must hide; `home` is the user's home folder, hidden in paths.
    ///
    /// A policy that does not match `integrity.lock` is an error: the server does not start.
    pub fn load(
        config: &PolicyConfig,
        environ: impl IntoIterator<Item = (String, String)>,
        home: Option<&str>,
    ) -> Result<Self, PolicyError> {
        let snapshot = integrity::verified(&config.root)?;
        let composer = Composer::new(&snapshot, config.prompt.clone())?;
        let workflows = Workflows::load(&snapshot)?;
        let help = snapshot
            .text(integrity::HELP_FILE)
            .and_then(Result::ok)
            .map(|t| t.trim().to_owned())
            .unwrap_or_default();
        // every confidential text, composed once as a session would see it
        let boot = composer.compose(&compose::Inputs {
            session_id: "boot",
            date: &gateway::today(),
            ..compose::Inputs::default()
        });
        let leak = LeakDetector::new(&config.guard, boot.confidential.iter().map(String::as_str));
        let root_text = config.root.to_string_lossy();
        let redactor = SecretRedactor::new(&config.guard, environ, Some(&root_text), home)
            .map_err(|e| PolicyError::Guard(e.to_string()))?;
        let secret: [u8; 32] = crate::access::random_bytes(32)
            .ok()
            .and_then(|b| b.try_into().ok())
            .ok_or(PolicyError::Random)?;
        let skills = Skills::load(&config.root, config.skills.clone());
        Ok(Self {
            composer,
            workflows,
            skills,
            help,
            guard: Guard::new(Arc::new(redactor), leak, config.guard.stream_holdback_chars),
            canary_enabled: config.guard.canary_enabled,
            think_tags: config.think_tags.clone(),
            secret,
        })
    }
}
