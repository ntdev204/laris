//! Start with nothing to configure, and sign in inside the interface (SR-C4).
//!
//! * [`decide`] says what the client does at start: use a key it has, show the login form, or tell the user that no
//!   server address exists (the package normally carries one, [`laris_config::packaged`]).
//! * [`LoginForm`] is the state behind the interface's login form. A key is saved only after the server accepts it
//!   ([`KeyVerifier`]); a refused key, an unreachable server and a malformed key all leave the form open with a
//!   message, and nothing is written.
//! * The key never appears in a message, in `Debug` output or in a setting. `LARIS_API_KEY` wins over the saved key;
//!   a saved key is used only for the server that accepted it.

use crate::credentials::{self, Saved};
use laris_config::home::Home;
use laris_config::settings::{Server, Settings, server_address};
use laris_config::{Catalogue, CatalogueError};
use laris_model_client::{
    API_KEY_ENV, ApiKey, ClientConfig, ClientError, HttpOptions, Interrupt, ModelClient,
    ReqwestTransport, Trust,
};
use laris_protocol::p1::AccountResponse;
use std::time::Duration;

/// Where the key in use comes from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeySource {
    /// `LARIS_API_KEY`.
    Environment,
    /// The credentials file.
    Saved,
}

/// Why the login form is shown.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Reason {
    /// No key yet.
    FirstRun,
    /// A key was saved, but another server accepted it.
    OtherServer(String),
    /// The credentials file is damaged.
    Unreadable(String),
}

/// What the client does at start.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Startup {
    /// No server address from the environment, the settings file or the package: nothing to sign in to.
    NoServer,
    /// Show the login form for this server.
    NeedsLogin {
        /// The complete server address.
        server: String,
        /// Why the form is shown.
        reason: Reason,
    },
    /// A key is available.
    Ready {
        /// The complete server address.
        server: String,
        /// The key.
        key: ApiKey,
        /// Where it came from.
        source: KeySource,
    },
}

/// Decides how to start. `settings` are the resolved settings (environment over file over package), `env` the
/// environment as pairs.
pub fn decide(home: &Home, settings: &Settings, env: &[(String, String)]) -> Startup {
    let server = server_address(&settings.server.url);
    if server.is_empty() {
        return Startup::NoServer;
    }
    let from_env = env
        .iter()
        .find(|(k, _)| k == API_KEY_ENV)
        .map(|(_, v)| v.trim())
        .filter(|v| !v.is_empty());
    if let Some(text) = from_env {
        return match ApiKey::new(text) {
            Ok(key) => Startup::Ready {
                server,
                key,
                source: KeySource::Environment,
            },
            Err(e) => Startup::NeedsLogin {
                server,
                reason: Reason::Unreadable(e.to_string()),
            },
        };
    }
    match credentials::read(&home.credentials_path()) {
        Ok(None) => Startup::NeedsLogin {
            server,
            reason: Reason::FirstRun,
        },
        Ok(Some(saved)) if saved.is_for(&server) => match ApiKey::new(saved.api_key) {
            Ok(key) => Startup::Ready {
                server,
                key,
                source: KeySource::Saved,
            },
            Err(e) => Startup::NeedsLogin {
                server,
                reason: Reason::Unreadable(e.to_string()),
            },
        },
        Ok(Some(saved)) => Startup::NeedsLogin {
            server,
            reason: Reason::OtherServer(saved.server),
        },
        Err(detail) => Startup::NeedsLogin {
            server,
            reason: Reason::Unreadable(detail),
        },
    }
}

/// Why a key was not taken.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoginError {
    /// There is no server address.
    NoServer,
    /// The key is empty or cannot travel in a header.
    InvalidKey(String),
    /// The server answered and refused the key.
    Rejected,
    /// The server could not be asked (network, certificate, version, other status).
    Unreachable(String),
    /// The server accepted the key, but the credentials file could not be written.
    SaveFailed(String),
}

impl LoginError {
    /// The message, in the language of the catalogue. It names the server and never the key.
    pub fn message(&self, words: &Catalogue, server: &str) -> Result<String, CatalogueError> {
        match self {
            Self::NoServer => words.get("login.no_server", &[("settings", "settings.json")]),
            Self::InvalidKey(detail) => words.get("login.invalid_key", &[("detail", detail)]),
            Self::Rejected => words.get("login.rejected", &[]),
            Self::Unreachable(detail) => words.get(
                "login.unreachable",
                &[("server", server), ("detail", detail)],
            ),
            Self::SaveFailed(detail) => words.get("login.save_failed", &[("detail", detail)]),
        }
    }
}

/// Why a verification failed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VerifyError {
    /// The server refused the key (401 or 403).
    Refused,
    /// The server could not be asked, or answered something else.
    Other(String),
}

/// Asks a server whether it accepts a key.
pub trait KeyVerifier {
    /// The account of the key, when `server` accepts it.
    fn verify(&self, server: &Server, key: &ApiKey) -> Result<AccountResponse, VerifyError>;
}

/// The real check: `GET /v1/laris/account` through the P1 client, with the pin and the limits of the `server`
/// settings.
#[derive(Debug, Clone, Copy)]
pub struct HttpVerifier {
    /// Honour `HTTPS_PROXY` and friends.
    pub use_env_proxy: bool,
}

impl KeyVerifier for HttpVerifier {
    fn verify(&self, server: &Server, key: &ApiKey) -> Result<AccountResponse, VerifyError> {
        let other = |e: ClientError| VerifyError::Other(e.to_string());
        let mut server = server.clone();
        server.url = server_address(&server.url);
        let config = ClientConfig::from_server(&server, Some(key.clone())).map_err(other)?;
        let connect = Duration::try_from_secs_f64(server.timeout_seconds)
            .map_err(|_| VerifyError::Other("server.timeoutSeconds is not usable".to_owned()))?;
        let transport = ReqwestTransport::new(&HttpOptions {
            connect_timeout: connect,
            trust: Trust::from_server(&server).map_err(other)?,
            use_env_proxy: self.use_env_proxy,
        })
        .map_err(other)?;
        let client = ModelClient::new(transport, config).map_err(other)?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| VerifyError::Other(e.to_string()))?;
        runtime
            .block_on(client.get_json::<AccountResponse>("/laris/account", &Interrupt::new()))
            .map_err(|e| match e {
                ClientError::Unauthorized(_) => VerifyError::Refused,
                other => VerifyError::Other(other.to_string()),
            })
    }
}

/// A key the server accepted and the client saved.
#[derive(Debug, Clone, PartialEq)]
pub struct Signed {
    /// What the server says about the key.
    pub account: AccountResponse,
    /// The key, ready for the client.
    pub key: ApiKey,
}

/// Checks `text` with the server and, only if it is accepted, saves it. Nothing is written on any failure.
pub fn sign_in(
    home: &Home,
    server: &Server,
    text: &str,
    verifier: &dyn KeyVerifier,
) -> Result<Signed, LoginError> {
    let address = server_address(&server.url);
    if address.is_empty() {
        return Err(LoginError::NoServer);
    }
    let key = ApiKey::new(text.trim()).map_err(|e| LoginError::InvalidKey(e.to_string()))?;
    let account = verifier.verify(server, &key).map_err(|e| match e {
        VerifyError::Refused => LoginError::Rejected,
        VerifyError::Other(detail) => LoginError::Unreachable(detail),
    })?;
    let saved = Saved {
        api_key: text.trim().to_owned(),
        server: address,
    };
    credentials::write(&home.credentials_path(), &saved)
        .map_err(|e| LoginError::SaveFailed(e.to_string()))?;
    Ok(Signed { account, key })
}

/// The state behind the login form: what is asked, what went wrong last time, how many tries were made.
#[derive(Debug, Clone)]
pub struct LoginForm {
    server: Server,
    error: Option<LoginError>,
    attempts: u32,
}

impl LoginForm {
    /// A fresh form for `server`.
    pub fn new(server: Server) -> Self {
        Self {
            server,
            error: None,
            attempts: 0,
        }
    }

    /// The complete address the key is checked against.
    pub fn server(&self) -> String {
        server_address(&self.server.url)
    }

    /// What went wrong with the last key, if anything. While this is set the form is shown again.
    pub fn error(&self) -> Option<&LoginError> {
        self.error.as_ref()
    }

    /// Keys tried so far.
    pub fn attempts(&self) -> u32 {
        self.attempts
    }

    /// Takes the key typed into the form. `Some` when it was accepted and saved (the form closes); `None` when it
    /// was not (the form stays open, [`LoginForm::error`] says why).
    pub fn submit(
        &mut self,
        home: &Home,
        text: &str,
        verifier: &dyn KeyVerifier,
    ) -> Option<Signed> {
        self.attempts += 1;
        match sign_in(home, &self.server, text, verifier) {
            Ok(signed) => {
                self.error = None;
                Some(signed)
            }
            Err(e) => {
                self.error = Some(e);
                None
            }
        }
    }
}

/// Removes the saved key; `false` when there was none.
pub fn sign_out(home: &Home) -> std::io::Result<bool> {
    credentials::remove(&home.credentials_path())
}
