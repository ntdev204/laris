//! Core event protocol (SR-P3): commands from an interface to the core and events from the core to an
//! interface. The same messages travel over a channel inside one process ([`channel`]) and as JSON
//! lines ([`crate::jsonl`]) for headless `stream-json` and a later daemon.
//!
//! The message set is the generation-1 E1 set. Both ends are built from one version, so unknown fields are
//! refused; the version in [`Event::Ready`] guards against mixed builds ([`check_ready`]).

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fmt;
use std::sync::mpsc;

/// Version of the core event protocol spoken by this build.
pub const CORE_VERSION: &str = "1";

/// Event types, in wire order.
pub const EVENT_TYPES: [&str; 14] = [
    "login_required",
    "ready",
    "text",
    "tool_call",
    "tool_result",
    "plan",
    "permission_request",
    "status",
    "usage",
    "compact",
    "goal",
    "completion",
    "error",
    "done",
];

/// Command types, in wire order.
pub const COMMAND_TYPES: [&str; 8] = [
    "login",
    "user_message",
    "permission_response",
    "interrupt",
    "command",
    "set_mode",
    "complete",
    "shutdown",
];

/// Error codes that answer one command and are not followed by `done`.
pub const ENDS_COMMAND: [&str; 5] = [
    "unknown_command",
    "command_failed",
    "bad_command",
    "bad_mode",
    "busy",
];

/// Why a session cannot start yet.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum LoginReason {
    /// No server address is configured.
    NoServer,
    /// The certificate has to be confirmed by a person.
    UntrustedCertificate,
    /// The certificate differs from the confirmed one.
    CertificateMismatch,
    /// No API key.
    NoKey,
    /// The server refused the key.
    Rejected,
    /// The input is not usable.
    Invalid,
}

/// How long an approval lasts.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Scope {
    /// This call only.
    #[default]
    Once,
    /// This session.
    Session,
    /// This project.
    Project,
    /// Everywhere.
    Everywhere,
}

/// The user's decision on a permission request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    /// Allow.
    Allow,
    /// Deny.
    Deny,
}

/// Permission mode a front end can ask for; `next` cycles.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum Mode {
    /// Ask before risky calls.
    #[serde(rename = "default")]
    Default,
    /// Accept edits without asking.
    #[serde(rename = "acceptEdits")]
    AcceptEdits,
    /// Plan only.
    #[serde(rename = "plan")]
    Plan,
    /// Skip approvals.
    #[serde(rename = "bypass")]
    Bypass,
    /// The next mode in the cycle.
    #[serde(rename = "next")]
    Next,
}

/// What `/` or `@` completes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum Trigger {
    /// Slash commands.
    #[serde(rename = "/")]
    Slash,
    /// Files and skills.
    #[serde(rename = "@")]
    At,
}

/// Kind of a pasted attachment.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum AttachmentKind {
    /// An image, read by local OCR.
    Image,
    /// A long pasted text.
    Text,
}

/// A pasted image or long text kept by the interface.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Attachment {
    /// Image or text.
    pub kind: AttachmentKind,
    /// Display name.
    #[serde(default = "pasted")]
    pub name: String,
    /// Content, base64.
    pub data_base64: String,
}

fn pasted() -> String {
    "pasted".to_owned()
}

fn all_scopes() -> Vec<String> {
    ["once", "session", "project", "everywhere"]
        .map(str::to_owned)
        .to_vec()
}

/// One entry of a completion answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct CompletionItem {
    /// Text to insert.
    pub value: String,
    /// Short explanation.
    #[serde(default)]
    pub description: String,
}

/// Core to interface.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Event {
    /// Sent before `ready` when the session cannot start yet.
    LoginRequired {
        /// What is missing.
        reason: LoginReason,
        /// Server address, if known.
        #[serde(default)]
        server: String,
        /// SHA-256 a person compares for `untrusted_certificate`.
        #[serde(default)]
        fingerprint: String,
        /// Extra text.
        #[serde(default)]
        message: String,
    },
    /// The session is ready; carries the protocol version.
    Ready {
        /// Protocol version ([`CORE_VERSION`]).
        #[serde(default = "core_version")]
        version: String,
        /// Program version.
        engine: String,
        /// Conversation id.
        session: String,
        /// Working directory.
        cwd: String,
        /// Permission mode.
        mode: String,
        /// Server address, empty when none.
        #[serde(default)]
        server: String,
    },
    /// A piece of the answer.
    Text {
        /// The text.
        delta: String,
    },
    /// The model called a tool.
    ToolCall {
        /// Call id.
        id: String,
        /// Tool name.
        name: String,
        /// Arguments.
        #[serde(default)]
        arguments: Map<String, Value>,
    },
    /// A tool answered.
    ToolResult {
        /// Id of the call.
        id: String,
        /// Tool name.
        name: String,
        /// Result.
        #[serde(default)]
        result: Value,
    },
    /// The plan.
    Plan {
        /// Where it came from.
        #[serde(default)]
        source: String,
        /// Steps (`text`, `status`).
        #[serde(default)]
        steps: Vec<Map<String, Value>>,
    },
    /// A call needs approval.
    PermissionRequest {
        /// Request id.
        id: String,
        /// Tool name.
        tool: String,
        /// Arguments.
        #[serde(default)]
        arguments: Map<String, Value>,
        /// Why approval is needed.
        #[serde(default)]
        reason: String,
        /// The rule an "always allow" would save.
        #[serde(default)]
        rule: String,
        /// Unified diff of the change.
        #[serde(default)]
        diff: String,
        /// Scopes that may be chosen.
        #[serde(default = "all_scopes")]
        scopes: Vec<String>,
    },
    /// Progress that is not text.
    Status {
        /// `verify`, `reflect`, `brain`, `learning`, `mode`, `notice`, `line`, `queued`, `sandbox` ...
        kind: String,
        /// Values.
        #[serde(default)]
        data: Map<String, Value>,
    },
    /// Context use.
    Usage {
        /// Tokens in context.
        tokens: u64,
        /// Context window.
        window: u64,
    },
    /// The context was compacted.
    Compact {
        /// Tokens before.
        before: u64,
        /// Tokens after.
        after: u64,
        /// Turns summarised.
        #[serde(default)]
        summarized: u64,
        /// How.
        #[serde(default)]
        method: String,
    },
    /// Result of the completion check.
    Goal {
        /// Whether the goal is complete.
        complete: bool,
        /// Open items.
        #[serde(default)]
        open: Vec<Value>,
        /// Failed items.
        #[serde(default)]
        failed: Vec<Value>,
        /// Whether the core retries.
        #[serde(default)]
        retry: bool,
    },
    /// The answer to a `complete` command.
    Completion {
        /// Id of the command.
        id: String,
        /// Candidates.
        #[serde(default)]
        items: Vec<CompletionItem>,
    },
    /// A failure.
    Error {
        /// Code.
        code: String,
        /// Message.
        message: String,
    },
    /// The turn ended.
    Done {
        /// `completed`, `interrupted`, ...
        status: String,
        /// Final answer text.
        #[serde(default)]
        answer: String,
    },
}

fn core_version() -> String {
    CORE_VERSION.to_owned()
}

/// Interface to core.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    /// The answer to `login_required`.
    Login {
        /// Server address.
        #[serde(default, skip_serializing_if = "String::is_empty")]
        server: String,
        /// API key; never echoed back in an event.
        #[serde(default, skip_serializing_if = "String::is_empty")]
        key: String,
        /// Confirms the shown certificate fingerprint.
        #[serde(default, skip_serializing_if = "is_false")]
        trust: bool,
    },
    /// A user message.
    UserMessage {
        /// Text.
        text: String,
        /// Pasted attachments.
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        attachments: Vec<Attachment>,
    },
    /// The answer to a permission request.
    PermissionResponse {
        /// Request id.
        id: String,
        /// Allow or deny.
        decision: Decision,
        /// How long.
        #[serde(default)]
        scope: Scope,
        /// Remember the decision.
        #[serde(default, skip_serializing_if = "is_false")]
        remember: bool,
    },
    /// Stop the running turn.
    Interrupt {},
    /// A slash command; `name` has no slash.
    #[serde(rename = "command")]
    Slash {
        /// Command name.
        name: String,
        /// The rest of the line.
        #[serde(default)]
        args: String,
    },
    /// Change the permission mode.
    SetMode {
        /// The mode.
        mode: Mode,
    },
    /// Ask for completions.
    Complete {
        /// Id echoed in the answer.
        id: String,
        /// `/` or `@`.
        trigger: Trigger,
        /// Text typed after the trigger.
        #[serde(default)]
        text: String,
    },
    /// End the session.
    Shutdown {},
}

fn is_false(b: &bool) -> bool {
    !*b
}

impl Event {
    /// Wire name of the event.
    pub fn type_name(&self) -> &'static str {
        match self {
            Self::LoginRequired { .. } => "login_required",
            Self::Ready { .. } => "ready",
            Self::Text { .. } => "text",
            Self::ToolCall { .. } => "tool_call",
            Self::ToolResult { .. } => "tool_result",
            Self::Plan { .. } => "plan",
            Self::PermissionRequest { .. } => "permission_request",
            Self::Status { .. } => "status",
            Self::Usage { .. } => "usage",
            Self::Compact { .. } => "compact",
            Self::Goal { .. } => "goal",
            Self::Completion { .. } => "completion",
            Self::Error { .. } => "error",
            Self::Done { .. } => "done",
        }
    }

    /// True for an error that answers one command and is not followed by `done`.
    pub fn ends_command(&self) -> bool {
        matches!(self, Self::Error { code, .. } if ENDS_COMMAND.contains(&code.as_str()))
    }
}

impl Command {
    /// Wire name of the command.
    pub fn type_name(&self) -> &'static str {
        match self {
            Self::Login { .. } => "login",
            Self::UserMessage { .. } => "user_message",
            Self::PermissionResponse { .. } => "permission_response",
            Self::Interrupt {} => "interrupt",
            Self::Slash { .. } => "command",
            Self::SetMode { .. } => "set_mode",
            Self::Complete { .. } => "complete",
            Self::Shutdown {} => "shutdown",
        }
    }
}

/// The core reports another protocol version than this build speaks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionMismatch {
    /// What the core reported.
    pub reported: String,
}

impl fmt::Display for VersionMismatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "this front end speaks engine protocol E1 version {CORE_VERSION} but the engine reports {:?}; update the laris program and the front end together",
            self.reported
        )
    }
}

impl std::error::Error for VersionMismatch {}

/// Accepts a `ready` event of this version; any other event is accepted unchanged.
pub fn check_ready(event: &Event) -> Result<(), VersionMismatch> {
    match event {
        Event::Ready { version, .. } if version != CORE_VERSION => Err(VersionMismatch {
            reported: version.clone(),
        }),
        _ => Ok(()),
    }
}

/// The core's end of an in-process channel.
#[derive(Debug)]
pub struct CoreEnd {
    /// Commands from the interface.
    pub commands: mpsc::Receiver<Command>,
    /// Events to the interface.
    pub events: mpsc::Sender<Event>,
}

/// The interface's end of an in-process channel.
#[derive(Debug)]
pub struct InterfaceEnd {
    /// Commands to the core.
    pub commands: mpsc::Sender<Command>,
    /// Events from the core.
    pub events: mpsc::Receiver<Event>,
}

/// A connected pair for one process; the messages are the same ones the JSON lines carry.
pub fn channel() -> (InterfaceEnd, CoreEnd) {
    let (command_tx, command_rx) = mpsc::channel();
    let (event_tx, event_rx) = mpsc::channel();
    (
        InterfaceEnd {
            commands: command_tx,
            events: event_rx,
        },
        CoreEnd {
            commands: command_rx,
            events: event_tx,
        },
    )
}
