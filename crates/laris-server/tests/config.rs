//! Server settings from the environment (SR-L1): required bind, defaults, errors that name the variable only.

use laris_server::ServerConfig;
use laris_server::config::ConfigError;
use std::collections::HashMap;
use std::time::Duration;

fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
        .collect()
}

#[test]
fn bind_is_required_and_has_no_default() {
    assert_eq!(
        ServerConfig::from_env(&env(&[])),
        Err(ConfigError::Missing("LARIS_SERVER__BIND"))
    );
    assert_eq!(
        ServerConfig::from_env(&env(&[("LARIS_SERVER__BIND", "  ")])),
        Err(ConfigError::Missing("LARIS_SERVER__BIND"))
    );
}

#[test]
fn defaults_apply_when_only_bind_is_set() {
    let c = ServerConfig::from_env(&env(&[("LARIS_SERVER__BIND", "127.0.0.1:9000")])).unwrap();
    assert_eq!(c.bind.port(), 9000);
    assert_eq!(c, ServerConfig::with_bind(c.bind));
    assert!(!c.trusted_proxies.is_trusted("127.0.0.1".parse().unwrap()));
}

#[test]
fn every_setting_is_read() {
    let c = ServerConfig::from_env(&env(&[
        ("LARIS_SERVER__BIND", "[::1]:8443"),
        ("LARIS_SERVER__MAX_BODY_BYTES", "2048"),
        (
            "LARIS_SERVER__TRUSTED_PROXIES",
            "10.0.0.0/8, 172.16.0.5 ,fd00::/8",
        ),
        ("LARIS_SERVER__HEADER_TIMEOUT_MS", "1500"),
        ("LARIS_SERVER__BODY_TIMEOUT_MS", "2500"),
        ("LARIS_SERVER__STREAM_IDLE_MS", "3500"),
        ("LARIS_SERVER__WRITE_STALL_MS", "4500"),
        ("LARIS_SERVER__MAX_CONNECTIONS", "7"),
        ("LARIS_SERVER__EMBED_MAX_INPUTS", "9"),
        ("LARIS_SERVER__SHUTDOWN_GRACE_MS", "0"),
    ]))
    .unwrap();
    assert_eq!(c.max_body_bytes, 2048);
    assert_eq!(c.header_timeout, Duration::from_millis(1500));
    assert_eq!(c.body_timeout, Duration::from_millis(2500));
    assert_eq!(c.stream_idle, Duration::from_millis(3500));
    assert_eq!(c.write_stall, Duration::from_millis(4500));
    assert_eq!((c.max_connections, c.embed_max_inputs), (7, 9));
    assert_eq!(c.shutdown_grace, Duration::ZERO);
    assert!(c.trusted_proxies.is_trusted("10.9.9.9".parse().unwrap()));
    assert!(c.trusted_proxies.is_trusted("172.16.0.5".parse().unwrap()));
    assert!(!c.trusted_proxies.is_trusted("172.16.0.6".parse().unwrap()));
    assert!(c.trusted_proxies.is_trusted("fd12::1".parse().unwrap()));
}

#[test]
fn errors_name_the_variable_and_not_the_value() {
    let bad = [
        ("LARIS_SERVER__BIND", "SECRETVALUE"),
        ("LARIS_SERVER__MAX_BODY_BYTES", "0"),
        ("LARIS_SERVER__MAX_BODY_BYTES", "SECRETVALUE"),
        ("LARIS_SERVER__HEADER_TIMEOUT_MS", "-5"),
        ("LARIS_SERVER__MAX_CONNECTIONS", "0"),
        ("LARIS_SERVER__WRITE_STALL_MS", "0"),
        ("LARIS_SERVER__TRUSTED_PROXIES", "10.0.0.0/8,SECRETVALUE"),
    ];
    for (name, value) in bad {
        let mut vars = env(&[("LARIS_SERVER__BIND", "127.0.0.1:1")]);
        vars.insert(name.to_owned(), value.to_owned());
        let e = ServerConfig::from_env(&vars).unwrap_err().to_string();
        assert!(e.contains(name), "{e}");
        assert!(!e.contains("SECRETVALUE"), "{e}");
    }
}
