//! The catalogue: English and Vietnamese carry the same keys and the same placeholders, and messages fill.

use laris_config::catalogue::placeholders;
use laris_config::{Catalogue, CatalogueError, ErrorKind, Language};

#[test]
fn both_languages_have_the_same_keys() {
    let en: Vec<&str> = Catalogue::keys(Language::En).collect();
    let vi: Vec<&str> = Catalogue::keys(Language::Vi).collect();
    assert!(!en.is_empty());
    assert_eq!(en, vi, "English and Vietnamese must define the same keys");
}

#[test]
fn both_languages_have_the_same_placeholders_and_no_blank_text() {
    let en = Catalogue::new(Language::En);
    let vi = Catalogue::new(Language::Vi);
    for key in Catalogue::keys(Language::En) {
        let (a, b) = (en.template(key).expect("en"), vi.template(key).expect("vi"));
        assert!(
            !a.trim().is_empty() && !b.trim().is_empty(),
            "{key}: blank text"
        );
        assert_eq!(
            placeholders(a),
            placeholders(b),
            "{key}: placeholders differ"
        );
        // every template is well formed: filling it with all its names works
        let names = placeholders(a);
        let args: Vec<(&str, &str)> = names.iter().map(|n| (n.as_str(), "x")).collect();
        assert!(
            en.get(key, &args).is_ok() && vi.get(key, &args).is_ok(),
            "{key}: malformed template"
        );
    }
}

#[test]
fn every_error_kind_has_a_message_with_exactly_its_placeholders() {
    let s = || "x".to_owned();
    let kinds = [
        ErrorKind::UnknownSetting,
        ErrorKind::ExpectedType {
            expected: s(),
            found: s(),
        },
        ErrorKind::NotInEnum { allowed: s() },
        ErrorKind::BelowMinimum { limit: s() },
        ErrorKind::AboveMaximum { limit: s() },
        ErrorKind::NotAbove { limit: s() },
        ErrorKind::NotBelow { limit: s() },
        ErrorKind::TooShort { min: s() },
        ErrorKind::MissingRequired { name: s() },
        ErrorKind::NoMatch,
        ErrorKind::NotAllowed,
        ErrorKind::InvalidJson { detail: s() },
        ErrorKind::NotObject,
        ErrorKind::LiteralSecret,
        ErrorKind::UrlScheme,
        ErrorKind::FingerprintFormat,
        ErrorKind::UnknownHookEvent {
            event: s(),
            known: s(),
        },
        ErrorKind::EnvValue { expected: s() },
        ErrorKind::Unreadable { detail: s() },
        ErrorKind::TooLarge { limit: s() },
        ErrorKind::WriteFailed { detail: s() },
    ];
    for language in Language::ALL {
        let catalogue = Catalogue::new(language);
        for kind in &kinds {
            let template = catalogue
                .template(kind.key())
                .unwrap_or_else(|| panic!("{}: no message", kind.key()));
            let names: Vec<String> = kind.args().iter().map(|(n, _)| (*n).to_owned()).collect();
            assert_eq!(
                placeholders(template).into_iter().collect::<Vec<_>>(),
                {
                    let mut n = names.clone();
                    n.sort();
                    n
                },
                "{}: placeholders",
                kind.key()
            );
        }
    }
    // and every `config.error.*` key is used by some kind
    let used: Vec<&str> = kinds.iter().map(ErrorKind::key).collect();
    for key in Catalogue::keys(Language::En).filter(|k| k.starts_with("config.error.")) {
        assert!(
            used.contains(&key),
            "{key} is not produced by any error kind"
        );
    }
}

#[test]
fn filling_a_message() {
    let c = Catalogue::new(Language::En);
    assert_eq!(
        c.get(
            "config.error.expected_type",
            &[("expected", "integer"), ("found", "string")]
        )
        .as_deref(),
        Ok("expected integer, found string")
    );
    let vi = Catalogue::new(Language::Vi);
    assert_eq!(
        vi.get("config.error.too_short", &[("min", "1")]).as_deref(),
        Ok("phải có ít nhất 1 ký tự")
    );
    // extra values are ignored; missing ones are an error
    assert!(c.get("config.error.no_match", &[("unused", "x")]).is_ok());
    assert_eq!(
        c.get("config.error.too_short", &[]),
        Err(CatalogueError::MissingArg {
            key: "config.error.too_short".to_owned(),
            name: "min".to_owned()
        })
    );
    assert_eq!(
        c.get("no.such.key", &[]),
        Err(CatalogueError::MissingKey("no.such.key".to_owned()))
    );
}

#[test]
fn languages_parse_from_codes_and_locales() {
    for (text, language) in [
        ("en", Language::En),
        ("vi", Language::Vi),
        ("VI", Language::Vi),
        ("vi_VN.UTF-8", Language::Vi),
        ("en-US", Language::En),
    ] {
        assert_eq!(Language::parse(text), Some(language), "{text}");
    }
    for text in ["", "fr", "viet"] {
        assert_eq!(Language::parse(text), None, "{text}");
    }
    assert_eq!(Language::default(), Language::En);
}

#[test]
fn braces_can_be_escaped() {
    assert_eq!(
        placeholders("a {x} {{y}} {z}")
            .into_iter()
            .collect::<Vec<_>>(),
        ["x", "z"]
    );
}
