//! The plan: a short list of steps with a status, shown to the user and kept across turns.
//!
//! The plan belongs to the loop, not to a prompt: the model changes it through the `update_plan` tool, the loop shows
//! it, keeps it in the session and refuses to call a goal finished while steps are still open.

use laris_protocol::Event;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Name of the tool the model changes the plan with. The loop handles it; it is not a registry tool.
pub const PLAN_TOOL: &str = "update_plan";

/// Where a step stands.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StepStatus {
    /// Not started.
    Pending,
    /// Being worked on.
    InProgress,
    /// Finished.
    Done,
    /// Tried and failed; reported, not repeated.
    Failed,
    /// Left out on purpose.
    Skipped,
}

impl StepStatus {
    /// Every status, in the order the model is told them.
    pub const ALL: [StepStatus; 5] = [
        Self::Pending,
        Self::InProgress,
        Self::Done,
        Self::Failed,
        Self::Skipped,
    ];

    /// The wire name.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::InProgress => "in_progress",
            Self::Done => "done",
            Self::Failed => "failed",
            Self::Skipped => "skipped",
        }
    }

    /// Reads a wire name.
    pub fn parse(text: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|s| s.as_str() == text)
    }

    /// Nothing more to do on this step (failures are reported at the end).
    pub fn is_closed(self) -> bool {
        matches!(self, Self::Done | Self::Failed | Self::Skipped)
    }

    fn mark(self) -> char {
        match self {
            Self::Pending => ' ',
            Self::InProgress => '~',
            Self::Done => 'x',
            Self::Failed => '!',
            Self::Skipped => '-',
        }
    }
}

/// One step of the plan.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanStep {
    /// What the step is.
    pub text: String,
    /// Where it stands.
    pub status: StepStatus,
}

/// Texts of the steps that are not closed.
pub fn open_steps(plan: &[PlanStep]) -> Vec<String> {
    plan.iter()
        .filter(|s| !s.status.is_closed())
        .map(|s| s.text.clone())
        .collect()
}

/// Texts of the steps that failed.
pub fn failed_steps(plan: &[PlanStep]) -> Vec<String> {
    plan.iter()
        .filter(|s| s.status == StepStatus::Failed)
        .map(|s| s.text.clone())
        .collect()
}

/// The plan as the model reads it: `1. [x] text (done)`.
pub fn render(plan: &[PlanStep]) -> String {
    plan.iter()
        .enumerate()
        .map(|(i, s)| {
            format!(
                "{}. [{}] {} ({})",
                i + 1,
                s.status.mark(),
                s.text,
                s.status.as_str()
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// The `plan` event.
pub fn plan_event(source: &str, plan: &[PlanStep]) -> Event {
    let steps = plan
        .iter()
        .map(|s| {
            let mut step = Map::new();
            step.insert("text".to_owned(), Value::from(s.text.clone()));
            step.insert("status".to_owned(), Value::from(s.status.as_str()));
            step
        })
        .collect();
    Event::Plan {
        source: source.to_owned(),
        steps,
    }
}

/// Reads the arguments of `update_plan` strictly: nothing is guessed. `Err` is the reason for the model.
pub fn parse_plan(
    arguments: &Map<String, Value>,
    max_steps: usize,
    step_chars: usize,
) -> Result<Vec<PlanStep>, String> {
    let Some(Value::Array(raw)) = arguments.get("steps") else {
        return Err("steps must be a non-empty list".to_owned());
    };
    if raw.is_empty() {
        return Err("steps must be a non-empty list".to_owned());
    }
    if raw.len() > max_steps {
        return Err(format!("at most {max_steps} steps"));
    }
    let mut steps = Vec::with_capacity(raw.len());
    for item in raw {
        let text = item
            .get("text")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .ok_or_else(|| "every step needs text".to_owned())?;
        let status = match item.get("status") {
            None => StepStatus::Pending,
            Some(Value::String(s)) => StepStatus::parse(s).ok_or_else(status_error)?,
            Some(_) => return Err(status_error()),
        };
        steps.push(PlanStep {
            text: text.chars().take(step_chars).collect(),
            status,
        });
    }
    Ok(steps)
}

fn status_error() -> String {
    let names: Vec<&str> = StepStatus::ALL.iter().map(|s| s.as_str()).collect();
    format!("status must be one of {}", names.join(", "))
}
