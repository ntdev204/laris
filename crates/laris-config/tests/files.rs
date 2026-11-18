//! The settings file on disk: strict read, atomic validated write, a crash keeps the old file.

mod common;

use common::{fixture, json_file, temp_dir};
use laris_config::files::{get_path, parse_value, read_settings, set_path, write_settings};
use laris_config::packaged::{self, Packaged};
use laris_config::{ErrorKind, LoadOptions, Settings, load};
use serde_json::json;
use std::path::Path;

#[test]
fn a_missing_file_is_no_layer_and_a_present_one_loads() {
    let dir = temp_dir("read");
    let path = dir.join("settings.json");
    assert_eq!(read_settings(&path).expect("missing is fine"), None);
    let packaged = Packaged::default();
    let defaults = load(&LoadOptions {
        settings_path: Some(&path),
        packaged: &packaged,
        env: &[],
    })
    .expect("defaults");
    assert_eq!(defaults, Settings::default());
    std::fs::copy(fixture("full.json"), &path).expect("copy");
    let loaded = load(&LoadOptions {
        settings_path: Some(&path),
        packaged: &packaged,
        env: &[],
    })
    .expect("full");
    assert_eq!(loaded.model, "research-llm");
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn broken_files_are_errors_that_name_the_file() {
    let dir = temp_dir("broken");
    let path = dir.join("settings.json");
    for (text, kind) in [
        ("{not json", "invalid_json"),
        ("[1, 2]", "not_object"),
        (r#"{"server": {"apiKey": "abc123"}}"#, "literal_secret"),
    ] {
        std::fs::write(&path, text).expect("write");
        let err = read_settings(&path).expect_err(text);
        assert_eq!(
            err.source.as_deref(),
            Some(path.display().to_string().as_str()),
            "{text}"
        );
        assert!(err.kind.key().ends_with(kind), "{text}: {:?}", err.kind);
    }
    std::fs::write(&path, vec![b' '; 1_048_577]).expect("write");
    assert!(matches!(
        read_settings(&path).expect_err("large").kind,
        ErrorKind::TooLarge { .. }
    ));
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn write_is_validated_and_atomic() {
    let dir = temp_dir("write");
    let path = dir.join("nested").join("settings.json");
    let good = json!({"model": "m", "context": {"windowTokens": 2048}});
    write_settings(&path, &good).expect("write");
    assert_eq!(json_file(&path), good);
    assert!(
        std::fs::read_to_string(&path)
            .expect("read")
            .ends_with("}\n")
    );
    assert!(
        !path.with_extension("json.tmp").exists(),
        "no temporary file is left"
    );

    // an invalid document writes nothing and keeps the old file
    let before = std::fs::read(&path).expect("read");
    let err = write_settings(&path, &json!({"context": {"windowTokens": 1}})).expect_err("invalid");
    assert_eq!(err.path, "context.windowTokens");
    assert_eq!(std::fs::read(&path).expect("read"), before);
    assert!(
        write_settings(&path, &json!({"env": {"API_KEY": "abcdef"}})).is_err(),
        "secrets are not written"
    );
    assert_eq!(std::fs::read(&path).expect("read"), before);
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn a_crash_between_temp_write_and_rename_keeps_the_old_file() {
    let dir = temp_dir("crash");
    let path = dir.join("settings.json");
    write_settings(&path, &json!({"model": "old"})).expect("write");
    // what a crash leaves behind: a half-written temporary file beside the target
    std::fs::write(path.with_extension("json.tmp"), "{\"model\": \"ne").expect("tmp");
    let packaged = Packaged::default();
    let s = load(&LoadOptions {
        settings_path: Some(&path),
        packaged: &packaged,
        env: &[],
    })
    .expect("old file loads");
    assert_eq!(s.model, "old");
    // and the next write replaces the stale temporary file
    write_settings(&path, &json!({"model": "new"})).expect("write");
    assert_eq!(json_file(&path), json!({"model": "new"}));
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn dotted_paths_read_and_set_with_validation() {
    let data = json!({"context": {"autoCompact": false}});
    assert_eq!(get_path(&data, "context.autoCompact"), Some(&json!(false)));
    assert_eq!(get_path(&data, "context.nope"), None);
    let set = set_path(&data, "context.windowTokens", parse_value("4096")).expect("set");
    assert_eq!(
        set,
        json!({"context": {"autoCompact": false, "windowTokens": 4096}})
    );
    assert_eq!(
        data,
        json!({"context": {"autoCompact": false}}),
        "the original is untouched"
    );
    assert_eq!(
        set_path(&data, "context.windowTokens", parse_value("5"))
            .expect_err("range")
            .path,
        "context.windowTokens"
    );
    assert_eq!(
        set_path(&data, "bogus", json!(1))
            .expect_err("unknown")
            .kind,
        ErrorKind::UnknownSetting
    );
    assert_eq!(parse_value("true"), json!(true));
    assert_eq!(parse_value("[\"a\"]"), json!(["a"]));
    assert_eq!(parse_value("plain words"), json!("plain words"));
}

#[test]
fn packaged_defaults_are_found_beside_the_binary_or_by_name() {
    assert_eq!(
        packaged::locate(
            Some("/etc/laris/defaults.json"),
            Some(Path::new("/opt/laris/laris"))
        ),
        Some("/etc/laris/defaults.json".into())
    );
    assert_eq!(
        packaged::locate(None, Some(Path::new("/opt/laris/laris"))),
        Some("/opt/laris/defaults.json".into())
    );
    assert_eq!(packaged::locate(Some(""), None), None);
    let dir = temp_dir("packaged");
    let file = dir.join("defaults.json");
    std::fs::write(&file, r#"{"server": {"url": "https://p.example.org"}}"#).expect("write");
    assert_eq!(
        Packaged::load(&file).server_url.as_deref(),
        Some("https://p.example.org/v1")
    );
    std::fs::write(&file, vec![b' '; 70_000]).expect("big");
    assert_eq!(
        Packaged::load(&file),
        Packaged::default(),
        "an oversized file counts as empty"
    );
    assert_eq!(
        Packaged::load(&dir.join("absent.json")),
        Packaged::default()
    );
    std::fs::remove_dir_all(dir).ok();
}
