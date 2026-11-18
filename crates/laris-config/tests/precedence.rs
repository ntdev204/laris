//! Precedence (`LARIS_*` environment over settings file over packaged defaults over defaults) and the
//! reading of environment values.

mod common;

use common::{env, fixture, json_file};
use laris_config::layers::resolve_layers;
use laris_config::packaged::Packaged;
use laris_config::settings::{PermissionMode, Settings, Theme};
use laris_config::{ErrorKind, Language, resolve};
use serde_json::json;

const PACKAGED: &str =
    r#"{"server": {"url": "packaged.example.org", "caFingerprint": "sha256:aa"}}"#;

#[test]
fn defaults_when_no_layer() {
    let settings = resolve(&Packaged::default(), None, &[]).expect("defaults");
    assert_eq!(settings, Settings::default());
    assert_eq!(settings.server.url, "");
    assert_eq!(settings.context.window_tokens, 32768);
    assert_eq!(settings.ui.language, Language::En);
}

#[test]
fn packaged_beats_defaults_and_completes_the_address() {
    let packaged =
        Packaged::parse(&PACKAGED.replace("packaged.example.org", "https://packaged.example.org"));
    let settings = resolve(&packaged, None, &[]).expect("packaged");
    assert_eq!(settings.server.url, "https://packaged.example.org/v1");
    // the fingerprint is kept apart: it is never copied into the settings layer
    assert_eq!(settings.server.ca_fingerprint, "");
    assert_eq!(packaged.ca_fingerprint.as_deref(), Some("sha256:aa"));
}

#[test]
fn packaged_needs_a_scheme_and_survives_garbage() {
    assert_eq!(Packaged::parse(PACKAGED), Packaged::default()); // no scheme: not an address
    for bad in [
        "",
        "not json",
        "[]",
        r#"{"server": 3}"#,
        r#"{"server": {"url": 5}}"#,
    ] {
        assert_eq!(Packaged::parse(bad), Packaged::default(), "{bad}");
    }
}

#[test]
fn file_beats_packaged() {
    let packaged = Packaged::parse(r#"{"server": {"url": "https://packaged.example.org"}}"#);
    let file = json!({"server": {"url": "https://mine.example.org/v1"}});
    let settings = resolve(&packaged, Some(("settings.json", file)), &[]).expect("file");
    assert_eq!(settings.server.url, "https://mine.example.org/v1");
}

#[test]
fn environment_beats_file_beats_packaged() {
    let packaged = Packaged::parse(r#"{"server": {"url": "https://packaged.example.org"}}"#);
    let file = json!({"server": {"url": "https://file.example.org/v1", "timeoutSeconds": 10}, "model": "from-file"});
    let vars = env(&[
        ("LARIS_SERVER__URL", "https://env.example.org/v1"),
        ("LARIS_MODEL", "from-env"),
    ]);
    let settings = resolve(&packaged, Some(("settings.json", file)), &vars).expect("all layers");
    assert_eq!(settings.server.url, "https://env.example.org/v1"); // env over file over packaged
    assert_eq!(settings.model, "from-env");
    assert_eq!(settings.server.timeout_seconds, 10.0); // file over default, no env for it
    assert_eq!(settings.context.window_tokens, 32768); // default
}

#[test]
fn merge_is_deep_not_replacing() {
    let file = json!({"context": {"windowTokens": 4096}});
    let vars = env(&[("LARIS_CONTEXT__AUTO_COMPACT", "no")]);
    let settings = resolve(&Packaged::default(), Some(("s.json", file)), &vars).expect("merge");
    assert_eq!(settings.context.window_tokens, 4096);
    assert!(!settings.context.auto_compact);
    assert_eq!(settings.context.compact_threshold, 0.8);
}

#[test]
fn full_fixture_round_trips() {
    let value = json_file(&fixture("full.json"));
    let settings = Settings::from_value(&value).expect("full fixture");
    assert_eq!(settings.server.url, "https://laris.example.org/v1"); // trailing slash trimmed
    assert_eq!(settings.ui.theme, Theme::Dark);
    assert_eq!(settings.ui.language, Language::Vi);
    assert_eq!(
        settings.permissions.default_mode,
        PermissionMode::AcceptEdits
    );
    assert_eq!(settings.hooks["PreToolUse"][0].hooks[0].timeout, 12.0);
    assert_eq!(settings.hooks["Stop"][0].hooks[0].kind, "command");
    assert_eq!(settings.hooks["Stop"][0].hooks[0].timeout, 30.0);
    // serialising and reading back gives the same settings
    let back =
        Settings::from_value(&serde_json::to_value(&settings).expect("to value")).expect("again");
    assert_eq!(back, settings);
}

#[test]
fn environment_names_match_keys_ignoring_case_and_underscores() {
    for name in [
        "LARIS_CONTEXT__WINDOWTOKENS",
        "LARIS_CONTEXT__WINDOW_TOKENS",
        "LARIS_CONTEXT__windowTokens",
    ] {
        let settings = resolve(&Packaged::default(), None, &env(&[(name, "2048")])).expect(name);
        assert_eq!(settings.context.window_tokens, 2048, "{name}");
    }
}

#[test]
fn environment_values_are_read_as_the_type_of_the_setting() {
    let vars = env(&[
        ("LARIS_MODEL", "123"),                         // text stays text
        ("LARIS_EXTRAINSTRUCTIONS", "true"),            // so does a word that looks like a boolean
        ("LARIS_UI__SPINNER", "False"),                 // boolean
        ("LARIS_SERVER__TIMEOUT_SECONDS", "2.5"),       // number
        ("LARIS_CLEANUPPERIODDAYS", "0"),               // integer at the top level
        ("LARIS_PERMISSIONS__ALLOW", r#"["a","b c"]"#), // list as JSON
        ("LARIS_ENV__My_Var", "x"),                     // map key keeps its case
        ("LARIS_UI__THEME", "light"),                   // enum
    ]);
    let s = resolve(&Packaged::default(), None, &vars).expect("typed values");
    assert_eq!(s.model, "123");
    assert_eq!(s.extra_instructions, "true");
    assert!(!s.ui.spinner);
    assert_eq!(s.server.timeout_seconds, 2.5);
    assert_eq!(s.cleanup_period_days, 0);
    assert_eq!(s.permissions.allow, ["a", "b c"]);
    assert_eq!(s.env["My_Var"], "x");
    assert_eq!(s.ui.theme, Theme::Light);
}

#[test]
fn other_laris_variables_are_left_alone() {
    let vars = env(&[
        ("LARIS_API_KEY", "x"),
        ("LARIS_PACKAGED_DEFAULTS", "/somewhere"),
        ("LARIS_SERVER", "{}"), // an object, not a scalar: not set from one variable
        ("OTHER__THING", "y"),
    ]);
    let s = resolve(&Packaged::default(), None, &vars).expect("ignored");
    assert_eq!(s, Settings::default());
}

#[test]
fn bad_environment_values_name_the_variable() {
    let cases: [(&str, &str, &str); 4] = [
        (
            "LARIS_CONTEXT__WINDOW_TOKENS",
            "many",
            "LARIS_CONTEXT__WINDOW_TOKENS",
        ),
        ("LARIS_UI__SPINNER", "maybe", "LARIS_UI__SPINNER"),
        (
            "LARIS_PERMISSIONS__ALLOW",
            "not a list",
            "LARIS_PERMISSIONS__ALLOW",
        ),
        ("LARIS_CONTEXT__NO_SUCH", "1", "LARIS_CONTEXT__NO_SUCH"),
    ];
    for (name, value, var) in cases {
        let err = resolve(&Packaged::default(), None, &env(&[(name, value)])).expect_err(name);
        assert_eq!(err.path, var, "{name}");
    }
    let err = resolve(
        &Packaged::default(),
        None,
        &env(&[("LARIS_CONTEXT__NO_SUCH", "1")]),
    )
    .expect_err("unknown");
    assert_eq!(err.kind, ErrorKind::UnknownSetting);
}

#[test]
fn a_merged_value_out_of_range_names_the_variable_that_set_it() {
    let err = resolve(
        &Packaged::default(),
        None,
        &env(&[("LARIS_CONTEXT__WINDOW_TOKENS", "10")]),
    )
    .expect_err("range");
    assert_eq!(err.path, "context.windowTokens");
    assert_eq!(err.source.as_deref(), Some("LARIS_CONTEXT__WINDOW_TOKENS"));
    assert_eq!(
        err.kind,
        ErrorKind::BelowMinimum {
            limit: "1024".to_owned()
        }
    );
}

#[test]
fn a_bad_file_names_the_file() {
    let file = json!({"context": {"windowTokens": 10}});
    let err = resolve_layers(
        json!(null),
        Some(("/home/u/.laris/settings.json", file)),
        &[],
    )
    .expect_err("file");
    assert_eq!(err.source.as_deref(), Some("/home/u/.laris/settings.json"));
    assert_eq!(
        err.to_string(),
        "/home/u/.laris/settings.json: context.windowTokens: must be at least 1024"
    );
}
