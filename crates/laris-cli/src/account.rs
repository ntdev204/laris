//! `laris login`, `laris logout` and `laris status`: the commands around the key. The interface's login form
//! ([`crate::login::LoginForm`]) uses the same steps.

use crate::login::{self, KeySource, KeyVerifier, LoginForm, Reason, Startup};
use crate::start::Started;
use laris_config::Catalogue;
use serde_json::json;

fn words(started: &Started) -> Catalogue {
    Catalogue::new(started.settings.ui.language)
}

/// `laris login`: `typed` is what was read from standard input. The first non-empty line is the key. The reply is
/// the confirmation; an error is the message the form would show.
pub fn login(started: &Started, typed: &str, verifier: &dyn KeyVerifier) -> Result<String, String> {
    let words = words(started);
    let mut form = LoginForm::new(started.settings.server.clone());
    let line = typed
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .unwrap_or("");
    match form.submit(&started.home, line, verifier) {
        Some(signed) => words
            .get(
                "login.saved",
                &[
                    ("role", &signed.account.role),
                    (
                        "path",
                        &started.home.credentials_path().display().to_string(),
                    ),
                ],
            )
            .map_err(|e| e.to_string()),
        None => {
            let error = form.error().cloned().ok_or("login failed")?;
            Err(error
                .message(&words, &form.server())
                .map_err(|e| e.to_string())?)
        }
    }
}

/// `laris logout`: removes the saved key.
pub fn logout(started: &Started) -> Result<String, String> {
    let words = words(started);
    let removed = login::sign_out(&started.home).map_err(|e| e.to_string())?;
    let key = if removed {
        "login.signed_out"
    } else {
        "login.no_saved_key"
    };
    words.get(key, &[]).map_err(|e| e.to_string())
}

/// `laris status`: where things are and whether a key is available, as JSON. The key itself is never shown.
pub fn status(started: &Started) -> String {
    let (server, signed_in, note) =
        match login::decide(&started.home, &started.settings, &started.env) {
            Startup::NoServer => (String::new(), None, Some("no server address")),
            Startup::NeedsLogin { server, reason } => {
                let note = match reason {
                    Reason::FirstRun => "not signed in",
                    Reason::OtherServer(_) => "the saved key belongs to another server",
                    Reason::Unreadable(_) => "the key cannot be used",
                };
                (server, None, Some(note))
            }
            Startup::Ready { server, source, .. } => {
                let source = match source {
                    KeySource::Environment => "environment",
                    KeySource::Saved => "saved",
                };
                (server, Some(source), None)
            }
        };
    let value = json!({
        "home": started.home.root(),
        "settings": started.home.settings_path(),
        "server": server,
        "signedIn": signed_in,
        "note": note,
        "project": started.project,
        "strayProjectEntries": started.project_folder().stray(),
        "language": started.settings.ui.language.code(),
    });
    serde_json::to_string_pretty(&value).unwrap_or_default()
}
