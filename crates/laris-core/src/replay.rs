//! Replay: fold a log again with a model in place of the real one and compare the outputs byte for byte.

use crate::error::CoreError;
use crate::model::{Model, ModelRequest};
use crate::record::{Record, decode_record, encode_record};
use crate::session::Session;
use laris_protocol::Event;
use laris_store::StoredEvent;
use std::collections::VecDeque;

/// The result of folding a log.
#[derive(Debug)]
pub struct Replayed {
    /// The state after the last input.
    pub session: Session,
    /// The stored form of every output the fold produced, one record per line, in order.
    pub output: String,
    /// Outputs of the last input that the log does not hold (the process died before writing them).
    pub missing: Vec<Event>,
}

/// Folds `events` from the start. Each input is applied; each recorded output must equal, byte for byte, the one the
/// fold produces. With `model`, a recorded model answer is asked of the model again (a [`crate::ScriptedModel`] built
/// from the same log fails when the conversation differs from the recorded one) and must equal the recorded answer.
///
/// Outputs missing at the very end are returned in [`Replayed::missing`]; missing anywhere else is an error.
pub fn replay(
    events: &[StoredEvent],
    mut model: Option<&mut dyn Model>,
) -> Result<Replayed, CoreError> {
    let mut session = Session::new();
    let mut queue: VecDeque<Event> = VecDeque::new();
    let mut output = String::new();
    for stored in events {
        let record = decode_record(&stored.data).map_err(|message| CoreError::Decode {
            seq: stored.seq,
            message,
        })?;
        if let Record::Emitted { .. } = &record {
            let Some(expected) = queue.pop_front() else {
                return Err(CoreError::Diverged {
                    seq: stored.seq,
                    expected: "no output".to_owned(),
                    found: stored.data.clone(),
                });
            };
            let expected = encode_record(&Record::Emitted { event: expected });
            if expected != stored.data {
                return Err(CoreError::Diverged {
                    seq: stored.seq,
                    expected,
                    found: stored.data.clone(),
                });
            }
            output.push_str(&expected);
            output.push('\n');
            continue;
        }
        if !queue.is_empty() {
            return Err(CoreError::MissingOutputs { seq: stored.seq });
        }
        if let (Record::ModelAnswer { answer, .. }, Some(model)) = (&record, model.as_deref_mut()) {
            let request = ModelRequest {
                messages: session.messages(),
                note: session.asked_note(),
                tools: &[],
            };
            let given = model.answer(&request).map_err(|source| CoreError::Model {
                seq: stored.seq,
                source,
            })?;
            if &given != answer {
                return Err(CoreError::Diverged {
                    seq: stored.seq,
                    expected: format!("{given:?}"),
                    found: format!("{answer:?}"),
                });
            }
        }
        queue.extend(session.apply(&record).map_err(|e| match e {
            CoreError::Unexpected(m) => CoreError::Decode {
                seq: stored.seq,
                message: m,
            },
            other => other,
        })?);
    }
    Ok(Replayed {
        session,
        output,
        missing: queue.into(),
    })
}
