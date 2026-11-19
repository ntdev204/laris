//! The session's thread and the three ways the interface reaches it: commands, the answer to an approval, and the
//! interrupt flag. The loop of `laris-core` is synchronous and the interface must keep reading keys, so the session
//! runs here and talks over channels.
//!
//! Everything non-`Send` (the loop, the registry) is built inside the thread.

use super::front::{Emit, Front};
use laris_core::{Model, ToolRunner};
use laris_policy::{Answer, ApprovalRequest, Approver, Remember};
use laris_protocol::events::{Decision, Scope};
use laris_protocol::{Command, Event};
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

/// The person's answer to an approval, as the interface gives it.
pub type Reply = (String, Decision, Scope);

/// Asks the person through the interface: the request goes out as a `permission_request` event and the call waits
/// until the answer with the same id comes back. A closed interface refuses.
pub struct ChannelApprover {
    events: Mutex<Sender<Event>>,
    answers: Mutex<Receiver<Reply>>,
    next: AtomicU64,
}

impl ChannelApprover {
    /// An approver that sends requests to `events` and reads answers from `answers`.
    pub fn new(events: Sender<Event>, answers: Receiver<Reply>) -> Self {
        Self {
            events: Mutex::new(events),
            answers: Mutex::new(answers),
            next: AtomicU64::new(1),
        }
    }
}

impl Approver for ChannelApprover {
    fn approve(&self, request: &ApprovalRequest) -> Answer {
        let id = format!("p{}", self.next.fetch_add(1, Ordering::SeqCst));
        let sent = self
            .events
            .lock()
            .map(|events| {
                events
                    .send(Event::PermissionRequest {
                        id: id.clone(),
                        tool: request.tool.clone(),
                        arguments: request.arguments.clone(),
                        reason: request.reason.clone(),
                        rule: request.suggested_rule.clone(),
                        diff: request.preview.clone().unwrap_or_default(),
                        scopes: ["once", "session", "project", "everywhere"]
                            .map(str::to_owned)
                            .to_vec(),
                    })
                    .is_ok()
            })
            .unwrap_or(false);
        if !sent {
            return Answer::Deny;
        }
        let Ok(answers) = self.answers.lock() else {
            return Answer::Deny;
        };
        // an answer to an older request (a stale one) is skipped; a closed interface ends the wait with a refusal
        while let Ok((answered, decision, scope)) = answers.recv() {
            if answered != id {
                continue;
            }
            return match (decision, scope) {
                (Decision::Deny, _) => Answer::Deny,
                (Decision::Allow, Scope::Once) => Answer::Once,
                (Decision::Allow, Scope::Session) => Answer::Always(Remember::Session),
                (Decision::Allow, Scope::Project) => Answer::Always(Remember::Project),
                (Decision::Allow, Scope::Everywhere) => Answer::Always(Remember::Everywhere),
            };
        }
        Answer::Deny
    }
}

/// What the session is built with.
pub struct Ports {
    /// Asks the person.
    pub approver: ChannelApprover,
    /// Set from outside to end the running turn.
    pub interrupt: Arc<AtomicBool>,
    /// Messages sent and not yet taken.
    pub waiting: Arc<AtomicUsize>,
    /// Where the session's events go.
    pub emit: Emit,
}

/// The interface's end of a session.
pub struct Handle {
    commands: Sender<Command>,
    answers: Sender<Reply>,
    interrupt: Arc<AtomicBool>,
    waiting: Arc<AtomicUsize>,
    thread: Option<JoinHandle<()>>,
}

impl Handle {
    /// Sends what the interface decided. An approval's answer, an interrupt and a message take the way they need;
    /// `false` when the session has ended.
    pub fn send(&self, command: Command) -> bool {
        match command {
            Command::PermissionResponse {
                id,
                decision,
                scope,
                ..
            } => self.answers.send((id, decision, scope)).is_ok(),
            Command::Interrupt {} => {
                self.interrupt.store(true, Ordering::SeqCst);
                true
            }
            Command::UserMessage { .. } | Command::Slash { .. } => {
                self.waiting.fetch_add(1, Ordering::SeqCst);
                let sent = self.commands.send(command).is_ok();
                if !sent {
                    self.waiting.fetch_sub(1, Ordering::SeqCst);
                }
                sent
            }
            other => self.commands.send(other).is_ok(),
        }
    }

    /// Whether the thread has ended.
    pub fn finished(&self) -> bool {
        self.thread.as_ref().is_none_or(JoinHandle::is_finished)
    }
}

impl Drop for Handle {
    fn drop(&mut self) {
        // the thread ends when its command channel closes; a turn in the middle of a model call ends with it
        let _ = self.commands.send(Command::Shutdown {});
        self.interrupt.store(true, Ordering::SeqCst);
        // dropping `answers` refuses any approval that waits
        drop(self.thread.take());
    }
}

/// Starts the session thread. `build` runs inside it and makes the [`Front`]; a failure is sent as an `error`
/// event and the thread ends. `ready` runs once after the build and gives the first events (`ready`, the status line).
pub fn spawn<F, M, R>(events: Sender<Event>, build: F) -> Handle
where
    F: FnOnce(Ports) -> Result<Front<M, R>, String> + Send + 'static,
    M: Model + 'static,
    R: ToolRunner + 'static,
{
    let (commands, inbox) = channel::<Command>();
    let (answers, answered) = channel::<Reply>();
    let interrupt = Arc::new(AtomicBool::new(false));
    let waiting = Arc::new(AtomicUsize::new(0));
    let handle_flag = Arc::clone(&interrupt);
    let handle_waiting = Arc::clone(&waiting);
    let thread = std::thread::spawn(move || {
        let approver = ChannelApprover::new(events.clone(), answered);
        let outbox = events.clone();
        let emit: Emit = Rc::new(move |event| {
            let _ = outbox.send(event);
        });
        let ports = Ports {
            approver,
            interrupt,
            waiting,
            emit,
        };
        let mut front = match build(ports) {
            Ok(front) => front,
            Err(message) => {
                let _ = events.send(Event::Error {
                    code: "session_failed".to_owned(),
                    message,
                });
                return;
            }
        };
        let _ = events.send(front.ready(env!("CARGO_PKG_VERSION")));
        let _ = events.send(front.line());
        while let Ok(command) = inbox.recv() {
            if !front.handle(command) {
                break;
            }
        }
    });
    Handle {
        commands,
        answers,
        interrupt: handle_flag,
        waiting: handle_waiting,
        thread: Some(thread),
    }
}
