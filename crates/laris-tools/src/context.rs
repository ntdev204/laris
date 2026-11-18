//! What the local tools work with: the allowed folders, the limits from the settings, the environment of
//! commands, the checkpoint folder, and the places memory and skills live.

use crate::checkpoints::Checkpoints;
use crate::error::ToolError;
use crate::knowledge::Knowledge;
use crate::scope::Scope;
use laris_config::Settings;
use laris_config::settings::{Tools, Vault};
use laris_sandbox::{PythonEnv, Sandbox};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Hides credentials in text before a tool writes it (T136 supplies the real one).
pub type Redactor = Box<dyn Fn(&str) -> String + Send + Sync>;

/// Shared by every local tool.
pub struct Context {
    /// The folders tools may touch.
    pub scope: Scope,
    /// Limits.
    pub limits: Tools,
    /// Environment variables set for commands.
    pub env: BTreeMap<String, String>,
    /// Whether commands inherit this process's environment.
    pub inherit_env: bool,
    /// Where edits are saved before they are made; `None` keeps no checkpoints.
    pub checkpoints: Option<Checkpoints>,
    /// The folder `save_memory` writes to; `None` turns the tool off.
    pub memory_dir: Option<PathBuf>,
    /// Folders holding `<name>/SKILL.md`; a project folder is passed only when the folder is trusted (T133).
    pub skill_dirs: Vec<PathBuf>,
    /// Confines `Bash` (T135). `None` runs commands unconfined, and then installs are refused.
    pub sandbox: Option<Arc<Sandbox>>,
    /// The Python environment (`~/.laris/.venv`); its `bin` folder leads `PATH` for `Bash`.
    pub python_env: Option<PythonEnv>,
    /// Applied to what `Write`, `Edit` and `save_memory` persist.
    pub redact: Redactor,
    /// Limits of the vault and of ingestion.
    pub vault: Vault,
    /// The project vault and database; `None` leaves the knowledge tools out.
    pub knowledge: Option<Arc<Knowledge>>,
}

impl Context {
    /// A context for the project folder `root` with the limits, environment and extra folders of `settings`.
    pub fn new(root: &Path, settings: &Settings) -> Result<Self, ToolError> {
        let extra: Vec<PathBuf> = settings
            .permissions
            .additional_directories
            .iter()
            .map(|d| expand_home(d))
            .collect();
        Ok(Self {
            scope: Scope::new(root, &extra, &settings.tools.denied_files)?,
            limits: settings.tools.clone(),
            env: settings.env.clone(),
            inherit_env: settings.sandbox.inherit_env,
            checkpoints: None,
            memory_dir: None,
            skill_dirs: Vec::new(),
            sandbox: None,
            python_env: None,
            redact: Box::new(str::to_owned),
            vault: settings.vault.clone(),
            knowledge: None,
        })
    }

    /// Keeps checkpoints in `folder`.
    #[must_use]
    pub fn with_checkpoints(mut self, folder: impl Into<PathBuf>) -> Self {
        let keep = usize::try_from(self.limits.checkpoint_keep).unwrap_or(usize::MAX);
        self.checkpoints = Some(Checkpoints::new(folder, keep));
        self
    }

    /// Turns `save_memory` on, writing into `folder`.
    #[must_use]
    pub fn with_memory_dir(mut self, folder: impl Into<PathBuf>) -> Self {
        self.memory_dir = Some(folder.into());
        self
    }

    /// Sets the folders skills are read from, first wins.
    #[must_use]
    pub fn with_skill_dirs(mut self, folders: Vec<PathBuf>) -> Self {
        self.skill_dirs = folders;
        self
    }

    /// Runs `Bash` inside `sandbox`.
    #[must_use]
    pub fn with_sandbox(mut self, sandbox: Arc<Sandbox>) -> Self {
        self.sandbox = Some(sandbox);
        self
    }

    /// Puts the Python environment on the `PATH` of `Bash`.
    #[must_use]
    pub fn with_python_env(mut self, env: PythonEnv) -> Self {
        self.python_env = Some(env);
        self
    }

    /// Turns the knowledge tools on: the vault of the project and its database.
    #[must_use]
    pub fn with_knowledge(mut self, knowledge: Knowledge) -> Self {
        self.knowledge = Some(Arc::new(knowledge));
        self
    }

    /// Sets the redactor.
    #[must_use]
    pub fn with_redactor(mut self, redact: Redactor) -> Self {
        self.redact = redact;
        self
    }
}

fn expand_home(raw: &str) -> PathBuf {
    if let Some(rest) = raw
        .strip_prefix("~/")
        .or_else(|| (raw == "~").then_some(""))
        && let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"))
    {
        return PathBuf::from(home).join(rest);
    }
    PathBuf::from(raw)
}
