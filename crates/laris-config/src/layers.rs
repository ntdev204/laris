//! Layers and precedence: `LARIS_*` environment over the settings file over the packaged defaults over the
//! defaults of [`Settings`].
//!
//! Environment names are `LARIS_<SECTION>__<KEY>`: segments are matched to settings keys ignoring case and
//! underscores (`LARIS_CONTEXT__WINDOW_TOKENS` sets `context.windowTokens`). Keys of a map (`env`, `hooks`) keep
//! the case written. A name with one segment is a setting only when it names a top-level scalar
//! (`LARIS_MODEL`); other `LARIS_*` variables belong to other components and are left alone. A value is read as
//! the type of its setting: text stays text, booleans take `true/false/yes/no/1/0`, lists and objects are JSON.

use crate::error::{ConfigError, ErrorKind};
use crate::files;
use crate::packaged::Packaged;
use crate::settings::{self, Settings};
use crate::validate::{allowed_types, join_key, resolve as follow_ref};
use serde_json::{Map, Number, Value};
use std::path::Path;

/// Prefix of the environment variables that set configuration.
pub const ENV_PREFIX: &str = "LARIS_";
/// Separator between the segments of a nested key.
pub const ENV_SEPARATOR: &str = "__";

/// Deep-merges `over` into `base`: objects merge key by key, everything else is replaced.
pub fn merge(base: &mut Value, over: Value) {
    match (base, over) {
        (Value::Object(b), Value::Object(o)) => {
            for (key, value) in o {
                match b.get_mut(&key) {
                    Some(slot) => merge(slot, value),
                    None => {
                        b.insert(key, value);
                    }
                }
            }
        }
        (slot, other) => *slot = other,
    }
}

fn squash(name: &str) -> String {
    name.chars()
        .filter(|c| *c != '_')
        .flat_map(char::to_lowercase)
        .collect()
}

/// The schema node of property `segment` below `node`, with the key as the schema spells it. A map node
/// (`additionalProperties` as a schema) accepts any key and keeps it as written.
fn child<'a>(root: &'a Value, node: &'a Value, segment: &str) -> Option<(String, &'a Value)> {
    let node = follow_ref(root, node);
    if let Some(props) = node.get("properties").and_then(Value::as_object) {
        let wanted = squash(segment);
        if let Some((key, sub)) = props.iter().find(|(k, _)| squash(k) == wanted) {
            return Some((key.clone(), sub));
        }
    }
    match node.get("additionalProperties") {
        Some(sub @ Value::Object(_)) => Some((segment.to_owned(), sub)),
        _ => None,
    }
}

fn read_value(text: &str, types: &[String]) -> Option<Value> {
    let trimmed = text.trim();
    if types.is_empty() || types.iter().any(|t| t == "string") {
        return Some(Value::from(text));
    }
    for t in types {
        let parsed = match t.as_str() {
            "boolean" => match trimmed.to_ascii_lowercase().as_str() {
                "true" | "yes" | "1" => Some(Value::Bool(true)),
                "false" | "no" | "0" => Some(Value::Bool(false)),
                _ => None,
            },
            "integer" => trimmed
                .parse::<i64>()
                .ok()
                .map(Value::from)
                .or_else(|| trimmed.parse::<u64>().ok().map(Value::from)),
            "number" => trimmed
                .parse::<f64>()
                .ok()
                .and_then(Number::from_f64)
                .map(Value::Number),
            "array" | "object" => serde_json::from_str::<Value>(trimmed)
                .ok()
                .filter(|v| (t == "array" && v.is_array()) || (t == "object" && v.is_object())),
            _ => None,
        };
        if parsed.is_some() {
            return parsed;
        }
    }
    None
}

/// The environment as a configuration layer, with the JSON path each variable set.
///
/// Returns the layer and `(json path, variable name)` pairs, so that an error in the merged result can name the
/// variable. `vars` are `(name, value)` pairs, for instance `std::env::vars()`; they are processed in name order.
pub fn env_layer(
    schema: &Value,
    vars: &[(String, String)],
) -> Result<(Value, Vec<(String, String)>), ConfigError> {
    let mut sorted: Vec<&(String, String)> = vars
        .iter()
        .filter(|(n, _)| n.starts_with(ENV_PREFIX))
        .collect();
    sorted.sort();
    let mut layer = Value::Object(Map::new());
    let mut origins = Vec::new();
    for (name, text) in sorted {
        let segments: Vec<&str> = name[ENV_PREFIX.len()..].split(ENV_SEPARATOR).collect();
        let mut node = schema;
        let mut keys = Vec::new();
        let mut known = true;
        for segment in &segments {
            match child(schema, node, segment) {
                Some((key, sub)) => {
                    keys.push(key);
                    node = sub;
                }
                None => {
                    known = false;
                    break;
                }
            }
        }
        if !known {
            if segments.len() == 1 {
                continue; // `LARIS_API_KEY`, `LARIS_PACKAGED_DEFAULTS`, ...: not a setting
            }
            return Err(ConfigError::at(name.clone(), ErrorKind::UnknownSetting));
        }
        if segments.len() == 1 && !is_scalar(schema, node) {
            continue;
        }
        let types = allowed_types(schema, node);
        let value = read_value(text, &types).ok_or_else(|| {
            ConfigError::at(
                name.clone(),
                ErrorKind::EnvValue {
                    expected: types.join(" or "),
                },
            )
        })?;
        let mut path = String::new();
        let mut slot = &mut layer;
        for key in &keys {
            path = join_key(&path, key);
            if let Value::Object(map) = slot {
                slot = map
                    .entry(key.clone())
                    .or_insert_with(|| Value::Object(Map::new()));
            }
        }
        *slot = value;
        origins.push((path, name.clone()));
    }
    Ok((layer, origins))
}

fn is_scalar(schema: &Value, node: &Value) -> bool {
    let types = allowed_types(schema, node);
    !types.is_empty() && types.iter().all(|t| t != "object" && t != "array")
}

/// Resolves the layers into typed settings. `packaged` and `file` are layers (`Null` for none); each file
/// layer is checked on its own and errors are attributed to `file_name`; `env` is `(name, value)` pairs.
pub fn resolve_layers(
    packaged: Value,
    file: Option<(&str, Value)>,
    env: &[(String, String)],
) -> Result<Settings, ConfigError> {
    let schema = settings::schema();
    let mut merged = Value::Object(Map::new());
    if packaged.is_object() {
        merge(&mut merged, packaged);
    }
    if let Some((name, layer)) = file {
        Settings::from_value(&layer).map_err(|e| e.from_source(name))?;
        merge(&mut merged, layer);
    }
    let (env_values, origins) = env_layer(&schema, env)?;
    merge(&mut merged, env_values);
    Settings::from_value(&merged).map_err(|e| {
        match origins.iter().find(|(path, _)| *path == e.path) {
            Some((_, var)) => e.from_source(var.clone()),
            None => e,
        }
    })
}

/// [`resolve_layers`] with the packaged defaults and a file layer already read.
pub fn resolve(
    packaged: &Packaged,
    file: Option<(&str, Value)>,
    env: &[(String, String)],
) -> Result<Settings, ConfigError> {
    resolve_layers(packaged.layer(), file, env)
}

/// Where the layers are read from.
#[derive(Debug, Clone, Copy)]
pub struct LoadOptions<'a> {
    /// The settings file; `None` or a missing file gives no layer.
    pub settings_path: Option<&'a Path>,
    /// The packaged defaults.
    pub packaged: &'a Packaged,
    /// The environment as `(name, value)` pairs.
    pub env: &'a [(String, String)],
}

/// Reads the settings file and resolves all layers.
pub fn load(options: &LoadOptions<'_>) -> Result<Settings, ConfigError> {
    let file = match options.settings_path {
        Some(path) => files::read_settings(path)?.map(|layer| (path.display().to_string(), layer)),
        None => None,
    };
    resolve(
        options.packaged,
        file.as_ref().map(|(n, v)| (n.as_str(), v.clone())),
        options.env,
    )
}
