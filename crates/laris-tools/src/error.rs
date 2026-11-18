//! The typed error of a tool: `{"error": {"code", "message", ...}}`, returned to the model, never raised.

use serde_json::{Map, Value, json};

/// Why a tool call failed. `code` is stable (the loop's progress check and the permanent-error list read it);
/// `message` is for the model and the person; `extra` carries facts such as the number of matches.
#[derive(Clone, Debug, PartialEq)]
pub struct ToolError {
    /// Stable machine-readable code.
    pub code: String,
    /// What went wrong.
    pub message: String,
    /// Further fields of the error object.
    pub extra: Map<String, Value>,
}

impl ToolError {
    /// An error with `code` and `message`.
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.to_owned(),
            message: message.into(),
            extra: Map::new(),
        }
    }

    /// The same error with one more field.
    #[must_use]
    pub fn with(mut self, key: &str, value: impl Into<Value>) -> Self {
        self.extra.insert(key.to_owned(), value.into());
        self
    }

    /// The `{"error": ...}` value the loop reads.
    pub fn to_value(&self) -> Value {
        let mut error = Map::new();
        error.insert("code".to_owned(), json!(self.code));
        error.insert("message".to_owned(), json!(self.message));
        for (key, value) in &self.extra {
            if key != "code" && key != "message" {
                error.insert(key.clone(), value.clone());
            }
        }
        json!({ "error": error })
    }

    /// The error of an I/O failure at `what`, with the operating-system reason.
    pub fn io(code: &str, what: &str, error: &std::io::Error) -> Self {
        Self::new(code, format!("{what}: {error}"))
    }
}

impl std::fmt::Display for ToolError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for ToolError {}
