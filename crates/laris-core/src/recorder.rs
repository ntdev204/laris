//! Recording a live session and resuming it after a killed process.

use crate::error::CoreError;
use crate::record::{Record, encode_record};
use crate::replay::replay;
use crate::session::Session;
use laris_protocol::Event;
use laris_store::Store;

/// What opening a session found.
#[derive(Debug)]
pub struct Resumed {
    /// Events already in the log.
    pub events: usize,
    /// Outputs written to repair a log cut between an input and its outputs.
    pub repaired: usize,
}

/// A session being written: its state and its log.
#[derive(Debug)]
pub struct Recorder {
    store: Store,
    id: String,
    session: Session,
}

impl Recorder {
    /// Opens a session, creating it when new. The state is rebuilt by folding the log; when the process died between
    /// an input and its outputs, the missing outputs are appended first, so the log ends where a clean run would.
    pub fn open(
        store: Store,
        id: &str,
        title: &str,
        now: f64,
    ) -> Result<(Self, Resumed), CoreError> {
        store.create_session(id, title, now)?;
        let events = store.events(id, 0)?;
        let replayed = replay(&events, None)?;
        let repaired = replayed.missing.len();
        let recorder = Self {
            store,
            id: id.to_owned(),
            session: replayed.session,
        };
        for event in replayed.missing {
            recorder.append(&Record::Emitted { event }, now)?;
        }
        Ok((
            recorder,
            Resumed {
                events: events.len(),
                repaired,
            },
        ))
    }

    /// The state.
    pub fn session(&self) -> &Session {
        &self.session
    }

    /// The store.
    pub fn store(&self) -> &Store {
        &self.store
    }

    /// Records one input, applies it, records the outputs and returns them. An input that does not fit the state is
    /// refused before anything is written.
    pub fn record(&mut self, input: Record, now: f64) -> Result<Vec<Event>, CoreError> {
        let mut next = self.session.clone();
        let events = next.apply(&input)?;
        self.append(&input, now)?;
        for event in &events {
            self.append(
                &Record::Emitted {
                    event: event.clone(),
                },
                now,
            )?;
        }
        self.session = next;
        Ok(events)
    }

    fn append(&self, record: &Record, now: f64) -> Result<(), CoreError> {
        self.store
            .append_event(&self.id, record.kind(), now, &encode_record(record))?;
        Ok(())
    }
}
