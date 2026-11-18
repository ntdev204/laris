//! Interface scenarios (`tests/golden/ink_scenarios/`) as typed data, and their replay.
//!
//! A scenario is a list of steps. A step may expect one command (only the fields written are compared) and
//! emits events. The first step usually has no command: the core speaks first. [`Scenario::parse`] checks
//! that every message is a valid typed one and that ids pair up; [`replay`] plays the interface against the
//! scripted core through the JSON-lines encoding in both directions.

use crate::events::{Command, Event, VersionMismatch, check_ready};
use crate::jsonl;
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::fmt;

/// One step.
#[derive(Debug, Clone, PartialEq)]
pub struct Step {
    /// The command the interface sends, as written (partial).
    pub expect: Option<Map<String, Value>>,
    /// The same command with defaults filled in.
    pub command: Option<Command>,
    /// Milliseconds the recording waited before the next input (informational).
    pub wait: Option<u64>,
    /// Events the core emits.
    pub emit: Vec<Event>,
}

/// A named list of steps.
#[derive(Debug, Clone, PartialEq)]
pub struct Scenario {
    /// Description.
    pub name: String,
    /// Steps in order.
    pub steps: Vec<Step>,
}

/// A scenario that is malformed or does not replay.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScenarioError(pub String);

impl fmt::Display for ScenarioError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ScenarioError {}

fn err<T>(m: impl Into<String>) -> Result<T, ScenarioError> {
    Err(ScenarioError(m.into()))
}

impl Scenario {
    /// Parses and checks a scenario file.
    pub fn parse(text: &str) -> Result<Self, ScenarioError> {
        let root: Value =
            serde_json::from_str(text).map_err(|e| ScenarioError(format!("not JSON: {e}")))?;
        let name = root
            .get("name")
            .and_then(Value::as_str)
            .ok_or_else(|| ScenarioError("missing `name`".to_owned()))?
            .to_owned();
        let Some(raw_steps) = root.get("steps").and_then(Value::as_array) else {
            return err("missing `steps`");
        };
        let mut steps = Vec::new();
        for (i, raw) in raw_steps.iter().enumerate() {
            let at = format!("step {i}");
            let expect = match raw.get("expect") {
                None => None,
                Some(Value::Object(o)) => Some(o.clone()),
                Some(_) => return err(format!("{at}: `expect` must be an object")),
            };
            let command = match &expect {
                None => None,
                Some(o) => {
                    // The recording leaves out ids the interface makes up; a placeholder stands in.
                    let mut full = o.clone();
                    if full.get("type").and_then(Value::as_str) == Some("complete") {
                        full.entry("id").or_insert_with(|| Value::from("c"));
                    }
                    Some(
                        jsonl::decode_command(&Value::Object(full).to_string())
                            .map_err(|e| ScenarioError(format!("{at}: expect: {e}")))?,
                    )
                }
            };
            let mut emit = Vec::new();
            for (j, e) in raw
                .get("emit")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .enumerate()
            {
                emit.push(
                    jsonl::decode_event(&e.to_string())
                        .map_err(|e| ScenarioError(format!("{at}: emit {j}: {e}")))?,
                );
            }
            steps.push(Step {
                expect,
                command,
                wait: raw.get("wait").and_then(Value::as_u64),
                emit,
            });
        }
        let scenario = Self { name, steps };
        scenario.check_ids()?;
        Ok(scenario)
    }

    /// Every tool result answers an earlier tool call and every permission response an earlier request.
    fn check_ids(&self) -> Result<(), ScenarioError> {
        let mut calls = BTreeSet::new();
        let mut requests = BTreeSet::new();
        for (i, step) in self.steps.iter().enumerate() {
            if let Some(Command::PermissionResponse { id, .. }) = &step.command
                && !requests.contains(id)
            {
                return err(format!(
                    "step {i}: response to unknown permission request {id}"
                ));
            }
            for event in &step.emit {
                match event {
                    Event::ToolCall { id, .. } => {
                        calls.insert(id.clone());
                    }
                    Event::ToolResult { id, .. } if !calls.contains(id) => {
                        return err(format!("step {i}: tool_result for unknown call {id}"));
                    }
                    Event::PermissionRequest { id, .. } => {
                        requests.insert(id.clone());
                    }
                    _ => {}
                }
            }
        }
        Ok(())
    }
}

/// What a replay produced.
#[derive(Debug, Clone, PartialEq)]
pub struct Replay {
    /// Every event the interface received, in order.
    pub events: Vec<Event>,
    /// Set when the core's `ready` named another version; the interface stops there.
    pub version_mismatch: Option<VersionMismatch>,
}

/// The interface sends each expected command (as JSON lines) to a scripted core that checks it against the
/// scenario and answers with the step's events (as JSON lines).
pub fn replay(scenario: &Scenario) -> Result<Replay, ScenarioError> {
    let mut received = Vec::new();
    for (i, step) in scenario.steps.iter().enumerate() {
        if let (Some(command), Some(expect)) = (&step.command, &step.expect) {
            let line = jsonl::encode(command);
            let sent = jsonl::decode_command(&line)
                .map_err(|e| ScenarioError(format!("step {i}: {e}")))?;
            let as_value = serde_json::to_value(&sent).unwrap_or(Value::Null);
            for (key, want) in expect {
                if as_value.get(key) != Some(want) {
                    return err(format!(
                        "step {i}: command field `{key}` is {:?}, the scenario expects {want}",
                        as_value.get(key)
                    ));
                }
            }
        }
        for event in &step.emit {
            let back = jsonl::decode_event(&jsonl::encode(event))
                .map_err(|e| ScenarioError(format!("step {i}: {e}")))?;
            if &back != event {
                return err(format!(
                    "step {i}: {} changed on the wire",
                    event.type_name()
                ));
            }
            if let Err(mismatch) = check_ready(&back) {
                received.push(back);
                return Ok(Replay {
                    events: received,
                    version_mismatch: Some(mismatch),
                });
            }
            received.push(back);
        }
    }
    Ok(Replay {
        events: received,
        version_mismatch: None,
    })
}
