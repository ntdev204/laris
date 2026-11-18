//! The settings file on disk: strict read, generation-1 flat files converted in memory, atomic validated write,
//! and dotted-path access for a settings panel.

use crate::error::{ConfigError, ErrorKind};
use crate::settings::Settings;
use serde_json::{Map, Value};
use std::io::Write;
use std::path::Path;

/// Larger settings files are refused.
pub const MAX_BYTES: u64 = 1_048_576;

/// Keys of a generation-1 flat `settings.json` and the nested path each becomes.
const LEGACY: [(&str, &str); 8] = [
    ("base_url", "server.url"),
    ("model", "model"),
    ("auto_compact", "context.autoCompact"),
    ("context_window", "context.windowTokens"),
    ("compact_threshold", "context.compactThreshold"),
    ("learning_enabled", "learning.collect"),
    ("vault_record", "vault.autoRecord"),
    ("extra_instructions", "extraInstructions"),
];
/// Legacy keys that are dropped (`api_key` is never carried over) or converted by hand (`allow_write`).
const LEGACY_OTHER: [&str; 4] = ["api_key", "api_key_env", "ca_file", "allow_write"];

/// Whether `data` is a generation-1 flat file: it has legacy keys and nothing but legacy keys (and `$schema`).
pub fn is_legacy(data: &Map<String, Value>) -> bool {
    let known =
        |k: &String| LEGACY.iter().any(|(l, _)| l == k) || LEGACY_OTHER.contains(&k.as_str());
    data.keys().any(known) && data.keys().all(|k| known(k) || k == "$schema")
}

/// A generation-1 flat file as the nested shape. The API key is not carried over.
pub fn from_legacy(flat: &Map<String, Value>) -> Value {
    let mut out = Value::Object(Map::new());
    for (old, path) in LEGACY {
        if let Some(value) = flat.get(old) {
            set_path_unchecked(&mut out, path, value.clone());
        }
    }
    if let Some(Value::Bool(allow)) = flat.get("allow_write") {
        let mode = if *allow { "acceptEdits" } else { "default" };
        set_path_unchecked(&mut out, "permissions.defaultMode", Value::from(mode));
    }
    out
}

const SECRET_MARKERS: [&str; 5] = ["password", "secret", "token", "key", "credential"];

/// Rejects a credential written into a settings file: a key that names one, holding non-empty text.
pub fn reject_literal_secrets(value: &Value) -> Result<(), ConfigError> {
    fn walk(value: &Value, path: &str) -> Result<(), ConfigError> {
        match value {
            Value::Object(map) => {
                for (key, child) in map {
                    let here = crate::validate::join_key(path, key);
                    let lower = key.to_lowercase();
                    let sensitive = SECRET_MARKERS.iter().any(|m| lower.contains(m));
                    if sensitive && child.as_str().is_some_and(|s| !s.trim().is_empty()) {
                        return Err(ConfigError::at(here, ErrorKind::LiteralSecret));
                    }
                    walk(child, &here)?;
                }
            }
            Value::Array(items) => {
                for (i, item) in items.iter().enumerate() {
                    walk(item, &crate::validate::join_index(path, i))?;
                }
            }
            _ => {}
        }
        Ok(())
    }
    walk(value, "")
}

/// Reads the settings file as a layer. A missing file is `None`; invalid JSON, a non-object, an oversized file
/// and a literal secret are errors naming the file. The layer is not yet validated against the schema.
pub fn read_settings(path: &Path) -> Result<Option<Value>, ConfigError> {
    let name = path.display().to_string();
    let meta = match std::fs::metadata(path) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => {
            return Err(ConfigError::at(
                "",
                ErrorKind::Unreadable {
                    detail: e.to_string(),
                },
            )
            .from_source(name));
        }
    };
    if meta.len() > MAX_BYTES {
        return Err(ConfigError::at(
            "",
            ErrorKind::TooLarge {
                limit: MAX_BYTES.to_string(),
            },
        )
        .from_source(name));
    }
    let text = std::fs::read_to_string(path).map_err(|e| {
        ConfigError::at(
            "",
            ErrorKind::Unreadable {
                detail: e.to_string(),
            },
        )
        .from_source(name.clone())
    })?;
    let parsed: Value = serde_json::from_str(&text).map_err(|e| {
        ConfigError::at(
            "",
            ErrorKind::InvalidJson {
                detail: e.to_string(),
            },
        )
        .from_source(name.clone())
    })?;
    let Value::Object(map) = parsed else {
        return Err(ConfigError::at("", ErrorKind::NotObject).from_source(name));
    };
    let layer = if is_legacy(&map) {
        from_legacy(&map)
    } else {
        Value::Object(map)
    };
    reject_literal_secrets(&layer).map_err(|e| e.from_source(name))?;
    Ok(Some(layer))
}

/// Validates `data` and writes it to `path` atomically: the new content goes to a temporary file beside the
/// target, is synced, and replaces the target by rename, so a crash leaves the old file or the new one. An invalid
/// `data` writes nothing.
pub fn write_settings(path: &Path, data: &Value) -> Result<(), ConfigError> {
    let name = path.display().to_string();
    Settings::from_value(data)?;
    reject_literal_secrets(data)?;
    let failed = |e: std::io::Error| {
        ConfigError::at(
            "",
            ErrorKind::WriteFailed {
                detail: e.to_string(),
            },
        )
        .from_source(name.clone())
    };
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        std::fs::create_dir_all(dir).map_err(failed)?;
    }
    let mut text = serde_json::to_string_pretty(data).map_err(|e| {
        ConfigError::at(
            "",
            ErrorKind::WriteFailed {
                detail: e.to_string(),
            },
        )
        .from_source(name.clone())
    })?;
    text.push('\n');
    let tmp = path.with_extension("json.tmp");
    let mut file = std::fs::File::create(&tmp).map_err(failed)?;
    file.write_all(text.as_bytes()).map_err(failed)?;
    file.sync_all().map_err(failed)?;
    drop(file);
    std::fs::rename(&tmp, path).map_err(failed)
}

/// The value at a dotted path (`context.autoCompact`), if present.
pub fn get_path<'a>(data: &'a Value, dotted: &str) -> Option<&'a Value> {
    dotted
        .split('.')
        .try_fold(data, |node, part| node.get(part))
}

fn set_path_unchecked(data: &mut Value, dotted: &str, value: Value) {
    let mut node = data;
    let parts: Vec<&str> = dotted.split('.').collect();
    for part in &parts[..parts.len().saturating_sub(1)] {
        if !node.is_object() {
            *node = Value::Object(Map::new());
        }
        if let Value::Object(map) = node {
            node = map
                .entry((*part).to_owned())
                .or_insert_with(|| Value::Object(Map::new()));
        }
    }
    if let Some(last) = parts.last() {
        if !node.is_object() {
            *node = Value::Object(Map::new());
        }
        if let Value::Object(map) = node {
            map.insert((*last).to_owned(), value);
        }
    }
}

/// A copy of `data` with `dotted` set; the whole result is validated before it is returned.
pub fn set_path(data: &Value, dotted: &str, value: Value) -> Result<Value, ConfigError> {
    let mut out = data.clone();
    set_path_unchecked(&mut out, dotted, value);
    Settings::from_value(&out)?;
    Ok(out)
}

/// `true`, `12`, `["a"]` and `{"k": 1}` are JSON; anything else is text.
pub fn parse_value(text: &str) -> Value {
    serde_json::from_str(text).unwrap_or_else(|_| Value::from(text))
}
