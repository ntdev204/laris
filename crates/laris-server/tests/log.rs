//! Access log records: written once, and with no field that could carry content.

use laris_server::log::{AccessRecord, MemorySink, RequestScope};
use std::sync::Arc;

#[test]
fn record_is_written_once() {
    let sink = Arc::new(MemorySink::default());
    let scope = RequestScope::new(
        "a".into(),
        "GET".into(),
        "127.0.0.1".parse().unwrap(),
        sink.clone(),
    );
    scope.set_route("health");
    scope.finish(200, None);
    scope.finish(499, Some("client_gone"));
    let records = sink.records();
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].status, 200);
    assert_eq!(records[0].route, "health");
}

#[test]
fn json_line_has_only_the_listed_fields() {
    let r = AccessRecord {
        id: "i".into(),
        method: "POST".into(),
        route: "chat",
        status: 200,
        bytes_in: 5,
        duration_ms: 3,
        client: "10.1.2.3".parse().unwrap(),
        outcome: Some("midstream_error"),
    };
    let v: serde_json::Value = serde_json::from_str(&r.to_json_line(1)).unwrap();
    let mut keys: Vec<_> = v.as_object().unwrap().keys().cloned().collect();
    keys.sort();
    assert_eq!(
        keys,
        [
            "bytes_in",
            "client",
            "duration_ms",
            "id",
            "method",
            "outcome",
            "route",
            "status",
            "ts_ms"
        ]
    );
}
