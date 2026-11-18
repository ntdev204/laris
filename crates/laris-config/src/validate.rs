//! A small JSON Schema validator for the subset schemars emits for the settings types, with JSON-path errors.
//!
//! Supported: `$ref`/`$defs`, `type` (also as a list), `enum`, `const`, `minimum`, `maximum`,
//! `exclusiveMinimum`, `exclusiveMaximum`, `minLength`, `properties`, `required`, `additionalProperties`
//! (boolean or schema), `items`, `anyOf`, `oneOf` and `allOf`. Objects are checked in key order, so the first
//! error is deterministic. No validator crate is approved (T119), so this lives here.

use crate::error::{ConfigError, ErrorKind};
use serde_json::Value;

/// Appends an object key to a JSON path.
pub fn join_key(path: &str, key: &str) -> String {
    if path.is_empty() {
        key.to_owned()
    } else {
        format!("{path}.{key}")
    }
}

/// Appends an array index to a JSON path.
pub fn join_index(path: &str, index: usize) -> String {
    format!("{path}[{index}]")
}

/// Follows a local `$ref` (`#/$defs/Name`); other schemas are returned as they are.
pub fn resolve<'a>(root: &'a Value, schema: &'a Value) -> &'a Value {
    match schema.get("$ref").and_then(Value::as_str) {
        Some(reference) => reference
            .strip_prefix('#')
            .and_then(|pointer| root.pointer(pointer))
            .unwrap_or(schema),
        None => schema,
    }
}

/// The JSON type name of a value.
pub fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(n) if n.is_i64() || n.is_u64() => "integer",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

fn type_matches(name: &str, value: &Value) -> bool {
    match name {
        "number" => value.is_number(),
        other => type_name(value) == other,
    }
}

/// The non-null types a schema allows, after following `$ref`; empty when it does not say.
pub fn allowed_types(root: &Value, schema: &Value) -> Vec<String> {
    let schema = resolve(root, schema);
    let mut out: Vec<String> = match schema.get("type") {
        Some(Value::String(s)) => vec![s.clone()],
        Some(Value::Array(a)) => a
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect(),
        _ => Vec::new(),
    };
    if out.is_empty() {
        for key in ["anyOf", "oneOf"] {
            for branch in schema
                .get(key)
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                out.extend(allowed_types(root, branch));
            }
        }
    }
    out.retain(|t| t != "null");
    out.dedup();
    out
}

/// Checks `value` against `root`, the whole schema document.
pub fn check(root: &Value, value: &Value) -> Result<(), ConfigError> {
    node(root, root, value, "")
}

fn number(value: &Value) -> String {
    value.to_string()
}

fn node(root: &Value, schema: &Value, value: &Value, path: &str) -> Result<(), ConfigError> {
    let schema = resolve(root, schema);
    match schema {
        Value::Bool(true) => return Ok(()),
        Value::Bool(false) => return Err(ConfigError::at(path, ErrorKind::NotAllowed)),
        _ => {}
    }
    if let Some(t) = schema.get("type") {
        let names: Vec<&str> = match t {
            Value::String(s) => vec![s.as_str()],
            Value::Array(a) => a.iter().filter_map(Value::as_str).collect(),
            _ => Vec::new(),
        };
        if !names.is_empty() && !names.iter().any(|n| type_matches(n, value)) {
            return Err(ConfigError::at(
                path,
                ErrorKind::ExpectedType {
                    expected: names.join(" or "),
                    found: type_name(value).to_owned(),
                },
            ));
        }
    }
    if let Some(c) = schema.get("const")
        && c != value
    {
        return Err(ConfigError::at(
            path,
            ErrorKind::NotInEnum { allowed: number(c) },
        ));
    }
    if let Some(options) = schema.get("enum").and_then(Value::as_array)
        && !options.contains(value)
    {
        let allowed = options.iter().map(number).collect::<Vec<_>>().join(", ");
        return Err(ConfigError::at(path, ErrorKind::NotInEnum { allowed }));
    }
    numbers(schema, value, path)?;
    if let (Some(min), Value::String(text)) =
        (schema.get("minLength").and_then(Value::as_u64), value)
        && (text.chars().count() as u64) < min
    {
        return Err(ConfigError::at(
            path,
            ErrorKind::TooShort {
                min: min.to_string(),
            },
        ));
    }
    alternatives(root, schema, value, path)?;
    match value {
        Value::Object(map) => object(root, schema, map, path)?,
        Value::Array(items) => {
            if let Some(sub) = schema.get("items") {
                for (i, item) in items.iter().enumerate() {
                    node(root, sub, item, &join_index(path, i))?;
                }
            }
        }
        _ => {}
    }
    Ok(())
}

fn numbers(schema: &Value, value: &Value, path: &str) -> Result<(), ConfigError> {
    let Some(n) = value.as_f64() else {
        return Ok(());
    };
    let limit = |key: &str| {
        schema
            .get(key)
            .and_then(Value::as_f64)
            .map(|l| (l, number(&schema[key])))
    };
    if let Some((l, text)) = limit("minimum")
        && n < l
    {
        return Err(ConfigError::at(
            path,
            ErrorKind::BelowMinimum { limit: text },
        ));
    }
    if let Some((l, text)) = limit("maximum")
        && n > l
    {
        return Err(ConfigError::at(
            path,
            ErrorKind::AboveMaximum { limit: text },
        ));
    }
    if let Some((l, text)) = limit("exclusiveMinimum")
        && n <= l
    {
        return Err(ConfigError::at(path, ErrorKind::NotAbove { limit: text }));
    }
    if let Some((l, text)) = limit("exclusiveMaximum")
        && n >= l
    {
        return Err(ConfigError::at(path, ErrorKind::NotBelow { limit: text }));
    }
    Ok(())
}

fn alternatives(
    root: &Value,
    schema: &Value,
    value: &Value,
    path: &str,
) -> Result<(), ConfigError> {
    for key in ["anyOf", "oneOf"] {
        let Some(branches) = schema.get(key).and_then(Value::as_array) else {
            continue;
        };
        let mut failures = Vec::new();
        for branch in branches {
            match node(root, branch, value, path) {
                Ok(()) => {
                    failures.clear();
                    break;
                }
                Err(e) => failures.push((branch, e)),
            }
        }
        if failures.is_empty() {
            continue;
        }
        // an enum with documented variants is `oneOf` of constants: say which values are allowed
        let consts: Vec<&Value> = branches
            .iter()
            .filter_map(|b| resolve(root, b).get("const"))
            .collect();
        if consts.len() == branches.len() {
            let allowed = consts
                .iter()
                .map(|c| number(c))
                .collect::<Vec<_>>()
                .join(", ");
            return Err(ConfigError::at(path, ErrorKind::NotInEnum { allowed }));
        }
        // `Option<T>` is `anyOf [T, null]`: when one branch is not null, its error is the useful one.
        let mut real = failures
            .into_iter()
            .filter(|(b, _)| !is_null_branch(root, b));
        return match (real.next(), real.next()) {
            (Some((_, e)), None) => Err(e),
            _ => Err(ConfigError::at(path, ErrorKind::NoMatch)),
        };
    }
    if let Some(all) = schema.get("allOf").and_then(Value::as_array) {
        for branch in all {
            node(root, branch, value, path)?;
        }
    }
    Ok(())
}

fn is_null_branch(root: &Value, branch: &Value) -> bool {
    resolve(root, branch).get("type").and_then(Value::as_str) == Some("null")
}

fn object(
    root: &Value,
    schema: &Value,
    map: &serde_json::Map<String, Value>,
    path: &str,
) -> Result<(), ConfigError> {
    for name in schema
        .get("required")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        if !map.contains_key(name) {
            return Err(ConfigError::at(
                path,
                ErrorKind::MissingRequired {
                    name: name.to_owned(),
                },
            ));
        }
    }
    let properties = schema.get("properties").and_then(Value::as_object);
    let additional = schema.get("additionalProperties");
    for (key, child) in map {
        let here = join_key(path, key);
        if let Some(sub) = properties.and_then(|p| p.get(key)) {
            node(root, sub, child, &here)?;
        } else {
            match additional {
                Some(Value::Bool(false)) => {
                    return Err(ConfigError::at(here, ErrorKind::UnknownSetting));
                }
                Some(sub @ Value::Object(_)) => node(root, sub, child, &here)?,
                _ => {}
            }
        }
    }
    Ok(())
}
