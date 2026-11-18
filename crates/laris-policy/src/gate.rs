//! The gate every tool call of the loop passes, and the runner that tells the hooks what a tool returned.
//!
//! [`PolicyGate`] is the [`ToolGate`] of the loop: the engine decides, a `PreToolUse` hook may still block, and an
//! asked call goes to the [`Approver`] (the person, through the front end). A refusal is a typed error for the
//! model: `permission_denied` (a rule or the plan mode), `hook_blocked`, `approval_denied`. Nothing runs before the
//! gate has let it through, so a denied path is never written.

use crate::engine::{Engine, Remember, Verdict};
use crate::hooks::{HookRunner, clean};
use crate::preview::preview;
use crate::shield::Shield;
use laris_core::{Refusal, ToolGate, ToolRunner};
use laris_tools::Registry;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;

type Args = Map<String, Value>;

/// What the person is shown when a call needs approval.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ApprovalRequest {
    /// The tool.
    pub tool: String,
    /// Its arguments.
    pub arguments: Args,
    /// Why it is asked.
    pub reason: String,
    /// The rule an "always allow" answer would save.
    pub suggested_rule: String,
    /// What the call would change, as text (a diff for a file).
    pub preview: Option<String>,
}

/// The person's answer.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Answer {
    /// Refuse.
    Deny,
    /// Allow this call only.
    Once,
    /// Allow it and save the suggested rule.
    Always(Remember),
}

/// Asks the person. The front end implements it; a headless run without approval uses [`NoApprover`].
pub trait Approver: Send + Sync {
    /// The answer to `request`.
    fn approve(&self, request: &ApprovalRequest) -> Answer;
}

/// Refuses everything it is asked: what a run does when nobody can answer.
#[derive(Clone, Copy, Debug, Default)]
pub struct NoApprover;

impl Approver for NoApprover {
    fn approve(&self, _request: &ApprovalRequest) -> Answer {
        Answer::Deny
    }
}

/// Which tools change state, read from the registry. A tool that is not listed is taken to change state.
pub fn writes_of(registry: &Registry) -> BTreeMap<String, bool> {
    registry
        .schemas()
        .iter()
        .filter_map(|schema| {
            let name = &schema.function.name;
            registry.info(name).map(|info| (name.clone(), info.writes))
        })
        .collect()
}

/// The policy a call passes before it runs.
pub struct PolicyGate {
    engine: Arc<Engine>,
    writes: BTreeMap<String, bool>,
    hooks: Option<Arc<HookRunner>>,
    shield: Option<Arc<Shield>>,
    approver: Box<dyn Approver>,
}

impl PolicyGate {
    /// A gate over `engine`. `writes` says which tools change state.
    pub fn new(
        engine: Arc<Engine>,
        writes: BTreeMap<String, bool>,
        approver: impl Approver + 'static,
    ) -> Self {
        Self {
            engine,
            writes,
            hooks: None,
            shield: None,
            approver: Box::new(approver),
        }
    }

    /// Runs the `PreToolUse` hooks of `hooks` for every call that is not already refused.
    #[must_use]
    pub fn with_hooks(mut self, hooks: Arc<HookRunner>) -> Self {
        self.hooks = Some(hooks);
        self
    }

    /// Refuses injected requests (`injected_request`) whatever the rules and the mode say, before any hook or
    /// question: see [`Shield`].
    #[must_use]
    pub fn with_shield(mut self, shield: Arc<Shield>) -> Self {
        self.shield = Some(shield);
        self
    }
}

fn refusal(code: &str, message: impl Into<String>) -> Refusal {
    Refusal {
        code: code.to_owned(),
        message: message.into(),
    }
}

impl ToolGate for PolicyGate {
    fn check(&self, name: &str, arguments: &Args) -> Option<Refusal> {
        let writes = self.writes.get(name).copied().unwrap_or(true);
        let decision = self.engine.decide(name, arguments, writes);
        if decision.verdict == Verdict::Deny {
            return Some(refusal(
                "permission_denied",
                format!("{name} is not permitted: {}", decision.reason),
            ));
        }
        if let Some(shield) = &self.shield
            && let Some(refused) = shield.review(name, arguments)
        {
            return Some(refused);
        }
        if let Some(hooks) = &self.hooks {
            let mut payload = Map::new();
            payload.insert("tool_name".to_owned(), json!(name));
            payload.insert("tool_input".to_owned(), Value::Object(arguments.clone()));
            let outcome = hooks.run("PreToolUse", &payload, name);
            if outcome.blocked {
                return Some(refusal("hook_blocked", outcome.reason));
            }
        }
        if decision.verdict == Verdict::Allow {
            return None;
        }
        let request = ApprovalRequest {
            tool: name.to_owned(),
            arguments: arguments.clone(),
            reason: decision.reason,
            suggested_rule: self.engine.suggest(name, arguments),
            preview: preview(name, arguments, self.engine.scope()),
        };
        match self.approver.approve(&request) {
            Answer::Once => None,
            Answer::Always(how) => {
                // the answer is yes for this call even when the rule could not be kept
                self.engine.remember(&request.suggested_rule, how).ok();
                None
            }
            Answer::Deny => Some(refusal("approval_denied", "this action was not approved")),
        }
    }
}

/// A [`ToolRunner`] that tells the `PostToolUse` hooks what a tool returned. Text a hook adds for the model is put
/// under `hook_context`, and the result is marked untrusted (it is the output of a command, not of this program).
pub struct HookedRunner<R> {
    inner: R,
    hooks: Arc<HookRunner>,
    shield: Option<Arc<Shield>>,
}

impl<R: ToolRunner> HookedRunner<R> {
    /// Wraps `inner`.
    pub fn new(inner: R, hooks: Arc<HookRunner>) -> Self {
        Self {
            inner,
            hooks,
            shield: None,
        }
    }

    /// Hides credentials in what hooks add and watches it for orders to the model (hook output is untrusted).
    #[must_use]
    pub fn with_shield(mut self, shield: Arc<Shield>) -> Self {
        self.shield = Some(shield);
        self
    }

    /// The wrapped runner.
    pub fn inner_mut(&mut self) -> &mut R {
        &mut self.inner
    }
}

impl<R: ToolRunner> ToolRunner for HookedRunner<R> {
    fn run(&mut self, name: &str, arguments: &Args) -> Value {
        let mut result = self.inner.run(name, arguments);
        if !self.hooks.has("PostToolUse") {
            return result;
        }
        let mut payload = Map::new();
        payload.insert("tool_name".to_owned(), json!(name));
        payload.insert("tool_input".to_owned(), Value::Object(arguments.clone()));
        payload.insert("tool_response".to_owned(), result.clone());
        let outcome = self.hooks.run("PostToolUse", &payload, name);
        let mut notes: Vec<String> = outcome.context;
        if outcome.blocked {
            notes.push(format!("a hook objected: {}", outcome.reason));
        }
        if !notes.is_empty()
            && let Value::Object(map) = &mut result
        {
            let notes: Vec<String> = notes
                .iter()
                .map(|n| {
                    let n = clean(n);
                    self.shield
                        .as_ref()
                        .map_or(n.clone(), |s| s.screen_text(&n))
                })
                .collect();
            map.insert("hook_context".to_owned(), json!(notes));
            map.insert("untrusted".to_owned(), Value::Bool(true));
        }
        result
    }
}

/// A [`ToolRunner`] that finishes every result through the [`Shield`]: credentials hidden before the loop logs the
/// result and the model reads it, untrusted content remembered and watched for orders. Put it directly around the
/// registry, inside a [`HookedRunner`].
pub struct ShieldedRunner<R> {
    inner: R,
    shield: Arc<Shield>,
}

impl<R: ToolRunner> ShieldedRunner<R> {
    /// Wraps `inner`.
    pub fn new(inner: R, shield: Arc<Shield>) -> Self {
        Self { inner, shield }
    }

    /// The wrapped runner.
    pub fn inner_mut(&mut self) -> &mut R {
        &mut self.inner
    }
}

impl<R: ToolRunner> ToolRunner for ShieldedRunner<R> {
    fn run(&mut self, name: &str, arguments: &Args) -> Value {
        let result = self.inner.run(name, arguments);
        self.shield.screen_value(&result)
    }
}
