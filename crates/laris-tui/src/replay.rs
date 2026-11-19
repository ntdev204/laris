//! A recorded core, played into the interface: the scenarios of `laris-protocol` (the golden ones recorded from the
//! first generation's engine and translated) become keystrokes and events.
//!
//! A step that expects a command is typed the way a person would (`user_message` is the text and Enter,
//! `interrupt` is Esc, `command` is `/name args` and Enter), and the commands the interface sends are checked
//! against the step. Then the step's events are fed in. After every step the screen is kept.

use crate::app::{App, Input};
use crate::input::Key;
use laris_config::settings::Ui;
use laris_protocol::Command;
use laris_protocol::scenario::Scenario;
use serde_json::Value;

/// The screen after one step.
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    /// Index of the step.
    pub step: usize,
    /// The whole screen as text.
    pub screen: String,
    /// The commands the interface sent in this step.
    pub commands: Vec<Command>,
}

/// What a replay produced.
#[derive(Debug, Clone)]
pub struct Replayed {
    /// The interface after the last step.
    pub app: App,
    /// The screen after each step.
    pub snapshots: Vec<Snapshot>,
}

/// Types `text` into the interface: characters, new lines as Shift+Enter, then Enter. Returns what it sent.
pub fn type_and_send(app: &mut App, text: &str) -> Vec<Command> {
    for c in text.chars() {
        let key = if c == '\n' {
            Key::Newline
        } else {
            Key::Char(c)
        };
        app.update(Input::Key(key));
    }
    app.update(Input::Key(Key::Enter))
}

/// Plays `scenario` into a new interface drawn at `width`. With `skip_unsupported` a step that expects a command
/// this interface cannot give yet (an approval, a login: T158) only has its events fed in; otherwise it is an error.
pub fn replay(
    scenario: &Scenario,
    ui: &Ui,
    width: usize,
    skip_unsupported: bool,
) -> Result<Replayed, String> {
    let mut app = App::new(ui);
    let mut snapshots = Vec::new();
    for (i, step) in scenario.steps.iter().enumerate() {
        let at = |m: String| format!("step {i}: {m}");
        let mut sent = Vec::new();
        if let (Some(command), Some(expect)) = (&step.command, &step.expect) {
            let produced = match command {
                Command::UserMessage { text, .. } => Some(type_and_send(&mut app, text)),
                Command::Interrupt {} => Some(app.update(Input::Key(Key::Esc))),
                Command::Slash { name, args } => {
                    let line = if args.is_empty() {
                        format!("/{name}")
                    } else {
                        format!("/{name} {args}")
                    };
                    Some(type_and_send(&mut app, &line))
                }
                _ => None,
            };
            match produced {
                Some(commands) => {
                    let [one] = commands.as_slice() else {
                        return Err(at(format!(
                            "the interface sent {} commands, expected one",
                            commands.len()
                        )));
                    };
                    let value = serde_json::to_value(one).unwrap_or(Value::Null);
                    for (key, want) in expect {
                        if value.get(key) != Some(want) {
                            return Err(at(format!(
                                "command field `{key}` is {:?}, the scenario expects {want}",
                                value.get(key)
                            )));
                        }
                    }
                    sent = commands;
                }
                None if skip_unsupported => {}
                None => {
                    return Err(at(format!(
                        "the interface cannot send a {} yet",
                        command.type_name()
                    )));
                }
            }
        }
        if let Some(wait) = step.wait {
            app.update(Input::Tick(wait));
        }
        for event in &step.emit {
            app.update(Input::Event(event.clone()));
        }
        snapshots.push(Snapshot {
            step: i,
            screen: app.screen_text(width),
            commands: sent,
        });
    }
    Ok(Replayed { app, snapshots })
}
