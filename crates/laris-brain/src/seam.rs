//! The brain behind the loop's `Decider` seam (SR-H14, ADR-024 5.1).
//!
//! [`BrainDecider`] wraps [`FollowModel`]. The mechanical steps of the loop (plan, tool gate, reflection, completion
//! check) stay with it, because they are not judgement and the policy layer must not be learnable. At the one choice
//! point, the moment the loop would ask the model, a [`Chooser`] picks an [`Act`] from the [`Signals`] the [`Brain`]
//! measured:
//!
//! * `stop`, `answer`, `abstain`, `ask_user` end the turn, with the text the [`Brain`] supplies (for `answer`, the
//!   composed answer; the advisor writes nothing the user reads);
//! * `retrieve`, `acquire`, `verify`, `run_tool`, `ask_advisor` need a proposal, so the loop asks the advisor, with a
//!   note naming the step the system chose. The proposed call still passes the tool gate before it runs.
//!
//! The advisor's final text is a proposal too: at the completion check the chooser decides again, and the turn ends
//! with the brain's own text, or the advisor is sent back with the step the system chose.
//!
//! The choice is logged through [`Brain::log`] before the action is returned, so a choice never goes unrecorded.

use laris_core::{Action, Clock, Decider, FollowModel, ModelError, Pending, Session};

use crate::decide::{Act, Choice, Chooser, Signals};

/// What the decider needs from the rest of the system.
pub trait Brain {
    /// The measured state for this decision.
    fn signals(&mut self, session: &Session, clock: &Clock) -> Signals;

    /// The text that ends the turn for `act` (`answer`, `abstain`, `ask_user` or `stop`).
    fn closing_text(&mut self, act: Act, choice: &Choice, session: &Session) -> String;

    /// Records the choice (the decision log). The default drops it.
    fn log(&mut self, choice: &Choice) {
        let _ = choice;
    }
}

/// A decider that lets a [`Chooser`] pick at the choice points and the wrapped policy do the rest.
pub struct BrainDecider<C: Chooser, B: Brain> {
    inner: FollowModel,
    chooser: C,
    brain: B,
}

impl<C: Chooser, B: Brain> BrainDecider<C, B> {
    /// `inner` keeps the mechanical steps.
    pub fn new(inner: FollowModel, chooser: C, brain: B) -> Self {
        Self {
            inner,
            chooser,
            brain,
        }
    }

    /// The brain side (a test reads what it was asked).
    pub fn brain(&self) -> &B {
        &self.brain
    }
}

impl<C: Chooser, B: Brain> Decider for BrainDecider<C, B> {
    fn decide(&mut self, session: &Session, clock: &Clock) -> Option<Action> {
        let checking = !session.is_closed() && *session.pending() == Pending::Check;
        let asking = !session.is_closed()
            && *session.pending() == Pending::Model
            && session.asked().is_none();
        if !checking && !asking {
            return self.inner.decide(session, clock);
        }
        let signals = self.brain.signals(session, clock);
        let choice = self.chooser.choose(&signals);
        debug_assert!(choice.candidates.contains(&choice.act));
        self.brain.log(&choice);
        match choice.act {
            Act::Stop => {
                let status = choice.limit.map_or("stopped", |l| l.as_str()).to_owned();
                let notice = self.brain.closing_text(choice.act, &choice, session);
                Some(Action::Stop { status, notice })
            }
            Act::Answer | Act::Abstain | Act::AskUser => {
                let notice = self.brain.closing_text(choice.act, &choice, session);
                Some(Action::Stop {
                    status: "completed".to_owned(),
                    notice,
                })
            }
            step if checking => Some(Action::Retry {
                text: format!(
                    "Next step chosen by the system: {}. Propose it; do not write the final answer.",
                    step.as_str()
                ),
                open: Vec::new(),
            }),
            step => match self.inner.decide(session, clock)? {
                Action::AskModel { note } => {
                    let line = format!("Next step chosen by the system: {}.", step.as_str());
                    Some(Action::AskModel {
                        note: Some(note.map_or(line.clone(), |n| format!("{n}\n{line}"))),
                    })
                }
                other => Some(other),
            },
        }
    }

    fn model_failed(&mut self, session: &Session, error: &ModelError) -> Action {
        self.inner.model_failed(session, error)
    }

    fn offers(&self, name: &str) -> bool {
        self.inner.offers(name)
    }
}
