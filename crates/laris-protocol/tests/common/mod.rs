//! Helpers shared by the integration tests: fixture lookup and a small JSON Schema validator.

#![allow(dead_code, missing_docs)]

use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

pub fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

/// File names (without directory) of a fixture group, sorted.
pub fn files(group: &str) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = fs::read_dir(fixtures().join(group))
        .unwrap_or_else(|e| panic!("fixture group {group}: {e}"))
        .filter_map(Result::ok)
        .map(|e| e.path())
        .collect();
    out.sort();
    out
}

pub fn text(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

pub fn json(path: &Path) -> Value {
    serde_json::from_str(&text(path)).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// Fixture stem: `chat_text.response.sse` gives `chat_text`.
pub fn stem(path: &Path) -> String {
    path.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .split('.')
        .next()
        .unwrap_or("")
        .to_owned()
}

/// Every key of `original` is in `copy` with an equal value (extra keys in `copy` are allowed).
pub fn subset(original: &Value, copy: &Value) -> bool {
    match (original, copy) {
        (Value::Object(a), Value::Object(b)) => a
            .iter()
            .all(|(k, v)| b.get(k).is_some_and(|w| subset(v, w))),
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(x, y)| subset(x, y))
        }
        _ => original == copy,
    }
}

/// Validates `value` against the subset of JSON Schema that schemars emits for the protocol types:
/// `$ref`/`$defs`, `type` (also as a list), `properties`, `required`, `items`, `enum`, `const`,
/// `anyOf`, `oneOf`, `allOf` and `additionalProperties`. Returns the first error with its path.
pub fn validate(root: &Value, schema: &Value, value: &Value) -> Result<(), String> {
    check(root, schema, value, "$")
}

fn resolve<'a>(root: &'a Value, schema: &'a Value) -> &'a Value {
    match schema.get("$ref").and_then(Value::as_str) {
        Some(r) => r
            .strip_prefix('#')
            .and_then(|p| root.pointer(p))
            .unwrap_or(schema),
        None => schema,
    }
}

fn type_ok(name: &str, v: &Value) -> bool {
    match name {
        "null" => v.is_null(),
        "boolean" => v.is_boolean(),
        "string" => v.is_string(),
        "array" => v.is_array(),
        "object" => v.is_object(),
        "number" => v.is_number(),
        "integer" => v.as_i64().is_some() || v.as_u64().is_some(),
        _ => true,
    }
}

fn check(root: &Value, schema: &Value, v: &Value, at: &str) -> Result<(), String> {
    let schema = resolve(root, schema);
    if schema.as_bool() == Some(true) || schema.as_object().is_some_and(|o| o.is_empty()) {
        return Ok(());
    }
    if schema.as_bool() == Some(false) {
        return Err(format!("{at}: not allowed"));
    }
    if let Some(t) = schema.get("type") {
        let ok = match t {
            Value::String(s) => type_ok(s, v),
            Value::Array(a) => a.iter().filter_map(Value::as_str).any(|s| type_ok(s, v)),
            _ => true,
        };
        if !ok {
            return Err(format!("{at}: expected type {t}, got {v}"));
        }
    }
    if let (Some(min), Some(n)) = (schema.get("minimum").and_then(Value::as_f64), v.as_f64())
        && n < min
    {
        return Err(format!("{at}: {v} below minimum {min}"));
    }
    if let Some(c) = schema.get("const")
        && c != v
    {
        return Err(format!("{at}: expected {c}"));
    }
    if let Some(e) = schema.get("enum").and_then(Value::as_array)
        && !e.contains(v)
    {
        return Err(format!("{at}: {v} not in enum"));
    }
    for key in ["anyOf", "oneOf"] {
        if let Some(options) = schema.get(key).and_then(Value::as_array)
            && !options.iter().any(|o| check(root, o, v, at).is_ok())
        {
            return Err(format!("{at}: matches none of {key}"));
        }
    }
    if let Some(all) = schema.get("allOf").and_then(Value::as_array) {
        for s in all {
            check(root, s, v, at)?;
        }
    }
    if let Value::Object(obj) = v {
        if let Some(req) = schema.get("required").and_then(Value::as_array) {
            for k in req.iter().filter_map(Value::as_str) {
                if !obj.contains_key(k) {
                    return Err(format!("{at}: missing required `{k}`"));
                }
            }
        }
        let props = schema.get("properties").and_then(Value::as_object);
        for (k, val) in obj {
            let sub = props
                .and_then(|p| p.get(k))
                .or_else(|| schema.get("additionalProperties"));
            if let Some(sub) = sub {
                check(root, sub, val, &format!("{at}.{k}"))?;
            }
        }
    }
    if let (Value::Array(items), Some(sub)) = (v, schema.get("items")) {
        for (i, item) in items.iter().enumerate() {
            check(root, sub, item, &format!("{at}[{i}]"))?;
        }
    }
    Ok(())
}
