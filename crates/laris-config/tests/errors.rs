//! Path errors: every kind of problem names the JSON path of the first fault, in both languages.

mod common;

use laris_config::files::reject_literal_secrets;
use laris_config::{Catalogue, ConfigError, ErrorKind, Language, Settings};
use serde_json::{Value, json};

fn error(value: &Value) -> ConfigError {
    Settings::from_value(value).expect_err("must be rejected")
}

#[test]
fn paths_are_named_for_every_kind_of_fault() {
    let cases: Vec<(Value, &str, ErrorKind)> = vec![
        (json!({"bogus": 1}), "bogus", ErrorKind::UnknownSetting),
        (
            json!({"server": {"nope": 1}}),
            "server.nope",
            ErrorKind::UnknownSetting,
        ),
        (
            json!({"permissions": {"defaultMode": "yolo"}}),
            "permissions.defaultMode",
            ErrorKind::NotInEnum {
                allowed: "\"auto\", \"default\", \"acceptEdits\", \"plan\", \"bypass\"".to_owned(),
            },
        ),
        (
            json!({"context": {"windowTokens": "big"}}),
            "context.windowTokens",
            ErrorKind::ExpectedType {
                expected: "integer".to_owned(),
                found: "string".to_owned(),
            },
        ),
        (
            json!({"context": {"windowTokens": 100}}),
            "context.windowTokens",
            ErrorKind::BelowMinimum {
                limit: "1024".to_owned(),
            },
        ),
        (
            json!({"context": {"compactThreshold": 1.5}}),
            "context.compactThreshold",
            ErrorKind::AboveMaximum {
                limit: "1".to_owned(),
            },
        ),
        (
            json!({"context": {"compactThreshold": 0}}),
            "context.compactThreshold",
            ErrorKind::NotAbove {
                limit: "0".to_owned(),
            },
        ),
        (
            json!({"server": {"timeoutSeconds": -1}}),
            "server.timeoutSeconds",
            ErrorKind::NotAbove {
                limit: "0".to_owned(),
            },
        ),
        (
            json!({"hooks": {"PreToolUse": [{"hooks": [{"command": "x", "timeout": 601}]}]}}),
            "hooks.PreToolUse[0].hooks[0].timeout",
            ErrorKind::AboveMaximum {
                limit: "600".to_owned(),
            },
        ),
        (
            json!({"hooks": {"PreToolUse": [{"hooks": [{"timeout": 5}]}]}}),
            "hooks.PreToolUse[0].hooks[0]",
            ErrorKind::MissingRequired {
                name: "command".to_owned(),
            },
        ),
        (
            json!({"hooks": {"Stop": [{"hooks": [{"command": ""}]}]}}),
            "hooks.Stop[0].hooks[0].command",
            ErrorKind::TooShort {
                min: "1".to_owned(),
            },
        ),
        (
            json!({"hooks": {"Sneeze": []}}),
            "hooks.Sneeze",
            ErrorKind::UnknownHookEvent {
                event: "Sneeze".to_owned(),
                known: "SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop".to_owned(),
            },
        ),
        (
            json!({"statusLine": {"command": ""}}),
            "statusLine.command",
            ErrorKind::TooShort {
                min: "1".to_owned(),
            },
        ),
        (
            json!({"statusLine": {"type": "other", "command": "x"}}),
            "statusLine.type",
            ErrorKind::NotInEnum {
                allowed: "\"command\"".to_owned(),
            },
        ),
        (
            json!({"server": {"url": "ftp://x"}}),
            "server.url",
            ErrorKind::UrlScheme,
        ),
        (
            json!({"server": {"caFingerprint": "sha256:XYZ"}}),
            "server.caFingerprint",
            ErrorKind::FingerprintFormat,
        ),
        (
            json!({"env": {"A": 1}}),
            "env.A",
            ErrorKind::ExpectedType {
                expected: "string".to_owned(),
                found: "integer".to_owned(),
            },
        ),
        (
            json!({"permissions": {"allow": ["ok", 7]}}),
            "permissions.allow[1]",
            ErrorKind::ExpectedType {
                expected: "string".to_owned(),
                found: "integer".to_owned(),
            },
        ),
        (
            json!({"cleanupPeriodDays": -1}),
            "cleanupPeriodDays",
            ErrorKind::BelowMinimum {
                limit: "0".to_owned(),
            },
        ),
        (
            json!({"ui": {"language": "fr"}}),
            "ui.language",
            ErrorKind::NotInEnum {
                allowed: "\"en\", \"vi\"".to_owned(),
            },
        ),
    ];
    for (value, path, kind) in cases {
        let err = error(&value);
        assert_eq!(err.path, path, "{value}");
        assert_eq!(err.kind, kind, "{value}");
    }
}

#[test]
fn the_document_itself_has_the_root_path() {
    let err = Settings::from_value(&json!([1])).expect_err("array");
    assert_eq!(err.path, "");
    assert_eq!(err.to_string(), "(root): expected object, found array");
}

#[test]
fn messages_read_in_both_languages() {
    let err = error(&json!({"hooks": {"Stop": [{"hooks": [{"command": "x", "timeout": 601}]}]}}));
    assert_eq!(
        err.render(&Catalogue::new(Language::En)),
        "hooks.Stop[0].hooks[0].timeout: must be at most 600"
    );
    assert_eq!(
        err.render(&Catalogue::new(Language::Vi)),
        "hooks.Stop[0].hooks[0].timeout: phải từ 600 trở xuống"
    );
}

#[test]
fn literal_secrets_are_refused_but_names_and_numbers_are_not() {
    let secret = json!({"server": {"apiKey": "abcdef"}});
    assert_eq!(
        reject_literal_secrets(&secret).expect_err("secret").path,
        "server.apiKey"
    );
    let nested =
        json!({"hooks": {"Stop": [{"hooks": [{"command": "x", "authToken": "t0ps3cret"}]}]}});
    assert_eq!(
        reject_literal_secrets(&nested).expect_err("nested").path,
        "hooks.Stop[0].hooks[0].authToken"
    );
    // a number under a key that mentions tokens is a size, not a credential; empty text is "unset"
    assert!(
        reject_literal_secrets(&json!({"context": {"windowTokens": 4096}, "apiKey": ""})).is_ok()
    );
}
