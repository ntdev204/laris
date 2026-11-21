//! The closed set of actions a [`crate::Decider`] chooses from (SR-H14).
//!
//! An action is recorded in the log before it is applied, so replay never needs the decider: what the decider
//! looked at (the clock, a configuration, a gate) is already in the action. Anything that costs something outside
//! the log (a model call, a tool run) happens only after the action that permits it.

use crate::plan::{PlanStep, StepStatus};
use serde::{Deserialize, Serialize};

/// A plan step the loop records itself because the model acted without a plan.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct AutoStep {
    /// The tool call the step stands for.
    pub id: String,
    /// The step text.
    pub text: String,
}

/// What `update_plan` came to.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum PlanChange {
    /// The new plan.
    Accept {
        /// Its steps.
        steps: Vec<PlanStep>,
    },
    /// The plan was refused, with the reason the model is told.
    Refuse {
        /// Why.
        message: String,
    },
}

/// A change of status the loop makes on its own steps.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Mark {
    /// Position of the step.
    pub index: usize,
    /// The new status.
    pub status: StepStatus,
}

/// What a message to the model after a step is about.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NoticeKind {
    /// The step got nowhere; one replan is spent.
    Replan,
    /// Replans are used up; said once.
    BudgetOut,
    /// No change of approach can help; said once.
    Permanent,
    /// Calls kept repeating: the tools are closed and the model must answer now; said once.
    Wrapup,
}

/// A message the loop adds to the conversation for the model.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Notice {
    /// What it is about.
    pub kind: NoticeKind,
    /// What went wrong, as the user may read it.
    pub issues: Vec<String>,
    /// The message to the model.
    pub text: String,
}

/// One step of the loop, chosen by the decider.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
pub enum Action {
    /// Ask the model to answer the conversation. `note` is shown to the model for this call only (the current
    /// plan); it is not part of the conversation.
    AskModel {
        /// The note, if any.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        note: Option<String>,
    },
    /// Run the tool call `id`.
    RunTool {
        /// The call.
        id: String,
    },
    /// Answer the tool call `id` with an error without running it.
    RejectTool {
        /// The call.
        id: String,
        /// Typed error code.
        code: String,
        /// Message for the model.
        message: String,
    },
    /// Apply `update_plan` for the call `id`.
    SetPlan {
        /// The call.
        id: String,
        /// The outcome.
        change: PlanChange,
    },
    /// Record a plan of the loop's own because the model started acting without one.
    AutoPlan {
        /// A step per acting call.
        steps: Vec<AutoStep>,
    },
    /// Close a step of tool results: change statuses and tell the model what did not work.
    Reflect {
        /// Status changes of the loop's own steps.
        marks: Vec<Mark>,
        /// Messages to the model.
        notices: Vec<Notice>,
    },
    /// The goal is not complete: send the model back to finish the open steps.
    Retry {
        /// The message to the model.
        text: String,
        /// The open steps.
        open: Vec<String>,
    },
    /// Accept the answer; `warning` is appended when the goal is still open.
    Finish {
        /// Text appended to the answer, or empty.
        warning: String,
    },
    /// End the turn without an accepted answer.
    Stop {
        /// `max_steps`, `timeout`, `cyclic`, `provider_error`, ...
        status: String,
        /// What the user is told (also kept in the conversation).
        notice: String,
    },
}
