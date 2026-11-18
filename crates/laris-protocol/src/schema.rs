//! JSON Schema export of every wire type. The output is deterministic: keys are sorted and nothing
//! depends on time, paths or the environment.

use crate::{p1, p2, sse};
use schemars::schema_for;
use serde_json::{Map, Value, json};

macro_rules! entries {
    ($($group:literal / $name:literal => $ty:ty),* $(,)?) => {
        vec![$(($group, $name, serde_json::to_value(schema_for!($ty)).unwrap_or(Value::Null))),*]
    };
}

/// All schemas: `{"protocol": "1", "p1": {name: schema}, "p2": {...}, "sse": {...}}`.
pub fn export() -> Value {
    let all = entries![
        "p1" / "ChatRequest" => p1::ChatRequest,
        "p1" / "ChatResponseChunk" => p1::ChatResponseChunk,
        "p1" / "EmbedRequest" => p1::EmbedRequest,
        "p1" / "EmbedResponse" => p1::EmbedResponse,
        "p1" / "ModelList" => p1::ModelList,
        "p1" / "WorkflowsResponse" => p1::WorkflowsResponse,
        "p1" / "HelpResponse" => p1::HelpResponse,
        "p1" / "AccountResponse" => p1::AccountResponse,
        "p1" / "AdminUsage" => p1::AdminUsage,
        "p1" / "AdminReasoning" => p1::AdminReasoning,
        "p1" / "ToolRequest" => p1::ToolRequest,
        "p1" / "ToolResponse" => p1::ToolResponse,
        "p1" / "HttpError" => p1::HttpError,
        "p2" / "ModelChatRequest" => p2::ModelChatRequest,
        "p2" / "ChatCompletion" => p2::ChatCompletion,
        "p2" / "ChatCompletionChunk" => p2::ChatCompletionChunk,
        "p2" / "EmbedRequest" => p1::EmbedRequest,
        "p2" / "EmbedResponse" => p1::EmbedResponse,
        "sse" / "StreamError" => sse::StreamError,
    ];
    let mut groups: Map<String, Value> = Map::new();
    for (group, name, schema) in all {
        let entry = groups.entry(group).or_insert_with(|| json!({}));
        if let Some(map) = entry.as_object_mut() {
            map.insert(name.to_owned(), schema);
        }
    }
    let mut root = Map::new();
    root.insert("protocol".to_owned(), json!(crate::PROTOCOL_VERSION));
    root.extend(groups);
    Value::Object(root)
}

/// [`export`] as pretty JSON with a final newline: the content of the committed schema file.
pub fn export_string() -> String {
    let mut text = serde_json::to_string_pretty(&export()).unwrap_or_default();
    text.push('\n');
    text
}
