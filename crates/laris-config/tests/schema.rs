//! The JSON Schema: committed copy is current, deterministic, and keeps every generation-1 setting.

mod common;

use laris_config::settings::{Settings, schema, schema_string};
use laris_config::validate::{allowed_types, resolve};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::Path;

fn committed() -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("schema/settings.schema.json");
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

#[test]
fn committed_schema_is_current_and_deterministic() {
    assert_eq!(committed(), schema_string(), "run `cargo xtask schema`");
    assert_eq!(schema_string(), schema_string());
}

#[test]
fn schema_is_strict_and_defaults_validate() {
    let s = schema();
    assert_eq!(s["additionalProperties"], json!(false));
    assert_eq!(
        s["title"],
        json!("LARIS client settings (~/.laris/settings.json)")
    );
    // the default settings are a valid document and the empty document gives the defaults
    let defaults = serde_json::to_value(Settings::default()).expect("serialise");
    assert_eq!(
        Settings::from_value(&defaults).expect("defaults valid"),
        Settings::default()
    );
    assert_eq!(
        Settings::from_value(&json!({})).expect("empty valid"),
        Settings::default()
    );
}

/// Leaf facts of a schema by path: `a.b` for properties, `*` for map values, `[]` for items.
type Facts = BTreeMap<String, Map<String, Value>>;

fn first_branch<'a>(root: &'a Value, schema: &'a Value) -> &'a Value {
    let schema = resolve(root, schema);
    for key in ["anyOf", "oneOf"] {
        if let Some(branches) = schema.get(key).and_then(Value::as_array)
            && let Some(real) = branches
                .iter()
                .find(|b| b.get("type").and_then(Value::as_str) != Some("null"))
            && schema.get("type").is_none()
            && !branches.iter().all(|b| b.get("const").is_some())
        {
            return first_branch(root, real);
        }
    }
    schema
}

fn walk(root: &Value, schema: &Value, path: &str, out: &mut Facts) {
    let node = first_branch(root, schema);
    let mut facts = Map::new();
    for key in [
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "minLength",
        "const",
    ] {
        // a default sits beside a `$ref`, not inside the referenced definition
        if let Some(v) = schema.get(key).or_else(|| node.get(key)) {
            // numbers compare by value: 600 and 600.0 are the same limit
            if key == "default" && v.is_null() {
                continue; // an optional setting is unset either way
            }
            let v = v.as_f64().map_or_else(|| v.clone(), |n| json!(n));
            facts.insert(key.to_owned(), v);
        }
    }
    let types = allowed_types(root, node);
    facts.insert("type".to_owned(), json!(types));
    if let Some(e) = node.get("enum") {
        facts.insert("enum".to_owned(), e.clone());
    }
    let consts: Vec<&Value> = node
        .get("oneOf")
        .and_then(Value::as_array)
        .map(|b| b.iter().filter_map(|x| x.get("const")).collect())
        .unwrap_or_default();
    if !consts.is_empty() {
        facts.insert("enum".to_owned(), json!(consts));
    }
    out.insert(path.to_owned(), facts);
    if let Some(props) = node.get("properties").and_then(Value::as_object) {
        for (k, sub) in props {
            walk(
                root,
                sub,
                &if path.is_empty() {
                    k.clone()
                } else {
                    format!("{path}.{k}")
                },
                out,
            );
        }
    }
    if let Some(sub @ Value::Object(_)) = node.get("additionalProperties") {
        walk(root, sub, &format!("{path}.*"), out);
    }
    if let Some(sub) = node.get("items") {
        walk(root, sub, &format!("{path}[]"), out);
    }
}

fn facts(root: &Value) -> Facts {
    let mut out = Facts::new();
    walk(root, root, "", &mut out);
    out
}

#[test]
fn every_generation_one_setting_is_kept_with_its_type_default_and_limits() {
    let v1_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../src/laris/shared/config/settings.schema.json");
    let v1 = common::json_file(&v1_path);
    let (old, new) = (facts(&v1), facts(&schema()));
    for (path, old_facts) in &old {
        let new_facts = new
            .get(path)
            .unwrap_or_else(|| panic!("setting `{path}` of generation 1 is gone"));
        for (key, value) in old_facts {
            assert_eq!(
                new_facts.get(key),
                Some(value),
                "`{path}`: {key} differs from generation 1"
            );
        }
    }
    let added: Vec<&String> = new.keys().filter(|p| !old.contains_key(*p)).collect();
    assert_eq!(
        added,
        [
            "server.caCertificateFile",
            "server.idleTimeoutSeconds",
            "server.maxResponseBytes",
            "server.maxRetries",
            "server.retryBackoffMaxSeconds",
            "server.retryBackoffSeconds",
            "ui.language",
        ],
        "settings added since generation 1 (server.* from T128)"
    );
}
