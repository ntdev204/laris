//! The schema export is deterministic and equals the committed file (T123).

use laris_protocol::schema;
use std::path::Path;

#[test]
fn export_is_deterministic() {
    let first = schema::export_string();
    for _ in 0..3 {
        assert_eq!(first, schema::export_string());
    }
}

#[test]
fn export_names_every_group_and_type() {
    let all = schema::export();
    assert_eq!(all["protocol"], laris_protocol::PROTOCOL_VERSION);
    for (group, name) in [
        ("p1", "ChatRequest"),
        ("p1", "ChatResponseChunk"),
        ("p1", "EmbedRequest"),
        ("p1", "WorkflowsResponse"),
        ("p1", "HelpResponse"),
        ("p1", "AccountResponse"),
        ("p1", "ToolRequest"),
        ("p1", "HttpError"),
        ("p2", "ModelChatRequest"),
        ("p2", "ChatCompletion"),
        ("p2", "ChatCompletionChunk"),
        ("sse", "StreamError"),
    ] {
        assert!(all[group][name].is_object(), "missing {group}/{name}");
    }
}

#[test]
fn committed_schema_is_current() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("schema/laris-protocol.schema.json");
    let committed = std::fs::read_to_string(&path).unwrap_or_default();
    assert!(
        committed == schema::export_string(),
        "{} is stale: run `cargo xtask schema`",
        path.display()
    );
}
