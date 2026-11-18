//! The decision: may this call run, must the person be asked, or is it refused?
//!
//! Order, first match wins:
//!
//! 1. a `deny` rule refuses;
//! 2. in `plan` mode a call that changes state is refused (no rule makes a plan writable);
//! 3. an `ask` rule asks, even in `bypass`;
//! 4. an `allow` rule allows;
//! 5. the mode: `bypass` allows, `acceptEdits` allows `Write` and `Edit`, `default` asks for a call that changes
//!    state; a call that only reads is allowed.
//!
//! Rules come from the settings (`permissions.*`), from what the user saved for this folder
//! ([`ProjectState`]) and from the answers of this session. `bypass` exists only when the installation's policy
//! allows it (`allow_bypass`); a setting cannot turn it on by itself.

use crate::rule::{command_parts, has_redirect_or_substitution, rule_matches, suggest_rule};
use crate::state::ProjectState;
use laris_config::settings::{PermissionMode, Permissions};
use laris_tools::Scope;
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard, PoisonError};

/// The tools `acceptEdits` lets through.
const EDIT_TOOLS: [&str; 2] = ["write", "edit"];

/// What the engine decided.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verdict {
    /// Run it.
    Allow,
    /// Ask the person first.
    Ask,
    /// Refuse it.
    Deny,
}

/// A verdict with its reason and the rule that decided, if one did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decision {
    /// What to do.
    pub verdict: Verdict,
    /// Why, for the person and the model.
    pub reason: String,
    /// The rule that decided.
    pub rule: Option<String>,
}

impl Decision {
    fn new(verdict: Verdict, reason: impl Into<String>, rule: Option<String>) -> Self {
        Self {
            verdict,
            reason: reason.into(),
            rule,
        }
    }
}

/// How long an "always allow" answer lasts.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Remember {
    /// This session, in memory.
    Session,
    /// This folder, in its `state.json`.
    Project,
    /// Everywhere, in `permissions.allow` of the settings file.
    Everywhere,
}

/// Why a mode or a rule was not accepted.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PolicyError(pub String);

impl std::fmt::Display for PolicyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for PolicyError {}

struct Inner {
    permissions: Permissions,
    mode: Option<PermissionMode>,
    session_allow: Vec<String>,
    session_deny: Vec<String>,
}

/// Modes and rules over one project folder.
pub struct Engine {
    scope: Scope,
    state: ProjectState,
    settings_path: Option<PathBuf>,
    allow_bypass: bool,
    inner: Mutex<Inner>,
}

impl Engine {
    /// An engine over `permissions` (from the settings), for the folders of `scope`. `settings_path` is where an
    /// "always, everywhere" answer is saved; `None` refuses that answer. `allow_bypass` is the installation's
    /// policy.
    pub fn new(
        permissions: Permissions,
        scope: Scope,
        state: ProjectState,
        settings_path: Option<PathBuf>,
        allow_bypass: bool,
    ) -> Self {
        Self {
            scope,
            state,
            settings_path,
            allow_bypass,
            inner: Mutex::new(Inner {
                permissions,
                mode: None,
                session_allow: Vec::new(),
                session_deny: Vec::new(),
            }),
        }
    }

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The folders and secrets the tools are held to.
    pub fn scope(&self) -> &Scope {
        &self.scope
    }

    /// The saved decisions of this folder.
    pub fn state(&self) -> &ProjectState {
        &self.state
    }

    /// Replaces the rules and the default mode, as when the settings change.
    pub fn set_permissions(&self, permissions: Permissions) {
        self.lock().permissions = permissions;
    }

    fn gated(&self, mode: PermissionMode) -> PermissionMode {
        if mode == PermissionMode::Bypass && !self.allow_bypass {
            PermissionMode::Default
        } else {
            mode
        }
    }

    /// The mode now: the one chosen for this session, else the settings' default (`bypass` only when allowed).
    pub fn mode(&self) -> PermissionMode {
        let inner = self.lock();
        self.gated(inner.mode.unwrap_or(inner.permissions.default_mode))
    }

    /// Chooses the mode of this session. `bypass` is refused unless the installation's policy allows it.
    pub fn set_mode(&self, mode: PermissionMode) -> Result<(), PolicyError> {
        if mode == PermissionMode::Bypass && !self.allow_bypass {
            return Err(PolicyError(
                "bypass mode is not allowed by this installation's policy".to_owned(),
            ));
        }
        self.lock().mode = Some(mode);
        Ok(())
    }

    /// Shift+Tab: `default`, `acceptEdits`, `plan`, then `bypass` when allowed, then `default` again.
    pub fn cycle(&self) -> PermissionMode {
        let order: Vec<PermissionMode> = [
            PermissionMode::Default,
            PermissionMode::AcceptEdits,
            PermissionMode::Plan,
            PermissionMode::Bypass,
        ]
        .into_iter()
        .filter(|m| *m != PermissionMode::Bypass || self.allow_bypass)
        .collect();
        let now = self.mode();
        let next = order
            .iter()
            .position(|m| *m == now)
            .map_or(PermissionMode::Default, |at| order[(at + 1) % order.len()]);
        self.lock().mode = Some(next);
        next
    }

    /// Adds a `deny` rule for this session (what `--disallowed-tools` of one headless run does).
    pub fn deny_for_session(&self, rule: &str) {
        self.lock().session_deny.push(rule.to_owned());
    }

    /// Every rule of `kind` (`allow`, `ask` or `deny`) now in force, in the order they are tried.
    pub fn rules(&self, kind: &str) -> Vec<String> {
        let inner = self.lock();
        let mut rules = match kind {
            "allow" => inner.permissions.allow.clone(),
            "ask" => inner.permissions.ask.clone(),
            "deny" => inner.permissions.deny.clone(),
            _ => Vec::new(),
        };
        match kind {
            "allow" => {
                rules.extend(self.state.rules("allow"));
                rules.extend(inner.session_allow.iter().cloned());
            }
            "deny" => {
                rules.extend(self.state.rules("deny"));
                rules.extend(inner.session_deny.iter().cloned());
            }
            _ => {}
        }
        rules
    }

    fn first(&self, kind: &str, tool: &str, arguments: &Map<String, Value>) -> Option<String> {
        let rules = self.rules(kind);
        let any_part = kind != "allow";
        if let Some(rule) = rules
            .iter()
            .find(|r| rule_matches(r, tool, arguments, &self.scope, any_part))
        {
            return Some(rule.clone());
        }
        // `a && b` runs unasked when a rule allows each part
        let command = arguments.get("command").and_then(Value::as_str)?;
        if kind != "allow" || has_redirect_or_substitution(command) {
            return None;
        }
        let parts = command_parts(command);
        if parts.len() < 2 {
            return None;
        }
        let mut chosen = Vec::new();
        for part in &parts {
            let single = json!({ "command": part });
            let single = single.as_object()?;
            chosen.push(
                rules
                    .iter()
                    .find(|r| rule_matches(r, tool, single, &self.scope, false))?,
            );
        }
        chosen.first().map(|r| (*r).clone())
    }

    /// Decides one call. `writes` says whether the tool changes files or state.
    pub fn decide(&self, tool: &str, arguments: &Map<String, Value>, writes: bool) -> Decision {
        let name = tool.trim().to_lowercase();
        if let Some(rule) = self.first("deny", tool, arguments) {
            return Decision::new(Verdict::Deny, format!("denied by rule {rule}"), Some(rule));
        }
        let mode = self.mode();
        if mode == PermissionMode::Plan && writes {
            return Decision::new(Verdict::Deny, "plan mode is read-only", None);
        }
        if let Some(rule) = self.first("ask", tool, arguments) {
            return Decision::new(Verdict::Ask, format!("rule {rule} asks"), Some(rule));
        }
        if let Some(rule) = self.first("allow", tool, arguments) {
            return Decision::new(
                Verdict::Allow,
                format!("allowed by rule {rule}"),
                Some(rule),
            );
        }
        if !writes || mode == PermissionMode::Bypass {
            return Decision::new(Verdict::Allow, "no approval needed", None);
        }
        if mode == PermissionMode::AcceptEdits && EDIT_TOOLS.contains(&name.as_str()) {
            return Decision::new(Verdict::Allow, "acceptEdits mode", None);
        }
        Decision::new(Verdict::Ask, "needs your approval", None)
    }

    /// The rule an "always allow" answer would save for this call.
    pub fn suggest(&self, tool: &str, arguments: &Map<String, Value>) -> String {
        suggest_rule(tool, arguments)
    }

    /// Keeps `rule` as an `allow` rule for the session, this folder or everywhere.
    pub fn remember(&self, rule: &str, how: Remember) -> Result<(), PolicyError> {
        if crate::rule::parse_rule(rule).is_none() {
            return Err(PolicyError(format!("not a rule: {rule:?}")));
        }
        match how {
            Remember::Session => {
                let mut inner = self.lock();
                if !inner.session_allow.iter().any(|r| r == rule) {
                    inner.session_allow.push(rule.to_owned());
                }
                Ok(())
            }
            Remember::Project => self
                .state
                .add_allow(rule)
                .map_err(|e| PolicyError(format!("cannot save the approval: {e}"))),
            Remember::Everywhere => self.remember_everywhere(rule),
        }
    }

    fn remember_everywhere(&self, rule: &str) -> Result<(), PolicyError> {
        use laris_config::files;
        let Some(path) = &self.settings_path else {
            return Err(PolicyError("no settings file to save to".to_owned()));
        };
        let failed = |e: laris_config::ConfigError| PolicyError(e.to_string());
        let data = files::read_settings(path)
            .map_err(failed)?
            .unwrap_or_else(|| json!({}));
        let mut allow: Vec<Value> = files::get_path(&data, "permissions.allow")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if !allow.iter().any(|r| r.as_str() == Some(rule)) {
            allow.push(json!(rule));
        }
        let updated =
            files::set_path(&data, "permissions.allow", Value::Array(allow)).map_err(failed)?;
        files::write_settings(path, &updated).map_err(failed)?;
        let mut inner = self.lock();
        if !inner.permissions.allow.iter().any(|r| r == rule) {
            inner.permissions.allow.push(rule.to_owned());
        }
        Ok(())
    }

    /// A readable summary: the mode and the rules.
    pub fn describe(&self) -> String {
        let mut lines = vec![format!(
            "mode: {}{}",
            mode_name(self.mode()),
            if self.allow_bypass {
                ""
            } else {
                " (bypass not allowed)"
            }
        )];
        for kind in ["deny", "ask", "allow"] {
            let rules = self.rules(kind);
            lines.push(format!(
                "{kind}: {}",
                if rules.is_empty() {
                    "(none)".to_owned()
                } else {
                    rules.join(", ")
                }
            ));
        }
        lines.join("\n")
    }
}

/// The name of a mode as the settings spell it.
pub fn mode_name(mode: PermissionMode) -> &'static str {
    match mode {
        PermissionMode::Default => "default",
        PermissionMode::AcceptEdits => "acceptEdits",
        PermissionMode::Plan => "plan",
        PermissionMode::Bypass => "bypass",
    }
}
