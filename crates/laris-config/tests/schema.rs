//! The JSON Schema: committed copy is current, deterministic and strict.

mod common;

use laris_config::settings::{Settings, schema, schema_string};
use serde_json::json;
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
