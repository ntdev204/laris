//! The policy gateway (SR-S4): a [`Backend`] that stands between the HTTP layer and the model.
//!
//! The client sends what belongs to the user: the conversation, its tool schemas and its own layers. The gateway
//! adds what belongs to the system — the system prompt composed from `.laris/`, the workflow — narrows the tools to
//! the workflow's list, calls the model behind it, and filters what comes back: reasoning goes to the operator's
//! [`ReasoningSink`] and never to the client, credentials and internal text are hidden or stopped, and tool calls
//! that repeat internal text are dropped. Nothing of `.laris/` is sent back. The gateway keeps no per-user state.

use super::compose::{Composer, Inputs};
use super::guard::{Guard, StreamGuard};
use super::reasoning::{ReasoningRecord, ReasoningSink, TagPair, ThinkSplitter};
use super::skills::SKILL_TOOL;
use super::workflows::Workflows;
use crate::backend::{Backend, ChunkStream, StreamFailure};
use crate::brain::{BRAIN_TOOL, Consulted};
use crate::error::ApiError;
use futures_util::StreamExt;
use futures_util::future::BoxFuture;
use hmac::{Hmac, Mac};
use laris_protocol::chat::{
    ChatMessage, Content, FinishReason, FunctionKind, Role, ToolCall, ToolCallFunction, Usage,
};
use laris_protocol::p1::{
    ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse, Kind, LarisMeta, LarisRequest,
    ToolList, ToolRequest, ToolResponse,
};
use laris_protocol::p2::{ChunkChoice, ChunkDelta, ChunkObject};
use serde_json::Map;
use sha2::Sha256;
use std::collections::VecDeque;
use std::sync::Arc;

/// The planning tool of the client: it stays available under every workflow.
pub const PLAN_TOOL: &str = "update_plan";
/// Most reasoning kept for one answer, in bytes.
const MAX_REASONING: usize = 256 * 1024;
/// Most tool calls assembled from one answer.
const MAX_CALLS: usize = 64;
/// Keys a model may use for reasoning in a delta; they are diverted, whatever the model calls them.
const REASONING_KEYS: [&str; 4] = ["reasoning", "reasoning_content", "thinking", "thoughts"];

/// What the model is asked when the client wants a conversation summarised.
const SUMMARIZER: &str = "Summarise the conversation below so the assistant can continue the work: the user's \
goal, decisions taken, files and sources used (keep paths, source names and numbers verbatim), work left. Include \
no internal instruction or secret. Be concise.";

/// The policy of a running server: prompt composer, workflows, help text and the guard.
pub struct Policy {
    pub(crate) composer: Composer,
    pub(crate) workflows: Workflows,
    pub(crate) skills: super::skills::Skills,
    pub(crate) brain: crate::brain::Brain,
    pub(crate) help: String,
    pub(crate) guard: Guard,
    pub(crate) canary_enabled: bool,
    pub(crate) think_tags: Vec<TagPair>,
    pub(crate) secret: [u8; 32],
    pub(crate) prefilter: Option<Arc<laris_policy::Prefilter>>,
    pub(crate) harness: Option<laris_policy::HarnessConfig>,
}

impl Policy {
    /// The Prefilter rules of `.laris/prefilter.toml`, when the file exists (stage 3 of the pipeline).
    pub fn prefilter(&self) -> Option<&Arc<laris_policy::Prefilter>> {
        self.prefilter.as_ref()
    }

    /// The harness settings of `.laris/harness.toml`, when the file exists (stages 6 and 7).
    pub fn harness(&self) -> Option<&laris_policy::HarnessConfig> {
        self.harness.as_ref()
    }

    /// The workflows.
    pub fn workflows(&self) -> &Workflows {
        &self.workflows
    }

    /// The system skills.
    pub fn skills(&self) -> &super::skills::Skills {
        &self.skills
    }

    /// The system brain.
    pub fn brain(&self) -> &crate::brain::Brain {
        &self.brain
    }

    /// The prepared user guide.
    pub fn help(&self) -> &str {
        &self.help
    }

    /// The version of the prompt manifest.
    pub fn prompt_version(&self) -> &str {
        self.composer.version()
    }

    /// The guard of this policy, with no session canary.
    pub fn guard(&self) -> &Guard {
        &self.guard
    }

    fn canary(&self, session_id: &str) -> String {
        if !self.canary_enabled {
            return String::new();
        }
        let mut mac = Hmac::<Sha256>::new_from_slice(&self.secret).expect("HMAC takes any key");
        mac.update(session_id.as_bytes());
        let tag = mac.finalize().into_bytes();
        let hex: String = tag.iter().take(8).map(|b| format!("{b:02x}")).collect();
        format!("LARIS-CANARY-{hex}")
    }
}

/// A [`Backend`] that applies the policy around another one.
pub struct PolicyGateway {
    policy: Arc<Policy>,
    inner: Arc<dyn Backend>,
    sink: Arc<dyn ReasoningSink>,
}

impl PolicyGateway {
    /// Puts `policy` in front of `inner`; reasoning goes to `sink`.
    pub fn new(policy: Arc<Policy>, inner: Arc<dyn Backend>, sink: Arc<dyn ReasoningSink>) -> Self {
        Self {
            policy,
            inner,
            sink,
        }
    }
}

/// A date as `YYYY-MM-DD` (UTC) from seconds since the epoch.
fn date_of(secs: u64) -> String {
    let (y, m, d) = civil((secs / 86_400) as i64);
    format!("{y:04}-{m:02}-{d:02}")
}

pub(crate) fn today() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    date_of(secs)
}

/// Days since 1970-01-01 to a calendar date (proleptic Gregorian).
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = yoe + era * 400 + i64::from(m <= 2);
    (y, m, d)
}

fn text_of(message: &ChatMessage) -> String {
    match &message.content {
        Some(Content::Text(t)) => t.clone(),
        Some(Content::Parts(parts)) => parts
            .iter()
            .filter_map(|p| p.get("text").and_then(|t| t.as_str()))
            .collect::<Vec<_>>()
            .join("\n"),
        None => String::new(),
    }
}

fn system_message(text: String) -> ChatMessage {
    ChatMessage {
        role: Role::System,
        content: Some(Content::Text(text)),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }
}

fn session_of(request: &ChatRequest) -> Result<String, ApiError> {
    match &request.laris.session_id {
        Some(id) => Ok(id.clone()),
        None => {
            let bytes = crate::access::random_bytes(6).map_err(|_| ApiError::Internal)?;
            Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
        }
    }
}

impl PolicyGateway {
    /// The request the model sees: system prompt first, the client's conversation after, and only the tools the
    /// workflow allows.
    fn shape(
        &self,
        request: ChatRequest,
        caller: Option<&str>,
    ) -> Result<(ChatRequest, Prepared), ApiError> {
        let policy = &*self.policy;
        let session = session_of(&request)?;
        // a client can never supply the system prompt
        let mut messages: Vec<ChatMessage> = request
            .messages
            .into_iter()
            .filter(|m| m.role != Role::System)
            .collect();
        if messages.is_empty() {
            return Err(ApiError::BadRequest(
                "invalid request: messages must not be empty".into(),
            ));
        }
        let laris = request.laris;
        let canary = policy.canary(&session);
        if laris.kind == Kind::Summarize {
            let mut ask = SUMMARIZER.to_owned();
            if !laris.focus.trim().is_empty() {
                let focus: String = laris.focus.chars().take(400).collect();
                ask.push_str(&format!("\nPrioritise: {focus}"));
            }
            let last_user = messages.iter().rposition(|m| m.role == Role::User);
            let user = last_user.map(|i| messages.swap_remove(i));
            let sent = ChatRequest {
                messages: std::iter::once(system_message(ask)).chain(user).collect(),
                tools: Vec::new(),
                stream: true,
                laris: LarisRequest {
                    kind: Kind::Summarize,
                    session_id: Some(session.clone()),
                    ..LarisRequest::default()
                },
                extra: Map::new(),
            };
            return Ok((
                sent,
                self.prepared(session, String::new(), &canary, false, caller),
            ));
        }
        let latest = messages
            .iter()
            .rev()
            .find(|m| m.role == Role::User)
            .map(text_of)
            .unwrap_or_default();
        // the workflow the client names, else the one whose trigger the user's latest message contains
        let (workflow, request_text) = match &laris.workflow {
            None => (policy.workflows.triggered_by(&latest), latest.clone()),
            Some(w) => (
                Some(policy.workflows.get(&w.name).ok_or_else(|| {
                    ApiError::BadRequest("invalid request: unknown workflow".into())
                })?),
                w.request.clone(),
            ),
        };
        let workflow_text = workflow.map_or_else(String::new, |found| {
            let request_text: String = request_text.chars().take(2_000).collect();
            found.render(&request_text, policy.composer.settings().workflow_max_chars)
        });
        // a skill the user named loads before the first step; any other is loaded by the model when it needs it
        let skill_tool_allowed = policy.skills.offered()
            && workflow.is_none_or(|w| w.allowed_tools.iter().any(|t| t == SKILL_TOOL));
        let named = if skill_tool_allowed {
            policy.skills.named(&latest)
        } else {
            None
        };
        let skills_index = if skill_tool_allowed {
            let budget = policy.composer.settings().skills_index_chars;
            let mut index = policy.skills.index(budget);
            if !laris.layers.skills_index.trim().is_empty() {
                index.push('\n');
                index.push_str(&laris.layers.skills_index);
            }
            index
        } else {
            laris.layers.skills_index.clone()
        };
        let brain_tool_allowed = policy.brain.offered()
            && workflow.is_none_or(|w| w.allowed_tools.iter().any(|t| t == BRAIN_TOOL));
        let brief = workflow.and_then(|w| policy.brain.brief(&w.name));
        let own: Vec<(String, String)> = laris
            .layers
            .instructions
            .iter()
            .map(|i| (i.label.clone(), i.text.clone()))
            .collect();
        let composed = policy.composer.compose(&Inputs {
            session_id: &session,
            canary: &canary,
            date: &today(),
            extra: &laris.layers.extra,
            workflow: &workflow_text,
            skills_index: &skills_index,
            memory: &laris.layers.memory,
            own: &own,
            skill: named.map(|k| (k.name.as_str(), k.body.as_str())),
            brain: brief.as_ref().map(|b| (b.route.as_str(), b.text.as_str())),
        });
        let mut tools: Vec<_> = request
            .tools
            .into_iter()
            // the server's own tool is the server's: a client cannot offer one under that name
            .filter(|t| t.function.name != SKILL_TOOL && t.function.name != BRAIN_TOOL)
            .filter(|t| {
                workflow.is_none_or(|w| {
                    t.function.name == PLAN_TOOL || w.allowed_tools.contains(&t.function.name)
                })
            })
            .collect();
        if skill_tool_allowed
            && let Ok(schema) = serde_json::from_value(policy.skills.tool_schema())
        {
            tools.push(schema);
        }
        if brain_tool_allowed && let Ok(schema) = serde_json::from_value(policy.brain.tool_schema())
        {
            tools.push(schema);
        }
        messages.insert(0, system_message(composed.text));
        let sent = ChatRequest {
            messages,
            tools,
            stream: true,
            laris: LarisRequest {
                kind: Kind::Turn,
                session_id: Some(session.clone()),
                ..LarisRequest::default()
            },
            extra: Map::new(),
        };
        let mut prepared = self.prepared(session, composed.sha256, &canary, true, caller);
        prepared.skills = named.map(|k| k.name.clone()).into_iter().collect();
        prepared.skill_tool = skill_tool_allowed;
        prepared.brain_tool = brain_tool_allowed;
        prepared.brain = brief.map(|b| b.titles).unwrap_or_default();
        Ok((sent, prepared))
    }

    fn prepared(
        &self,
        session: String,
        sha: String,
        canary: &str,
        tools: bool,
        caller: Option<&str>,
    ) -> Prepared {
        let guard = Guard::new(
            self.policy.guard.redactor.clone(),
            self.policy.guard.leak.with_canary(canary),
            self.policy.guard.holdback(),
        );
        Prepared {
            key_id: caller.unwrap_or_default().to_owned(),
            session,
            prompt_sha256: sha,
            guard,
            tags: self.policy.think_tags.clone(),
            skills: Vec::new(),
            skill_tool: false,
            brain_tool: false,
            brain: Vec::new(),
            tools,
        }
    }
}

#[derive(Clone)]
struct Prepared {
    key_id: String,
    session: String,
    prompt_sha256: String,
    guard: Guard,
    tags: Vec<TagPair>,
    /// Names of the skills the user named, loaded before the first step.
    skills: Vec<String>,
    /// Whether the model may load system skills.
    skill_tool: bool,
    /// Whether the model may consult the system brain.
    brain_tool: bool,
    /// Titles of the brain notes the brief in the prompt drew on.
    brain: Vec<String>,
    /// Whether tool calls may be passed on (a summary has none).
    tools: bool,
}

impl Backend for PolicyGateway {
    fn chat(&self, request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        self.chat_for(request, None)
    }

    fn chat_for(
        &self,
        request: ChatRequest,
        caller: Option<&str>,
    ) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        let shaped = self.shape(request, caller);
        let inner = self.inner.clone();
        let sink = self.sink.clone();
        let policy = self.policy.clone();
        Box::pin(async move {
            let (sent, prepared) = shaped?;
            let stream = inner.chat(sent.clone()).await?;
            Ok(filtered(stream, sent, prepared, inner, policy, sink))
        })
    }

    fn embed(&self, request: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        self.inner.embed(request)
    }

    fn tools(&self) -> BoxFuture<'static, Result<ToolList, ApiError>> {
        self.inner.tools()
    }

    fn tool(
        &self,
        name: String,
        request: ToolRequest,
    ) -> BoxFuture<'static, Result<ToolResponse, ApiError>> {
        self.inner.tool(name, request)
    }
}

/// One tool call being assembled from streamed pieces.
#[derive(Default)]
struct Call {
    id: Option<String>,
    name: String,
    arguments: String,
}

/// The state of one answer on its way through the guard.
struct Filter {
    prepared: Prepared,
    visible: String,
    usage: Option<Usage>,
    pending: Option<Vec<Call>>,
    splitter: ThinkSplitter,
    stream: StreamGuard,
    base_id: String,
    model: String,
    calls: Vec<Call>,
    reasoning: String,
    ended: bool,
}

impl Filter {
    fn new(prepared: Prepared, base_id: String) -> Self {
        let splitter = ThinkSplitter::new(&prepared.tags);
        let stream = prepared.guard.stream();
        Self {
            base_id,
            visible: String::new(),
            usage: None,
            pending: None,
            prepared,
            splitter,
            stream,
            model: String::new(),
            calls: Vec::new(),
            reasoning: String::new(),
            ended: false,
        }
    }

    fn keep_reasoning(&mut self, text: &str) {
        if self.reasoning.len() < MAX_REASONING {
            let room = MAX_REASONING - self.reasoning.len();
            let take: String = text.chars().take(room).collect();
            self.reasoning.push_str(&take);
        }
    }

    fn chunk(&self, delta: ChunkDelta, finish: Option<FinishReason>) -> ChatResponseChunk {
        ChatResponseChunk {
            id: self.base_id.clone(),
            object: ChunkObject::default(),
            model: self.model.clone(),
            laris: None,
            choices: vec![ChunkChoice {
                index: 0,
                delta,
                finish_reason: finish,
                extra: Map::new(),
            }],
            usage: None,
            extra: Map::new(),
        }
    }

    fn text_chunks(&mut self, pieces: Vec<String>) -> Vec<ChatResponseChunk> {
        self.visible.extend(pieces.iter().map(String::as_str));
        pieces
            .into_iter()
            .map(|p| {
                self.chunk(
                    ChunkDelta {
                        content: Some(p),
                        ..ChunkDelta::default()
                    },
                    None,
                )
            })
            .collect()
    }

    /// Everything the guard still holds, as visible text.
    fn flush_text(&mut self) -> Vec<ChatResponseChunk> {
        let rest = self.splitter.finish();
        let mut pieces = self.stream.feed(&rest);
        pieces.extend(self.stream.finish());
        let thought = self.splitter.take_reasoning();
        self.keep_reasoning(&thought);
        self.text_chunks(pieces)
    }

    fn push(&mut self, mut chunk: ChatResponseChunk) -> Vec<ChatResponseChunk> {
        // one id for the whole answer, the gateway's own
        if !chunk.model.is_empty() {
            self.model.clone_from(&chunk.model);
        }
        if chunk.choices.is_empty() {
            // the evidence list and the usage event carry no text; usage is summed over the steps of the answer
            if let Some(u) = chunk.usage.take() {
                let total = self.usage.get_or_insert_with(Usage::default);
                total.prompt_tokens += u.prompt_tokens;
                total.completion_tokens += u.completion_tokens;
                total.total_tokens += u.total_tokens;
            }
            if chunk.laris.is_none() {
                return Vec::new();
            }
            chunk.extra = Map::new();
            chunk.id.clone_from(&self.base_id);
            return vec![chunk];
        }
        let mut out = Vec::new();
        let Some(choice) = chunk.choices.into_iter().find(|c| c.index == 0) else {
            return out;
        };
        let ChunkChoice {
            delta,
            finish_reason,
            ..
        } = choice;
        if let Some(r) = delta.reasoning_content {
            self.keep_reasoning(&r);
        }
        for key in REASONING_KEYS {
            if let Some(serde_json::Value::String(r)) = delta.extra.get(key) {
                let r = r.clone();
                self.keep_reasoning(&r);
            }
        }
        for tc in delta.tool_calls {
            self.take_call(tc);
        }
        if let Some(text) = delta.content
            && !text.is_empty()
            && !self.ended
        {
            let visible = self.splitter.feed(&text);
            let thought = self.splitter.take_reasoning();
            self.keep_reasoning(&thought);
            let pieces = self.stream.feed(&visible);
            out.extend(self.text_chunks(pieces));
        }
        if let Some(reason) = finish_reason
            && !self.ended
        {
            self.ended = true;
            out.extend(self.flush_text());
            out.extend(self.close(reason));
        }
        out
    }

    fn take_call(&mut self, tc: ToolCall) {
        // a delta with an index belongs to that call; without one, an id opens a new call and anything else
        // continues the last
        let slot = match tc.index {
            Some(i) => i as usize,
            None if tc.id.is_some() || self.calls.is_empty() => self.calls.len(),
            None => self.calls.len() - 1,
        };
        if slot >= MAX_CALLS {
            return;
        }
        while self.calls.len() <= slot {
            self.calls.push(Call::default());
        }
        let call = &mut self.calls[slot];
        if tc.id.is_some() {
            call.id = tc.id;
        }
        if !tc.function.name.is_empty() {
            call.name = tc.function.name;
        }
        call.arguments.push_str(&tc.function.arguments);
    }

    /// The tool calls (those that do not repeat internal text) and the finish event. A turn that only asks for
    /// system skills is not finished: the calls are kept for the server to answer.
    fn close(&mut self, reason: FinishReason) -> Vec<ChatResponseChunk> {
        let mut out = Vec::new();
        let calls = std::mem::take(&mut self.calls);
        let mut wire = Vec::new();
        let mut mine = Vec::new();
        if !self.stream.blocked && self.prepared.tools {
            for (i, c) in calls.into_iter().enumerate() {
                if c.name.is_empty() || self.prepared.guard.leak.leaked(&c.arguments) {
                    continue;
                }
                if (self.prepared.skill_tool && c.name == SKILL_TOOL)
                    || (self.prepared.brain_tool && c.name == BRAIN_TOOL)
                {
                    mine.push(c);
                    continue;
                }
                let (name_ok, _) = self.prepared.guard.redactor.redact(&c.name);
                wire.push(ToolCall {
                    index: Some(i as u32),
                    id: c.id,
                    kind: FunctionKind::Function,
                    function: ToolCallFunction {
                        name: name_ok,
                        arguments: c.arguments,
                        extra: Map::new(),
                    },
                    extra: Map::new(),
                });
            }
        }
        // calls for the client win: the skill calls are dropped and the model asks again if it still needs them
        if wire.is_empty() && !mine.is_empty() {
            self.pending = Some(mine);
            return out;
        }
        let finish =
            if self.stream.blocked || (wire.is_empty() && reason == FinishReason::ToolCalls) {
                FinishReason::Stop
            } else {
                reason
            };
        if !wire.is_empty() {
            out.push(self.chunk(
                ChunkDelta {
                    tool_calls: wire,
                    ..ChunkDelta::default()
                },
                None,
            ));
        }
        out.push(self.chunk(ChunkDelta::default(), Some(finish)));
        out
    }

    /// The inner stream ended: text the guard still holds, and the end of the answer when it never came.
    fn end(&mut self) -> Vec<ChatResponseChunk> {
        if self.ended {
            return Vec::new();
        }
        self.ended = true;
        self.flush_text()
    }
}

struct Run {
    inner: Option<ChunkStream>,
    filter: Filter,
    queue: VecDeque<Result<ChatResponseChunk, StreamFailure>>,
    sink: Arc<dyn ReasoningSink>,
    backend: Arc<dyn Backend>,
    policy: Arc<Policy>,
    request: ChatRequest,
    id: String,
    steps: usize,
    loads: usize,
    consulted: Consulted,
    usage: Option<Usage>,
    reasoning: String,
    model: String,
}

impl Run {
    /// Takes what the finished step knew into the totals of the answer.
    fn absorb(&mut self) {
        let thought = self.filter.splitter.take_reasoning();
        self.filter.keep_reasoning(&thought);
        self.reasoning
            .push_str(&std::mem::take(&mut self.filter.reasoning));
        if !self.filter.model.is_empty() {
            self.model.clone_from(&self.filter.model);
        }
        if let Some(u) = self.filter.usage.take() {
            let total = self.usage.get_or_insert_with(Usage::default);
            total.prompt_tokens += u.prompt_tokens;
            total.completion_tokens += u.completion_tokens;
            total.total_tokens += u.total_tokens;
        }
    }

    fn meta(&self, skills: &[String]) -> ChatResponseChunk {
        let mut extra = Map::new();
        extra.insert("skills".to_owned(), serde_json::json!(skills));
        ChatResponseChunk {
            id: self.id.clone(),
            object: ChunkObject::default(),
            model: String::new(),
            laris: Some(LarisMeta {
                // the whole list so far: a client keeps the last one it saw
                brain: self.consulted.titles().to_vec(),
                extra,
                ..LarisMeta::default()
            }),
            choices: Vec::new(),
            usage: None,
            extra: Map::new(),
        }
    }

    /// Answers the model's calls for system skills and starts the next step. `false` when the answer ends here.
    async fn next_step(&mut self, calls: Vec<Call>) -> bool {
        let visible = std::mem::take(&mut self.filter.visible);
        let mut asked = Vec::new();
        let mut answers = Vec::new();
        let mut loaded = Vec::new();
        let before = self.consulted.titles().len();
        for (n, call) in calls.into_iter().enumerate() {
            let id = call
                .id
                .clone()
                .unwrap_or_else(|| format!("server-{}-{n}", self.steps));
            let args: serde_json::Value =
                serde_json::from_str(&call.arguments).unwrap_or(serde_json::Value::Null);
            let (tool, result) = if call.name == BRAIN_TOOL {
                (
                    BRAIN_TOOL,
                    self.policy.brain.consult(&args, &mut self.consulted),
                )
            } else {
                let name = args
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default();
                let reference = args.get("reference").and_then(|v| v.as_str());
                let result = if self.loads >= self.policy.skills.max_loads() {
                    Err(super::skills::LoadError(
                        "Error: the limit of skills for this answer is reached; answer with what you have.".into(),
                    ))
                } else {
                    self.policy.skills.text_of(name, reference)
                };
                self.loads += 1;
                if result.is_ok() {
                    loaded.push(name.to_owned());
                }
                (SKILL_TOOL, result)
            };
            let content = match result {
                Ok(text) => text,
                Err(e) => e.0,
            };
            asked.push(ToolCall {
                index: None,
                id: Some(id.clone()),
                kind: FunctionKind::Function,
                function: ToolCallFunction {
                    name: tool.to_owned(),
                    arguments: call.arguments,
                    extra: Map::new(),
                },
                extra: Map::new(),
            });
            answers.push(ChatMessage {
                role: Role::Tool,
                content: Some(Content::Text(content)),
                tool_calls: Vec::new(),
                tool_call_id: Some(id),
                name: Some(tool.to_owned()),
                extra: Map::new(),
            });
        }
        self.request.messages.push(ChatMessage {
            role: Role::Assistant,
            content: (!visible.is_empty()).then_some(Content::Text(visible)),
            tool_calls: asked,
            tool_call_id: None,
            name: None,
            extra: Map::new(),
        });
        self.request.messages.extend(answers);
        if !loaded.is_empty() || self.consulted.titles().len() > before {
            let meta = self.meta(&loaded);
            self.queue.push_back(Ok(meta));
        }
        self.steps += 1;
        // a brain call earns one more step, up to the brain's own limit; skills keep theirs
        let brain_steps = self.consulted.calls().min(self.policy.brain.max_calls());
        if self.steps > self.policy.skills.max_loads() + brain_steps + 1 {
            let done = self
                .filter
                .chunk(ChunkDelta::default(), Some(FinishReason::Stop));
            self.queue.push_back(Ok(done));
            return false;
        }
        match self.backend.chat(self.request.clone()).await {
            Ok(stream) => {
                self.inner = Some(stream);
                self.filter = Filter::new(self.filter.prepared.clone(), self.id.clone());
                self.filter.model.clone_from(&self.model);
                true
            }
            Err(e) => {
                self.queue.push_back(Err(StreamFailure {
                    message: e.to_string(),
                    kind: "BackendError".into(),
                }));
                false
            }
        }
    }
}

impl Drop for Run {
    fn drop(&mut self) {
        // written whether the answer ended, failed or the client left
        self.absorb();
        if self.reasoning.is_empty() && self.consulted.titles().is_empty() {
            return;
        }
        self.sink.record(ReasoningRecord {
            key_id: self.filter.prepared.key_id.clone(),
            session_id: self.filter.prepared.session.clone(),
            model: self.model.clone(),
            prompt_sha256: self.filter.prepared.prompt_sha256.clone(),
            reasoning: std::mem::take(&mut self.reasoning),
            brain: self.consulted.titles().to_vec(),
            at: crate::access::now(),
        });
    }
}

fn filtered(
    inner: ChunkStream,
    request: ChatRequest,
    prepared: Prepared,
    backend: Arc<dyn Backend>,
    policy: Arc<Policy>,
    sink: Arc<dyn ReasoningSink>,
) -> ChunkStream {
    let id = crate::access::random_bytes(6)
        .map(|b| b.iter().map(|x| format!("{x:02x}")).collect::<String>())
        .unwrap_or_else(|_| prepared.session.clone());
    let id = format!("chatcmpl-{id}");
    let named = prepared.skills.clone();
    let seeded = Consulted::seeded(&prepared.brain);
    let mut run = Run {
        inner: Some(inner),
        filter: Filter::new(prepared, id.clone()),
        queue: VecDeque::new(),
        sink,
        backend,
        policy,
        request,
        id,
        steps: 0,
        loads: 0,
        consulted: seeded,
        usage: None,
        reasoning: String::new(),
        model: String::new(),
    };
    if !named.is_empty() || !run.consulted.titles().is_empty() {
        // which skill the user named and which brain notes the brief drew on, before the text (names only)
        let meta = run.meta(&named);
        run.queue.push_back(Ok(meta));
    }
    futures_util::stream::unfold(run, |mut run| async move {
        loop {
            if let Some(item) = run.queue.pop_front() {
                return Some((item, run));
            }
            let stream = run.inner.as_mut()?;
            match stream.next().await {
                Some(Ok(chunk)) => {
                    let out = run.filter.push(chunk);
                    run.queue.extend(out.into_iter().map(Ok));
                }
                Some(Err(failure)) => {
                    run.inner = None;
                    let out = run.filter.flush_text();
                    run.queue.extend(out.into_iter().map(Ok));
                    run.queue.push_back(Err(failure));
                }
                None => {
                    run.inner = None;
                    let out = run.filter.end();
                    run.queue.extend(out.into_iter().map(Ok));
                    run.absorb();
                    if let Some(calls) = run.filter.pending.take() {
                        run.next_step(calls).await;
                        continue;
                    }
                    if let Some(total) = run.usage.take() {
                        let mut event = run.meta(&[]);
                        event.laris = None;
                        event.model.clone_from(&run.model);
                        event.usage = Some(total);
                        run.queue.push_back(Ok(event));
                    }
                }
            }
        }
    })
    .boxed()
}

#[cfg(test)]
mod tests {
    use super::civil;

    #[test]
    fn dates() {
        assert_eq!(civil(0), (1970, 1, 1));
        assert_eq!(civil(19_723), (2024, 1, 1));
        assert_eq!(civil(20_412), (2025, 11, 20));
        assert_eq!(civil(11_016), (2000, 2, 29));
    }
}
