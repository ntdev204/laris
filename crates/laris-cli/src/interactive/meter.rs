//! Token use of the session: what `/context` and `/usage` report and what the status line's `context N%` is made of.
//!
//! [`Metered`] wraps the model. After each answer the server reported usage for, it adds to the [`Meter`] and sends
//! an `usage` event. It changes nothing about the question or the answer, so the event log and replay are as before.

use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use laris_protocol::Event;
use std::cell::Cell;
use std::rc::Rc;

/// What has been counted.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Tally {
    /// Tokens the conversation holds after the last answer (its prompt and its answer).
    pub context: u64,
    /// Prompt tokens of every request so far.
    pub prompt: u64,
    /// Answer tokens of every request so far.
    pub completion: u64,
    /// Requests the server reported usage for.
    pub requests: u64,
}

/// The counts and the limits they are read against; cheap to clone, shared by the model wrapper and the commands.
#[derive(Debug, Clone)]
pub struct Meter {
    tally: Rc<Cell<Tally>>,
    /// Context window in tokens.
    pub window: u64,
    /// Fraction of the window at which compaction starts.
    pub threshold: f64,
}

impl Meter {
    /// A meter for a window of `window` tokens.
    pub fn new(window: u64, threshold: f64) -> Self {
        Self {
            tally: Rc::default(),
            window,
            threshold,
        }
    }

    /// The counts now.
    pub fn tally(&self) -> Tally {
        self.tally.get()
    }

    /// Adds one answer's usage; returns the tokens in context.
    fn add(&self, prompt: u64, completion: u64, total: u64) -> u64 {
        let mut t = self.tally.get();
        t.context = if total > 0 {
            total
        } else {
            prompt + completion
        };
        t.prompt += prompt;
        t.completion += completion;
        t.requests += 1;
        self.tally.set(t);
        t.context
    }
}

/// A model that counts what the server says it used.
pub struct Metered<M> {
    inner: M,
    meter: Meter,
    emit: Rc<dyn Fn(Event)>,
}

impl<M> Metered<M> {
    /// `inner`, counted into `meter`; each count is also sent to `emit`.
    pub fn new(inner: M, meter: Meter, emit: Rc<dyn Fn(Event)>) -> Self {
        Self { inner, meter, emit }
    }
}

impl<M: Model> Model for Metered<M> {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let answer = self.inner.answer(request)?;
        if let Some(usage) = &answer.usage {
            let tokens = self.meter.add(
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
            );
            (self.emit)(Event::Usage {
                tokens,
                window: self.meter.window,
            });
        }
        Ok(answer)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_context_is_the_last_total_and_the_sums_grow() {
        let meter = Meter::new(1000, 0.8);
        assert_eq!(meter.add(100, 20, 120), 120);
        assert_eq!(meter.add(150, 30, 0), 180);
        let t = meter.tally();
        assert_eq!(
            (t.context, t.prompt, t.completion, t.requests),
            (180, 250, 50, 2)
        );
    }
}
