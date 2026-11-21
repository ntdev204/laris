//! The settings document (`~/.laris/settings.json`), shaped like Claude Code's.
//!
//! These types are the one source of the JSON Schema ([`schema`]); the committed copy lives in
//! `schema/settings.schema.json` and `cargo xtask schema --check` keeps it current. The file holds no secrets:
//! the API key is in the credentials file. Keys are camelCase.

use crate::catalogue::Language;
use crate::error::{ConfigError, ErrorKind};
use crate::validate;
use schemars::{JsonSchema, schema_for};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

/// Hook events, in firing order.
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

/// Where the client finds its own new releases. Updating is always on: with no address (a development build) there
/// is nothing to check. A release build carries both values (`LARIS_BUILD_DEFAULTS`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Update {
    /// Release address (`https://.../<version>/<file>` is a release file); empty for none.
    pub url: String,
    /// The release signing key, PEM or its base64 body; empty for none. A release is installed only when its
    /// checksum list is signed with this key.
    pub signature_verifier: String,
    /// Minutes between two checks while the client runs.
    #[schemars(extend("minimum" = 1))]
    pub interval_minutes: u64,
}

impl Default for Update {
    fn default() -> Self {
        Self {
            url: String::new(),
            signature_verifier: String::new(),
            interval_minutes: 360,
        }
    }
}

/// Permission mode and rules.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
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
    /// In `auto` mode, the calls that still ask: destructive commands. A list here replaces the default one.
    pub auto_ask: Vec<String>,
}

impl Default for Permissions {
    fn default() -> Self {
        Self {
            default_mode: PermissionMode::default(),
            allow: Vec::new(),
            ask: Vec::new(),
            deny: Vec::new(),
            additional_directories: Vec::new(),
            auto_ask: default_auto_ask(),
        }
    }
}

/// The guard of `auto` mode when the settings name none: privilege escalation, recursive deletion of `/`, `~`, the
/// home folder or a parent, history-changing git commands, and disk and power commands.
pub fn default_auto_ask() -> Vec<String> {
    [
        "Bash(sudo:*)",
        "Bash(su:*)",
        "Bash(doas:*)",
        "Bash(rm -[rRf]* /*)",
        "Bash(rm -[rRf]* ~*)",
        "Bash(rm -[rRf]* ..*)",
        "Bash(rm -[rRf]* $HOME*)",
        "Bash(git push:*)",
        "Bash(git reset --hard*)",
        "Bash(git clean:*)",
        "Bash(git branch -D:*)",
        "Bash(mkfs*)",
        "Bash(dd:*)",
        "Bash(chmod -R:*)",
        "Bash(chown -R:*)",
        "Bash(shutdown:*)",
        "Bash(reboot:*)",
        "Bash(poweroff:*)",
        "Bash(halt:*)",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

/// Permission mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
pub enum PermissionMode {
    /// Run reads, writes and commands without asking, except the calls `autoAsk` names.
    #[default]
    #[serde(rename = "auto")]
    Auto,
    /// Ask before writes and commands.
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

/// One MCP server the client starts as a child process and talks to over standard input and output.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct McpServer {
    /// Whether the server is started.
    pub enabled: bool,
    /// Program to run (for example `uvx` or `npx`).
    pub command: String,
    /// Arguments of the program.
    pub args: Vec<String>,
    /// Names of environment variables passed to the server; the values are read from this process's environment
    /// and never stored in the settings. The server is skipped while one of them is unset.
    pub env: Vec<String>,
    /// Seconds the start (handshake and tool list) may take; the first start may download the server.
    #[schemars(extend("minimum" = 1))]
    pub start_timeout_seconds: u64,
    /// Seconds one tool call may take.
    #[schemars(extend("minimum" = 1))]
    pub call_timeout_seconds: u64,
}

impl Default for McpServer {
    fn default() -> Self {
        Self {
            enabled: true,
            command: String::new(),
            args: Vec::new(),
            env: Vec::new(),
            start_timeout_seconds: 120,
            call_timeout_seconds: 60,
        }
    }
}

/// MCP servers (SR-H16): extra tools the user adds. None is configured by default. Read from the user's own settings only.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Mcp {
    /// Whether MCP servers are started at all.
    pub enabled: bool,
    /// Servers by name; the name becomes part of the tool names (`mcp__<name>__<tool>`).
    pub servers: BTreeMap<String, McpServer>,
}

impl Default for Mcp {
    fn default() -> Self {
        Self {
            enabled: true,
            servers: BTreeMap::new(),
        }
    }
}

/// The web tools `WebSearch` and `WebFetch` (SR-H17): they run in the client, with the client's address.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Web {
    /// Whether the web tools are offered.
    pub enabled: bool,
    /// Address of the HTML search page; the query is added as `q`. Empty turns `WebSearch` off.
    pub search_url: String,
    /// Seconds one request may take, redirects included.
    #[schemars(extend("minimum" = 1))]
    pub timeout_seconds: u64,
    /// Most bytes read from one page.
    #[schemars(extend("minimum" = 1024))]
    pub max_bytes: u64,
    /// Most redirects followed; every hop is checked again.
    pub max_redirects: u32,
    /// Most search results returned.
    #[schemars(extend("minimum" = 1))]
    pub max_results: u32,
    /// `User-Agent` sent.
    pub user_agent: String,
}

impl Default for Web {
    fn default() -> Self {
        Self {
            enabled: true,
            search_url: "https://html.duckduckgo.com/html/".to_owned(),
            timeout_seconds: 20,
            max_bytes: 2 * 1024 * 1024,
            max_redirects: 5,
            max_results: 8,
            user_agent: "Mozilla/5.0 (compatible; Laris)".to_owned(),
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

/// Context window, autocompact and the budget of the prompt layer.
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
    /// Fraction of the compaction trigger that compaction aims for.
    #[schemars(extend("exclusiveMinimum" = 0), range(max = 1))]
    pub compact_target: f64,
    /// Tokens kept free for the answer.
    pub reserve_tokens: u64,
    /// Share of the available tokens the `LARIS.md` layers and memory may take together.
    #[schemars(extend("exclusiveMinimum" = 0), range(max = 1))]
    pub layer_share: f64,
    /// Share of the available tokens the pinned items may take; they are never cut.
    #[schemars(extend("exclusiveMinimum" = 0), range(max = 1))]
    pub pinned_share: f64,
    /// Share of the available tokens the compaction summary may take.
    #[schemars(extend("exclusiveMinimum" = 0), range(max = 1))]
    pub summary_share: f64,
    /// Characters of a request or an answer kept in the compaction summary.
    #[schemars(range(min = 20))]
    pub summary_line_chars: u64,
    /// Characters read from one `LARIS.md` or memory file.
    #[schemars(range(min = 1))]
    pub layer_max_chars: u64,
    /// Memory notes read for a request.
    pub memory_max_notes: u64,
}

impl Default for Context {
    fn default() -> Self {
        Self {
            auto_compact: true,
            window_tokens: 32768,
            compact_threshold: 0.8,
            compact_target: 0.75,
            reserve_tokens: 4096,
            layer_share: 0.25,
            pinned_share: 0.25,
            summary_share: 0.15,
            summary_line_chars: 160,
            layer_max_chars: 20000,
            memory_max_notes: 50,
        }
    }
}

/// When the agent makes a visible plan.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum PlanMode {
    /// No plan, and `update_plan` is not offered.
    Off,
    /// A plan for requests of at least `minRequestWords` words.
    #[default]
    Auto,
    /// A plan for every request.
    Always,
}

/// Agentic planning: a visible, tracked plan for goals that take several steps.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct PlanSettings {
    /// When a plan is made.
    pub mode: PlanMode,
    /// `auto`: requests with at least this many words count as multi-step.
    #[schemars(range(min = 1))]
    pub min_request_words: u32,
    /// Most steps in a plan.
    #[schemars(range(min = 1, max = 30))]
    pub max_steps: u32,
    /// Longest text of a step, in characters.
    #[schemars(range(min = 20))]
    pub step_chars: u32,
}

impl Default for PlanSettings {
    fn default() -> Self {
        Self {
            mode: PlanMode::Auto,
            min_request_words: 12,
            max_steps: 12,
            step_chars: 240,
        }
    }
}

/// After each tool result the loop checks progress; a failed or empty step allows a bounded replan, and a goal
/// closes only when its plan is done.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Reflect {
    /// Check progress and completion.
    pub enabled: bool,
    /// Replans allowed in one turn.
    #[schemars(range(max = 5))]
    pub max_replans: u32,
    /// Times a goal with open steps is sent back to the model before it is reported open.
    #[schemars(range(max = 3))]
    pub completion_retries: u32,
    /// Error codes no change of approach can fix: the loop says so once instead of asking for a replan.
    pub permanent_errors: Vec<String>,
    /// Result keys whose empty value means the step found nothing.
    pub empty_keys: Vec<String>,
}

impl Default for Reflect {
    fn default() -> Self {
        Self {
            enabled: true,
            max_replans: 2,
            completion_retries: 2,
            permanent_errors: vec!["no_documents".to_owned()],
            empty_keys: ["hits", "passages", "results", "matches", "items"]
                .map(str::to_owned)
                .to_vec(),
        }
    }
}

/// Limits of the agent loop.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Agent {
    /// Model calls in one turn (the orchestration specification caps it at 10).
    #[schemars(range(min = 1, max = 10))]
    pub max_steps: u32,
    /// Longest time of one turn, in seconds.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub time_budget_seconds: f64,
    /// Tool calls run in one model step; more are refused.
    #[schemars(range(min = 1, max = 16))]
    pub max_tool_calls_per_step: u32,
    /// Planning.
    pub plan: PlanSettings,
    /// Reflection and completion check.
    pub reflect: Reflect,
}

impl Default for Agent {
    fn default() -> Self {
        Self {
            max_steps: 10,
            time_budget_seconds: 180.0,
            max_tool_calls_per_step: 4,
            plan: PlanSettings::default(),
            reflect: Reflect::default(),
        }
    }
}

/// Limits of the local tools (`Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `save_memory`, skills) and of every
/// tool result.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Tools {
    /// Time a `Bash` command gets when it names none, in seconds.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub bash_default_timeout_seconds: f64,
    /// Longest time a `Bash` command may ask for, in seconds.
    #[schemars(extend("exclusiveMinimum" = 0))]
    pub bash_max_timeout_seconds: f64,
    /// Characters of `Bash` output kept.
    #[schemars(range(min = 1))]
    pub bash_output_max_chars: u32,
    /// Lines `Read` returns at most.
    #[schemars(range(min = 1))]
    pub read_max_lines: u32,
    /// Files `Glob` lists at most.
    #[schemars(range(min = 1))]
    pub glob_max_results: u32,
    /// Matches `Grep` returns at most.
    #[schemars(range(min = 1))]
    pub grep_max_results: u32,
    /// Files larger than this are not searched by `Grep`, in bytes.
    #[schemars(range(min = 1))]
    pub grep_max_file_bytes: u64,
    /// Largest file `Read`, `Write` and `Edit` handle, in bytes.
    #[schemars(range(min = 1))]
    pub edit_max_bytes: u64,
    /// Edits kept for `/rewind`.
    #[schemars(range(min = 1))]
    pub checkpoint_keep: u32,
    /// Characters of one tool result, local or remote, passed to the model; more is cut.
    #[schemars(range(min = 1))]
    pub result_max_chars: u32,
    /// Characters of a skill's instructions kept.
    #[schemars(range(min = 1))]
    pub skill_max_chars: u32,
    /// File names (`*` and `?` match) that no tool reads or writes: secrets and keys.
    pub denied_files: Vec<String>,
}

impl Default for Tools {
    fn default() -> Self {
        Self {
            bash_default_timeout_seconds: 120.0,
            bash_max_timeout_seconds: 600.0,
            bash_output_max_chars: 30_000,
            read_max_lines: 2000,
            glob_max_results: 500,
            grep_max_results: 200,
            grep_max_file_bytes: 2_000_000,
            edit_max_bytes: 2_000_000,
            checkpoint_keep: 200,
            result_max_chars: 60_000,
            skill_max_chars: 20_000,
            denied_files: [
                ".env",
                ".env.*",
                "*.pem",
                "*.key",
                "id_rsa",
                "id_ed25519",
                ".netrc",
                ".npmrc",
                ".pypirc",
            ]
            .map(str::to_owned)
            .to_vec(),
        }
    }
}

/// The project vault: recording, writing and ingestion.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Vault {
    /// Record sessions in the vault.
    pub auto_record: bool,
    /// Longest note or note block LARIS writes, in characters.
    #[schemars(range(min = 1))]
    pub max_note_chars: u32,
    /// Note writes allowed in a minute; 0 for no limit.
    pub max_writes_per_minute: u32,
    /// Keep the text of a replaced block under `.laris/backups`.
    pub backup: bool,
    /// Largest document ingested, in bytes.
    #[schemars(range(min = 1))]
    pub ingest_max_bytes: u64,
    /// Longest passage cut from a document, in characters.
    #[schemars(range(min = 50))]
    pub passage_max_chars: u32,
    /// Passages `search_corpus` returns at most.
    #[schemars(range(min = 1))]
    pub search_max_results: u32,
}

impl Default for Vault {
    fn default() -> Self {
        Self {
            auto_record: true,
            max_note_chars: 60_000,
            max_writes_per_minute: 120,
            backup: true,
            ingest_max_bytes: 20_000_000,
            passage_max_chars: 1200,
            search_max_results: 10,
        }
    }
}

/// Learning data collection (kept on the machine, ADR-021 D40).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct Learning {
    /// Derive learning examples from sessions.
    pub collect: bool,
    /// Shortest final answer (characters) that becomes an example.
    pub min_answer_chars: u32,
    /// Longest tool result (characters) kept in an example; longer ones are cut.
    pub max_tool_result_chars: u32,
    /// Keep tool results in examples; otherwise they are replaced by `[omitted]`.
    pub store_tool_results: bool,
    /// Keep the passage text of retrieval examples; otherwise only identifiers and hashes.
    pub store_passage_text: bool,
    /// Rating an example needs to be exported (`none`: every one that was not rated down).
    pub export_min_rating: ExportRating,
    /// Names of the tools whose results are retrieval hits.
    pub retrieval_tools: Vec<String>,
}

impl Default for Learning {
    fn default() -> Self {
        Self {
            collect: true,
            min_answer_chars: 40,
            max_tool_result_chars: 3000,
            store_tool_results: true,
            store_passage_text: true,
            export_min_rating: ExportRating::None,
            retrieval_tools: vec!["search_corpus".to_owned()],
        }
    }
}

/// Which rated examples `laris learn export` writes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum ExportRating {
    /// Everything that was not rated down.
    #[default]
    None,
    /// Only what was rated up.
    Up,
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
    /// Agent loop limits.
    pub agent: Agent,
    /// Limits of the local tools and of tool results.
    pub tools: Tools,
    /// Vault recording.
    pub vault: Vault,
    /// Learning data.
    pub learning: Learning,
    /// Instructions appended to every prompt.
    pub extra_instructions: String,
    /// Days to keep session data; 0 keeps none.
    pub cleanup_period_days: u32,
    /// Automatic updates of the client (always on; this says where the releases are).
    pub update: Update,
    /// MCP servers.
    pub mcp: Mcp,
    /// Web tools.
    pub web: Web,
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
            agent: Agent::default(),
            tools: Tools::default(),
            vault: Vault::default(),
            learning: Learning::default(),
            extra_instructions: String::new(),
            cleanup_period_days: 30,
            update: Update::default(),
            mcp: Mcp::default(),
            web: Web::default(),
        }
    }
}

/// JSON Schema of [`Settings`]: deterministic (sorted keys).
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
        if !self.web.search_url.is_empty()
            && !self.web.search_url.starts_with("https://")
            && !self.web.search_url.starts_with("http://")
        {
            return Err(ConfigError::at("web.searchUrl", ErrorKind::UrlScheme));
        }
        if !self.update.url.is_empty() && !self.update.url.starts_with("https://") {
            return Err(ConfigError::at("update.url", ErrorKind::UrlScheme));
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
