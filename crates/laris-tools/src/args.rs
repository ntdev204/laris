//! Checks the arguments of a call against the tool's JSON Schema (the subset tools use) and reads them.

use crate::error::ToolError;
use serde_json::{Map, Value};

/// A JSON Schema object for a tool's parameters: `properties`, `required`, no other property.
pub fn object_schema(properties: Value, required: &[&str]) -> Value {
    serde_json::json!({
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": false,
    })
}

/// Refuses `arguments` that do not fit `schema` with `invalid_arguments`. Checked: required properties,
/// `additionalProperties: false`, `type` (`string`, `integer`, `number`, `boolean`, `array`, `object`), `minimum`,
/// `maximum` and `enum`. Anything else in the schema is not enforced here.
pub fn validate(schema: &Value, arguments: &Map<String, Value>) -> Result<(), ToolError> {
    let bad = |message: String| Err(ToolError::new("invalid_arguments", message));
    let properties = schema.get("properties").and_then(Value::as_object);
    if let Some(required) = schema.get("required").and_then(Value::as_array) {
        for name in required.iter().filter_map(Value::as_str) {
            if !arguments.contains_key(name) {
                return bad(format!("missing argument `{name}`"));
            }
        }
    }
    let closed = schema.get("additionalProperties") == Some(&Value::Bool(false));
    for (name, value) in arguments {
        match properties.and_then(|p| p.get(name)) {
            None if closed => return bad(format!("unknown argument `{name}`")),
            None => {}
            Some(spec) => {
                if let Some(problem) = misfit(spec, value) {
                    return bad(format!("argument `{name}` {problem}"));
                }
            }
        }
    }
    Ok(())
}

fn misfit(spec: &Value, value: &Value) -> Option<String> {
    if let Some(kind) = spec.get("type").and_then(Value::as_str) {
        let fits = match kind {
            "string" => value.is_string(),
            "integer" => value.is_i64() || value.is_u64(),
            "number" => value.is_number(),
            "boolean" => value.is_boolean(),
            "array" => value.is_array(),
            "object" => value.is_object(),
            _ => true,
        };
        if !fits {
            return Some(format!("must be of type {kind}"));
        }
    }
    if let (Some(number), Some(minimum)) =
        (value.as_f64(), spec.get("minimum").and_then(Value::as_f64))
        && number < minimum
    {
        return Some(format!("must be at least {minimum}"));
    }
    if let (Some(number), Some(maximum)) =
        (value.as_f64(), spec.get("maximum").and_then(Value::as_f64))
        && number > maximum
    {
        return Some(format!("must be at most {maximum}"));
    }
    if let Some(options) = spec.get("enum").and_then(Value::as_array)
        && !options.contains(value)
    {
        return Some("is not one of the allowed values".to_owned());
    }
    None
}

/// A string argument the schema already required.
pub fn string<'a>(arguments: &'a Map<String, Value>, name: &str) -> Result<&'a str, ToolError> {
    arguments
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| ToolError::new("invalid_arguments", format!("missing argument `{name}`")))
}

/// An optional string argument.
pub fn opt_string<'a>(arguments: &'a Map<String, Value>, name: &str) -> Option<&'a str> {
    arguments.get(name).and_then(Value::as_str)
}

/// An optional whole-number argument.
pub fn opt_u64(arguments: &Map<String, Value>, name: &str) -> Option<u64> {
    arguments.get(name).and_then(Value::as_u64)
}

/// An optional boolean argument.
pub fn opt_bool(arguments: &Map<String, Value>, name: &str) -> Option<bool> {
    arguments.get(name).and_then(Value::as_bool)
}
