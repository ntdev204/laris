//! Configuration errors: a kind with its values, the JSON path, and where the value came from.

use crate::catalogue::Catalogue;
use std::fmt;

/// What is wrong. Each kind is a catalogue key (`config.error.<name>`) plus its placeholders.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ErrorKind {
    /// A key the schema does not know.
    UnknownSetting,
    /// Wrong JSON type.
    ExpectedType {
        /// Type the schema asks for.
        expected: String,
        /// Type found.
        found: String,
    },
    /// Not one of the allowed values.
    NotInEnum {
        /// The allowed values, comma separated.
        allowed: String,
    },
    /// Below `minimum`.
    BelowMinimum {
        /// The limit.
        limit: String,
    },
    /// Above `maximum`.
    AboveMaximum {
        /// The limit.
        limit: String,
    },
    /// Not above `exclusiveMinimum`.
    NotAbove {
        /// The limit.
        limit: String,
    },
    /// Not below `exclusiveMaximum`.
    NotBelow {
        /// The limit.
        limit: String,
    },
    /// Shorter than `minLength`.
    TooShort {
        /// The minimum length.
        min: String,
    },
    /// A required key is absent.
    MissingRequired {
        /// The key.
        name: String,
    },
    /// Matches none of the alternatives.
    NoMatch,
    /// The schema forbids any value here.
    NotAllowed,
    /// The text is not JSON.
    InvalidJson {
        /// Parser message with position.
        detail: String,
    },
    /// The document is not a JSON object.
    NotObject,
    /// A credential written into a file.
    LiteralSecret,
    /// A server address without `http://` or `https://`.
    UrlScheme,
    /// A fingerprint that is not `sha256:` and 64 hex digits.
    FingerprintFormat,
    /// A hook event that does not exist.
    UnknownHookEvent {
        /// The event given.
        event: String,
        /// The known events, comma separated.
        known: String,
    },
    /// An environment value that does not read as the type of its setting.
    EnvValue {
        /// Type the setting needs.
        expected: String,
    },
    /// The file cannot be read.
    Unreadable {
        /// System message.
        detail: String,
    },
    /// The file is too large.
    TooLarge {
        /// The limit in bytes.
        limit: String,
    },
    /// The file cannot be written.
    WriteFailed {
        /// System message.
        detail: String,
    },
}

impl ErrorKind {
    /// Catalogue key of the message.
    pub fn key(&self) -> &'static str {
        match self {
            Self::UnknownSetting => "config.error.unknown_setting",
            Self::ExpectedType { .. } => "config.error.expected_type",
            Self::NotInEnum { .. } => "config.error.not_in_enum",
            Self::BelowMinimum { .. } => "config.error.below_minimum",
            Self::AboveMaximum { .. } => "config.error.above_maximum",
            Self::NotAbove { .. } => "config.error.not_above",
            Self::NotBelow { .. } => "config.error.not_below",
            Self::TooShort { .. } => "config.error.too_short",
            Self::MissingRequired { .. } => "config.error.missing_required",
            Self::NoMatch => "config.error.no_match",
            Self::NotAllowed => "config.error.not_allowed",
            Self::InvalidJson { .. } => "config.error.invalid_json",
            Self::NotObject => "config.error.not_object",
            Self::LiteralSecret => "config.error.literal_secret",
            Self::UrlScheme => "config.error.url_scheme",
            Self::FingerprintFormat => "config.error.fingerprint_format",
            Self::UnknownHookEvent { .. } => "config.error.unknown_hook_event",
            Self::EnvValue { .. } => "config.error.env_value",
            Self::Unreadable { .. } => "config.error.unreadable",
            Self::TooLarge { .. } => "config.error.too_large",
            Self::WriteFailed { .. } => "config.error.write_failed",
        }
    }

    /// Placeholder values of the message.
    pub fn args(&self) -> Vec<(&'static str, &str)> {
        match self {
            Self::ExpectedType { expected, found } => {
                vec![("expected", expected), ("found", found)]
            }
            Self::NotInEnum { allowed } => vec![("allowed", allowed)],
            Self::BelowMinimum { limit }
            | Self::AboveMaximum { limit }
            | Self::NotAbove { limit }
            | Self::NotBelow { limit }
            | Self::TooLarge { limit } => vec![("limit", limit)],
            Self::TooShort { min } => vec![("min", min)],
            Self::MissingRequired { name } => vec![("name", name)],
            Self::InvalidJson { detail }
            | Self::Unreadable { detail }
            | Self::WriteFailed { detail } => {
                vec![("detail", detail)]
            }
            Self::UnknownHookEvent { event, known } => vec![("event", event), ("known", known)],
            Self::EnvValue { expected } => vec![("expected", expected)],
            _ => Vec::new(),
        }
    }
}

/// A configuration problem: what, at which JSON path, from which file or variable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigError {
    /// File name or environment variable the value came from, when known.
    pub source: Option<String>,
    /// JSON path of the value (`permissions.defaultMode`, `hooks.PreToolUse[0].hooks[0].timeout`); empty for the
    /// document itself.
    pub path: String,
    /// What is wrong.
    pub kind: ErrorKind,
}

impl ConfigError {
    /// An error at `path` with no known source.
    pub fn at(path: impl Into<String>, kind: ErrorKind) -> Self {
        Self {
            source: None,
            path: path.into(),
            kind,
        }
    }

    /// The same error attributed to `source`, unless it already has one.
    pub fn from_source(mut self, source: impl Into<String>) -> Self {
        self.source.get_or_insert_with(|| source.into());
        self
    }

    /// `source: path: message` in the language of `catalogue`.
    pub fn render(&self, catalogue: &Catalogue) -> String {
        let message = catalogue
            .get(self.kind.key(), &self.kind.args())
            .unwrap_or_else(|e| e.to_string());
        let path = if self.path.is_empty() {
            catalogue.get("config.root", &[]).unwrap_or_default()
        } else {
            self.path.clone()
        };
        match &self.source {
            Some(source) => format!("{source}: {path}: {message}"),
            None => format!("{path}: {message}"),
        }
    }
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.render(&Catalogue::english()))
    }
}

impl std::error::Error for ConfigError {}
