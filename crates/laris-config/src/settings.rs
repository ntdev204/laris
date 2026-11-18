//! The settings document (`~/.laris/settings.json`), shaped like Claude Code's and compatible with generation 1.
//!
//! These types are the one source of the JSON Schema ([`schema`]); the committed copy lives in
//! `schema/settings.schema.json` and `cargo xtask schema --check` keeps it current. The file holds no secrets:
//! the API key is in the credentials file. Keys are camelCase as in generation 1.

use crate::catalogue::Language;
use crate::error::{ConfigError, ErrorKind};
use crate::validate;
use schemars::{JsonSchema, schema_for};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

/// Hook events, in generation-1 order.
pub const HOOK_EVENTS: [&str; 5] = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
];

/// Server connection.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Server {
    /// Server address; empty until the user or the package sets it.
    pub url: String,
    /// `sha256:<hex>` of the pinned private certificate; empty for none.
    pub ca_fingerprint: String,
    /// File holding the certificate of the pinned authority (PEM or DER); empty for none. Needed when
    /// `caFingerprint` is set: the fingerprint is checked against this file.
    pub ca_certificate_file: String,
    /// Longest wait for the answer headers of one attempt, in seconds.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub timeout_seconds: f64,
    /// Longest silence inside a streamed or downloaded body, in seconds.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub idle_timeout_seconds: f64,
    /// Extra attempts after the first, before a stream has started.
    pub max_retries: u32,
    /// Wait before the first retry, in seconds; doubles each time.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub retry_backoff_seconds: f64,
    /// Longest wait between retries, in seconds; a `Retry-After` of the server is cut to this.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub retry_backoff_max_seconds: f64,
    /// Largest accepted stream event or JSON answer, in bytes.
    #[schemars(extend("minimum" = 1))]
    pub max_response_bytes: u64,
}

impl Default for Server {
    fn default() -> Self {
        Self {
            url: String::new(),
            ca_fingerprint: String::new(),
            ca_certificate_file: String::new(),
            timeout_seconds: 120.0,
            idle_timeout_seconds: 60.0,
            max_retries: 3,
            retry_backoff_seconds: 1.0,
            retry_backoff_max_seconds: 30.0,
            max_response_bytes: 16 * 1024 * 1024,
        }
    }
}

/// Permission mode and rules.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Permissions {
    /// Mode when a rule does not decide.
    pub default_mode: PermissionMode,
    /// Rules that allow.
    pub allow: Vec<String>,
    /// Rules that ask.
    pub ask: Vec<String>,
    /// Rules that deny.
    pub deny: Vec<String>,
    /// Directories outside the project that tools may touch.
    pub additional_directories: Vec<String>,
}

/// Permission mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
pub enum PermissionMode {
    /// Ask before writes and commands.
    #[default]
    #[serde(rename = "default")]
    Default,
    /// Accept file edits without asking.
    #[serde(rename = "acceptEdits")]
    AcceptEdits,
    /// Plan only; deny changes.
    #[serde(rename = "plan")]
    Plan,
    /// Skip permission prompts.
    #[serde(rename = "bypass")]
    Bypass,
}

/// A command hook.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct HookCommand {
    /// Always `command`.
    #[serde(default = "command_kind", rename = "type")]
    #[schemars(extend("const" = "command"))]
    pub kind: String,
    /// Shell command.
    #[schemars(length(min = 1))]
    pub command: String,
    /// Timeout in seconds.
    #[serde(default = "thirty")]
    #[schemars(extend("exclusiveMinimum" = 0), range(max = 600))]
    pub timeout: f64,
}

fn command_kind() -> String {
    "command".to_owned()
}

fn thirty() -> f64 {
    30.0
}

/// Hooks that run for tools matching `matcher`.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields, default)]
pub struct HookMatcher {
    /// Tool-name pattern; empty matches all.
    pub matcher: String,
    /// Commands to run.
    pub hooks: Vec<HookCommand>,
}

/// Status line command.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct StatusLine {
    /// Always `command`.
    #[serde(default = "command_kind", rename = "type")]
    #[schemars(extend("const" = "command"))]
    pub kind: String,
    /// Shell command.
    #[schemars(length(min = 1))]
    pub command: String,
}

/// Sandbox for code the model runs.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Sandbox {
    /// Python version of the sandbox.
    pub python: String,
    /// Packages preinstalled in the sandbox.
    pub packages: Vec<String>,
    /// Whether the sandbox inherits the environment.
    pub inherit_env: bool,
    /// Package index address; empty for the default.
    pub index_url: String,
    /// Where to fetch the interpreter; empty for the default.
    pub python_source: String,
}

impl Default for Sandbox {
    fn default() -> Self {
        Self {
            python: "3.12".to_owned(),
            packages: Vec::new(),
            inherit_env: false,
            index_url: String::new(),
            python_source: String::new(),
        }
    }
}

/// Terminal interface.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Ui {
    /// Colour theme.
    pub theme: Theme,
    /// Language of the interface messages ([`crate::Catalogue`]).
    pub language: Language,
    /// Render Markdown.
    pub markdown: bool,
    /// Show the spinner.
    pub spinner: bool,
    /// Show the status line.
    pub show_status_line: bool,
}

impl Default for Ui {
    fn default() -> Self {
        Self {
            theme: Theme::Auto,
            language: Language::En,
            markdown: true,
            spinner: true,
            show_status_line: true,
        }
    }
}

/// Colour theme.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum Theme {
    /// Follow the terminal.
    #[default]
    Auto,
    /// Light.
    Light,
    /// Dark.
    Dark,
}

/// Context window and autocompact.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Context {
    /// Compact automatically near the limit.
    pub auto_compact: bool,
    /// Window size in tokens.
    #[schemars(range(min = 1024))]
    pub window_tokens: u64,
    /// Fraction of the window at which compaction starts.
    #[schemars(extend("exclusiveMinimum" = 0), range(max = 1))]
    pub compact_threshold: f64,
}

impl Default for Context {
    fn default() -> Self {
        Self {
            auto_compact: true,
            window_tokens: 32768,
            compact_threshold: 0.8,
        }
    }
}

/// Vault recording.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Vault {
    /// Record sessions in the vault.
    pub auto_record: bool,
}

impl Default for Vault {
    fn default() -> Self {
        Self { auto_record: true }
    }
}

/// Learning data collection (kept on the machine, ADR-021 D40).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Learning {
    /// Derive learning examples from sessions.
    pub collect: bool,
}

impl Default for Learning {
    fn default() -> Self {
        Self { collect: true }
    }
}

/// The settings document.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Settings {
    /// Schema reference, kept for editors.
    #[serde(rename = "$schema", skip_serializing_if = "Option::is_none")]
    pub schema: Option<String>,
    /// Server connection.
    pub server: Server,
    /// Model name sent to the server; empty for the server default.
    pub model: String,
    /// Terminal interface.
    pub ui: Ui,
    /// Permissions.
    pub permissions: Permissions,
    /// Environment variables set for tools and hooks.
    pub env: BTreeMap<String, String>,
    /// Hooks by event; events are listed in [`HOOK_EVENTS`].
    pub hooks: BTreeMap<String, Vec<HookMatcher>>,
    /// Status line command.
    pub status_line: Option<StatusLine>,
    /// Sandbox.
    pub sandbox: Sandbox,
    /// Context window.
    pub context: Context,
    /// Vault recording.
    pub vault: Vault,
    /// Learning data.
    pub learning: Learning,
    /// Instructions appended to every prompt.
    pub extra_instructions: String,
    /// Days to keep session data; 0 keeps none.
    pub cleanup_period_days: u32,
    /// Check for updates.
    pub auto_updates: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            schema: None,
            server: Server::default(),
            model: String::new(),
            ui: Ui::default(),
            permissions: Permissions::default(),
            env: BTreeMap::new(),
            hooks: BTreeMap::new(),
            status_line: None,
            sandbox: Sandbox::default(),
            context: Context::default(),
            vault: Vault::default(),
            learning: Learning::default(),
            extra_instructions: String::new(),
            cleanup_period_days: 30,
            auto_updates: true,
        }
    }
}

/// JSON Schema of [`Settings`]: deterministic (sorted keys), with generation-1's title.
pub fn schema() -> Value {
    let mut value = serde_json::to_value(schema_for!(Settings)).unwrap_or(Value::Null);
    if let Some(map) = value.as_object_mut() {
        map.insert(
            "title".to_owned(),
            Value::from("LARIS client settings (~/.laris/settings.json)"),
        );
    }
    value
}

/// [`schema`] as pretty JSON with a final newline: the content of the committed schema file.
pub fn schema_string() -> String {
    let mut text = serde_json::to_string_pretty(&schema()).unwrap_or_default();
    text.push('\n');
    text
}

/// A server address as a person types it, made complete: `https://` when no scheme is given and the API
/// prefix `/v1` when there is no path (`laris.example.com` becomes `https://laris.example.com/v1`).
pub fn server_address(url: &str) -> String {
    let url = url.trim().trim_end_matches('/');
    if url.is_empty() {
        return String::new();
    }
    let mut full = if url.contains("://") {
        url.to_owned()
    } else {
        format!("https://{url}")
    };
    let after_scheme = full.split_once("://").map_or("", |(_, rest)| rest);
    if !after_scheme.contains('/') {
        full.push_str("/v1");
    }
    full
}

fn is_fingerprint(text: &str) -> bool {
    text.is_empty()
        || text.strip_prefix("sha256:").is_some_and(|hex| {
            hex.len() == 64
                && hex
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
}

impl Settings {
    /// Validates `value` against the schema, then the rules a schema does not say, and returns the typed
    /// settings. The error names the JSON path of the first problem.
    pub fn from_value(value: &Value) -> Result<Self, ConfigError> {
        validate::check(&schema(), value)?;
        let mut settings: Settings = serde_json::from_value(value.clone()).map_err(|e| {
            ConfigError::at(
                "",
                ErrorKind::InvalidJson {
                    detail: e.to_string(),
                },
            )
        })?;
        settings.check()?;
        settings.server.url = settings.server.url.trim_end_matches('/').to_owned();
        Ok(settings)
    }

    /// Rules beyond the schema: the server address and fingerprint forms and the hook event names.
    pub fn check(&self) -> Result<(), ConfigError> {
        let url = &self.server.url;
        if !url.is_empty() && !url.starts_with("http://") && !url.starts_with("https://") {
            return Err(ConfigError::at("server.url", ErrorKind::UrlScheme));
        }
        if !is_fingerprint(&self.server.ca_fingerprint) {
            return Err(ConfigError::at(
                "server.caFingerprint",
                ErrorKind::FingerprintFormat,
            ));
        }
        if let Some(event) = self
            .hooks
            .keys()
            .find(|k| !HOOK_EVENTS.contains(&k.as_str()))
        {
            return Err(ConfigError::at(
                format!("hooks.{event}"),
                ErrorKind::UnknownHookEvent {
                    event: event.clone(),
                    known: HOOK_EVENTS.join(", "),
                },
            ));
        }
        Ok(())
    }
}
