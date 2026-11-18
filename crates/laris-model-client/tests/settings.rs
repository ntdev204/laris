//! The client built from the `server` block of the settings.

mod common;

use common::fixture_tls;
use laris_config::settings::Server;
use laris_model_client::{ClientConfig, ClientError, Pin, Trust};
use std::time::Duration;

fn server() -> Server {
    Server {
        url: "https://laris.example.org/v1".to_owned(),
        ..Server::default()
    }
}

fn write(name: &str, bytes: &[u8]) -> String {
    let dir =
        std::env::temp_dir().join(format!("laris-model-client-{}-{name}", std::process::id()));
    std::fs::write(&dir, bytes).unwrap();
    dir.to_string_lossy().into_owned()
}

fn pem(der: &[u8]) -> Vec<u8> {
    // Minimal PEM writer for the test: base64 of the DER in 64-column lines.
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut b64 = String::new();
    for chunk in der.chunks(3) {
        let n =
            chunk.iter().fold(0u32, |acc, b| (acc << 8) | u32::from(*b)) << (8 * (3 - chunk.len()));
        for i in 0..4 {
            if i <= chunk.len() {
                b64.push(ALPHABET[((n >> (18 - 6 * i)) & 63) as usize] as char);
            } else {
                b64.push('=');
            }
        }
    }
    let mut out = String::from("-----BEGIN CERTIFICATE-----\n");
    for line in b64.as_bytes().chunks(64) {
        out.push_str(std::str::from_utf8(line).unwrap());
        out.push('\n');
    }
    out.push_str("-----END CERTIFICATE-----\n");
    out.into_bytes()
}

#[test]
fn the_defaults_of_the_settings_make_a_valid_client_config() {
    let config = ClientConfig::from_server(&server(), None).unwrap();
    assert_eq!(config.base_url, "https://laris.example.org/v1");
    assert_eq!(config.request_timeout, Duration::from_secs(120));
    assert_eq!(config.idle_timeout, Duration::from_secs(60));
    assert_eq!(config.max_retries, 3);
    assert_eq!(config.backoff_base, Duration::from_secs(1));
    assert_eq!(config.backoff_max, Duration::from_secs(30));
    assert_eq!(config.max_body_bytes, 16 * 1024 * 1024);
}

#[test]
fn settings_values_reach_the_client_config() {
    let mut s = server();
    s.timeout_seconds = 2.5;
    s.max_retries = 0;
    s.retry_backoff_seconds = 0.5;
    s.retry_backoff_max_seconds = 4.0;
    let config = ClientConfig::from_server(&s, None).unwrap();
    assert_eq!(config.request_timeout, Duration::from_millis(2500));
    assert_eq!(config.max_retries, 0);
    assert_eq!(config.backoff_base, Duration::from_millis(500));
    assert_eq!(config.backoff_max, Duration::from_secs(4));
}

#[test]
fn unusable_numbers_are_config_errors() {
    for bad in [f64::NAN, f64::INFINITY, -1.0] {
        let mut s = server();
        s.idle_timeout_seconds = bad;
        assert!(matches!(
            ClientConfig::from_server(&s, None),
            Err(ClientError::Config(m)) if m.contains("idleTimeoutSeconds")
        ));
    }
}

#[test]
fn the_first_wait_may_not_exceed_the_longest_wait() {
    let mut s = server();
    s.retry_backoff_seconds = 10.0;
    s.retry_backoff_max_seconds = 1.0;
    let config = ClientConfig::from_server(&s, None).unwrap();
    let transport_less = laris_model_client::ModelClient::new(common::Script::default(), config);
    assert!(matches!(transport_less, Err(ClientError::Config(_))));
}

#[test]
fn no_pin_means_the_system_store() {
    assert!(matches!(Trust::from_server(&server()), Ok(Trust::System)));
}

#[test]
fn a_pin_needs_the_certificate_file() {
    let mut s = server();
    s.ca_fingerprint = Pin::fingerprint(&fixture_tls("ca.der"));
    assert!(
        matches!(Trust::from_server(&s), Err(ClientError::Config(m)) if m.contains("caCertificateFile"))
    );
    s.ca_certificate_file = "/nonexistent/laris-ca.pem".to_owned();
    assert!(
        matches!(Trust::from_server(&s), Err(ClientError::Config(m)) if m.contains("cannot read"))
    );
}

#[test]
fn a_pinned_authority_loads_from_der_and_from_pem() {
    let ca = fixture_tls("ca.der");
    let mut s = server();
    s.ca_fingerprint = Pin::fingerprint(&ca);
    for (name, bytes) in [("der", ca.clone()), ("pem", pem(&ca))] {
        s.ca_certificate_file = write(name, &bytes);
        assert!(
            matches!(Trust::from_server(&s), Ok(Trust::Pinned { .. })),
            "{name}"
        );
    }
}

#[test]
fn a_certificate_that_does_not_match_the_pin_is_refused() {
    let mut s = server();
    s.ca_fingerprint = Pin::fingerprint(&fixture_tls("ca.der"));
    s.ca_certificate_file = write("other", &pem(&fixture_tls("other.der")));
    assert!(matches!(
        Trust::from_server(&s),
        Err(ClientError::PinMismatch { .. })
    ));
    s.ca_certificate_file = write(
        "garbage",
        b"-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----\n",
    );
    assert!(matches!(
        Trust::from_server(&s),
        Err(ClientError::Config(_))
    ));
}
