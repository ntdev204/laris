//! The harness side of the prompt layer (SR-H3): reads the `LARIS.md` layers and the memory notes, keeps the pinned
//! items, and assembles every request with [`laris_core::prompt`], which knows none of this.
//!
//! * The user's layers are `~/.laris/LARIS.md` and the `extraInstructions` setting. The project's layer
//!   (`.laris/LARIS.md`) and memory (`.laris/memory/*.md`) are read only in a trusted folder, like the project's
//!   skills and commands ([`crate::skill_dirs`]): a cloned repository cannot speak to the model by planting them.
//! * Files are read as given only when they are regular files (a symbolic link is skipped), up to
//!   `context.layerMaxChars` characters, and at most `context.memoryMaxNotes` notes (links and empty files do not count).
//! * [`Prompted`] wraps a [`Model`]. The loop keeps its conversation and its digest as they are; only the request
//!   that leaves is assembled. Wrap the redacting model, not the other way round, so credentials in a layer are
//!   masked too: `Prompted::new(RedactingModel::new(client, redactor), ..)`.

use crate::state::ProjectState;
use laris_config::settings::Context;
use laris_core::prompt::{
    Assembled, Budget, Compaction, Input, Layer, LayerSource, Pin, PinKind, assemble,
    estimate_tokens,
};
use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

/// The pinned items of a session; clones share one list, so the interface can pin while the loop runs.
#[derive(Clone, Debug, Default)]
pub struct PinBoard {
    pins: Arc<Mutex<Vec<Pin>>>,
}

impl PinBoard {
    /// An empty board.
    pub fn new() -> Self {
        Self::default()
    }

    /// Pins `text`; the same text of the same kind is kept once.
    pub fn pin(&self, kind: PinKind, text: &str) {
        let text = text.trim();
        if text.is_empty() {
            return;
        }
        let mut pins = self.pins.lock().unwrap_or_else(|e| e.into_inner());
        if !pins.iter().any(|p| p.kind == kind && p.text == text) {
            pins.push(Pin::new(kind, text));
        }
    }

    /// Removes the pin at `index` (0-based, in the order shown by [`PinBoard::list`]).
    pub fn unpin(&self, index: usize) -> bool {
        let mut pins = self.pins.lock().unwrap_or_else(|e| e.into_inner());
        if index < pins.len() {
            pins.remove(index);
            true
        } else {
            false
        }
    }

    /// The pins, oldest first.
    pub fn list(&self) -> Vec<Pin> {
        self.pins.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }
}

/// Where the layers are read from.
#[derive(Clone, Debug)]
pub struct Sources {
    /// The user's home (`~/.laris`).
    pub home: PathBuf,
    /// The project folder.
    pub project_root: PathBuf,
    /// Whether the project folder is trusted.
    pub state: ProjectState,
    /// The `extraInstructions` setting.
    pub extra_instructions: String,
}

fn read_capped(path: &Path, max_chars: usize) -> Option<String> {
    let meta = std::fs::symlink_metadata(path).ok()?;
    if !meta.is_file() {
        return None;
    }
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .ok()?
        .take((max_chars as u64).saturating_mul(4))
        .read_to_end(&mut bytes)
        .ok()?;
    let text = String::from_utf8_lossy(&bytes);
    let text: String = text.chars().take(max_chars).collect();
    (!text.trim().is_empty()).then_some(text)
}

/// The layers for one request: the user's, the project's and the memory notes, in that order.
pub fn load_layers(sources: &Sources, context: &Context) -> Vec<Layer> {
    let max_chars = usize::try_from(context.layer_max_chars).unwrap_or(usize::MAX);
    let mut layers = Vec::new();
    if let Some(text) = read_capped(&sources.home.join("LARIS.md"), max_chars) {
        layers.push(Layer {
            name: "LARIS.md (user)".to_owned(),
            source: LayerSource::User,
            text,
        });
    }
    let extra = sources.extra_instructions.trim();
    if !extra.is_empty() {
        layers.push(Layer {
            name: "Extra instructions (user)".to_owned(),
            source: LayerSource::User,
            text: extra.chars().take(max_chars).collect(),
        });
    }
    if !sources.state.trusted() {
        return layers;
    }
    let dot = sources.project_root.join(".laris");
    if let Some(text) = read_capped(&dot.join("LARIS.md"), max_chars) {
        layers.push(Layer {
            name: "LARIS.md (project)".to_owned(),
            source: LayerSource::Project,
            text,
        });
    }
    let mut notes: Vec<PathBuf> = std::fs::read_dir(dot.join("memory"))
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "md"))
        .collect();
    notes.sort();
    let limit = usize::try_from(context.memory_max_notes).unwrap_or(usize::MAX);
    let mut read = 0usize;
    for path in notes {
        if read >= limit {
            break;
        }
        let stem = path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        if let Some(text) = read_capped(&path, max_chars) {
            read += 1;
            layers.push(Layer {
                name: format!("memory/{stem}"),
                source: LayerSource::Memory,
                text,
            });
        }
    }
    layers
}

/// What the last request looked like.
#[derive(Clone, Debug, PartialEq)]
pub struct Report {
    /// Estimated tokens of the request.
    pub tokens: u64,
    /// The window.
    pub window: u64,
    /// Set when the conversation was compacted.
    pub compaction: Option<Compaction>,
    /// Layers that were cut to fit.
    pub trimmed: Vec<String>,
}

/// A [`Model`] that asks the wrapped model the assembled request instead of the bare conversation.
pub struct Prompted<M> {
    inner: M,
    sources: Sources,
    context: Context,
    pins: PinBoard,
    last: Option<Report>,
}

impl<M: Model> Prompted<M> {
    /// Wraps `inner`.
    pub fn new(inner: M, sources: Sources, context: Context, pins: PinBoard) -> Self {
        Self {
            inner,
            sources,
            context,
            pins,
            last: None,
        }
    }

    /// The wrapped model.
    pub fn inner(&self) -> &M {
        &self.inner
    }

    /// The wrapped model.
    pub fn inner_mut(&mut self) -> &mut M {
        &mut self.inner
    }

    /// The shared pins.
    pub fn pins(&self) -> &PinBoard {
        &self.pins
    }

    /// What the last request looked like, for the `usage` and `compact` events the client shows.
    pub fn last(&self) -> Option<&Report> {
        self.last.as_ref()
    }

    /// Assembles the request the wrapped model would be asked.
    pub fn assemble(&self, request: &ModelRequest<'_>) -> Result<Assembled, ModelError> {
        let tools_tokens = request
            .tools
            .iter()
            .map(|t| estimate_tokens(&serde_json::to_string(t).unwrap_or_default()))
            .sum();
        let budget = Budget::from_settings(&self.context, tools_tokens);
        let layers = load_layers(&self.sources, &self.context);
        let pins = self.pins.list();
        let input = Input {
            layers: &layers,
            pins: &pins,
            plan: request.note,
            conversation: request.messages,
        };
        assemble(&input, &budget).map_err(|e| ModelError::Failed(e.to_string()))
    }
}

impl<M: Model> Model for Prompted<M> {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let assembled = self.assemble(request)?;
        self.last = Some(Report {
            tokens: assembled.tokens,
            window: assembled.window,
            compaction: assembled.compaction.clone(),
            trimmed: assembled.trimmed.clone(),
        });
        self.inner.answer(&ModelRequest {
            messages: &assembled.messages,
            note: None,
            tools: request.tools,
        })
    }
}
