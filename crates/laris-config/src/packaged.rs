//! Defaults written into the package at build time (ADR-019 D24 carries over).
//!
//! A release may ship the server address and, for a server with a private certificate authority, the
//! fingerprint of that authority, as JSON beside the binary:
//!
//! ```json
//! {"server": {"url": "<address>", "caFingerprint": "sha256:<hex>"},
//!  "update": {"url": "<release address>", "signatureVerifier": "<PEM or its base64 body>"}}
//! ```
//!
//! It is the lowest layer: the settings file and the `LARIS_*` environment both override it. `LARIS_PACKAGED_DEFAULTS`
//! names another file (tests, a development checkout). A broken or oversized file never stops a start: it counts as
//! empty. Only a well-formed address is taken, and the fingerprint is never copied into the settings layer, so the
//! pin recorded in the settings file keeps meaning "verified by the user".

use crate::settings::server_address;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

/// Environment variable that names the defaults file.
pub const ENV: &str = "LARIS_PACKAGED_DEFAULTS";
/// File name beside the executable.
pub const FILE_NAME: &str = "defaults.json";
/// Larger files are ignored.
pub const MAX_BYTES: u64 = 65536;
/// Defaults compiled in from the `LARIS_BUILD_DEFAULTS` variable of the build, when it was set.
pub const BUILD_TIME: Option<&str> = option_env!("LARIS_BUILD_DEFAULTS");

/// What the package vouches for.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Packaged {
    /// Complete server address (`https://host/v1`), if the package has one.
    pub server_url: Option<String>,
    /// Fingerprint of the server's certificate authority, if the package has one.
    pub ca_fingerprint: Option<String>,
    /// Release address of the client's updates (`https://`), if the package has one.
    pub update_url: Option<String>,
    /// Release signing key (PEM or its base64 body), if the package has one.
    pub update_verifier: Option<String>,
}

impl Packaged {
    /// Reads the defaults from JSON text; anything unusable gives the empty value.
    pub fn parse(text: &str) -> Self {
        let Ok(Value::Object(root)) = serde_json::from_str::<Value>(text) else {
            return Self::default();
        };
        let mut found = Self::default();
        if let Some(Value::Object(server)) = root.get("server")
            && let Some(url) = server
                .get("url")
                .and_then(Value::as_str)
                .filter(|u| u.starts_with("https://") || u.starts_with("http://"))
                .map(server_address)
        {
            found.server_url = Some(url);
            found.ca_fingerprint = server
                .get("caFingerprint")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|f| !f.is_empty())
                .map(str::to_owned);
        }
        if let Some(Value::Object(update)) = root.get("update") {
            let text = |name: &str| {
                update
                    .get(name)
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|t| !t.is_empty())
                    .map(str::to_owned)
            };
            found.update_url = text("url")
                .filter(|u| u.starts_with("https://"))
                .map(|u| u.trim_end_matches('/').to_owned());
            found.update_verifier = text("signatureVerifier");
        }
        found
    }

    /// Reads the defaults file at `path`; absent, oversized or unreadable gives the empty value.
    pub fn load(path: &Path) -> Self {
        match std::fs::metadata(path) {
            Ok(meta) if meta.is_file() && meta.len() <= MAX_BYTES => {}
            _ => return Self::default(),
        }
        std::fs::read_to_string(path)
            .map(|t| Self::parse(&t))
            .unwrap_or_default()
    }

    /// The defaults of this build: the file when there is one, else the compiled-in text.
    pub fn discover(named: Option<&str>, exe: Option<&Path>) -> Self {
        if let Some(path) = locate(named, exe) {
            let found = Self::load(&path);
            if found != Self::default() {
                return found;
            }
        }
        BUILD_TIME.map(Self::parse).unwrap_or_default()
    }

    /// The configuration layer: the server address and the update source, as
    /// `{"server": {"url": ...}, "update": {...}}`; `Null` when there is none.
    pub fn layer(&self) -> Value {
        let mut layer = serde_json::Map::new();
        if let Some(url) = &self.server_url {
            layer.insert("server".to_owned(), json!({"url": url}));
        }
        let mut update = serde_json::Map::new();
        if let Some(url) = &self.update_url {
            update.insert("url".to_owned(), json!(url));
        }
        if let Some(key) = &self.update_verifier {
            update.insert("signatureVerifier".to_owned(), json!(key));
        }
        if !update.is_empty() {
            layer.insert("update".to_owned(), Value::Object(update));
        }
        if layer.is_empty() {
            Value::Null
        } else {
            Value::Object(layer)
        }
    }
}

/// Where the defaults of this installation are: the file named by `LARIS_PACKAGED_DEFAULTS` (`named`), else
/// `defaults.json` in the directory of the executable `exe`.
pub fn locate(named: Option<&str>, exe: Option<&Path>) -> Option<PathBuf> {
    match named.filter(|n| !n.is_empty()) {
        Some(name) => Some(PathBuf::from(name)),
        None => exe.and_then(Path::parent).map(|dir| dir.join(FILE_NAME)),
    }
}
