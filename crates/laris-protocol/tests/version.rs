//! Version header behaviour (T123): a mismatch gives a clear error with the fixture message.

use laris_protocol::{PROTOCOL_HEADER, PROTOCOL_VERSION, check_version};

#[test]
fn accepts_only_the_current_version() {
    assert!(check_version(Some(PROTOCOL_VERSION)).is_ok());
    assert!(check_version(Some("1")).is_err());
    assert!(check_version(Some("")).is_err());
    assert!(check_version(None).is_err());
}

#[test]
fn message_equals_the_fixture() {
    let fixture = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/p1/error_protocol_mismatch.response.json"
    ))
    .expect("fixture");
    let expected = serde_json::from_str::<serde_json::Value>(&fixture).expect("json")["error"]
        .as_str()
        .expect("string")
        .to_owned();
    assert_eq!(
        check_version(Some("9")).expect_err("mismatch").to_string(),
        expected
    );
    let missing = check_version(None).expect_err("missing").to_string();
    assert!(missing.contains("(missing)") && missing.contains(PROTOCOL_HEADER));
}
