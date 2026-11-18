//! Certificate pinning: parsing, matching, and a real TLS handshake against a local server.

mod common;

use common::server;

use common::fixture_tls;
use laris_model_client::{
    ClientConfig, ClientError, HttpOptions, Interrupt, ModelClient, Pin, ReqwestTransport, Trust,
};
use laris_protocol::p1::HelpResponse;
use std::time::Duration;

fn pin_of(der: &[u8]) -> String {
    Pin::fingerprint(der)
}

#[test]
fn the_pin_text_is_strict() {
    let good = "sha256:".to_owned() + &"ab".repeat(32);
    assert_eq!(Pin::parse(&good).unwrap().render(), good);
    assert!(
        Pin::parse(&good.to_uppercase().replace("SHA256", "sha256")).is_ok(),
        "hex digits in either case"
    );
    for bad in [
        "",
        "sha256:",
        "ab".repeat(32).as_str(),
        &format!("sha1:{}", "ab".repeat(20)),
        &format!("sha256:{}", "ab".repeat(31)),
        &format!("sha256:{}", "zz".repeat(32)),
    ] {
        assert!(
            matches!(Pin::parse(bad), Err(ClientError::Config(_))),
            "{bad:?}"
        );
    }
}

#[test]
fn a_matching_authority_is_accepted_and_a_different_one_is_a_pin_mismatch() {
    let ca = fixture_tls("ca.der");
    let other = fixture_tls("other.der");
    let leaf = fixture_tls("leaf.der");
    assert!(Trust::pinned(&pin_of(&ca), ca.clone()).is_ok());
    for wrong in [other, leaf] {
        match Trust::pinned(&pin_of(&ca), wrong.clone()) {
            Err(ClientError::PinMismatch { expected, actual }) => {
                assert_eq!(expected, pin_of(&ca));
                assert_eq!(actual, pin_of(&wrong));
            }
            other => panic!("expected a pin mismatch, got {other:?}"),
        }
    }
    assert!(matches!(
        Trust::pinned("not-a-pin", ca),
        Err(ClientError::Config(_))
    ));
}

fn config(url: String) -> ClientConfig {
    ClientConfig {
        base_url: url,
        api_key: None,
        request_timeout: Duration::from_secs(10),
        idle_timeout: Duration::from_secs(10),
        max_retries: 0,
        backoff_base: Duration::from_millis(10),
        backoff_max: Duration::from_millis(10),
        max_body_bytes: 1 << 20,
    }
}

fn client(port: u16, trust: Trust) -> ModelClient<ReqwestTransport> {
    let transport = ReqwestTransport::new(&HttpOptions {
        connect_timeout: Duration::from_secs(5),
        trust,
        use_env_proxy: false,
    })
    .unwrap();
    ModelClient::new(transport, config(format!("https://localhost:{port}/v1"))).unwrap()
}

/// The handshake failed because of the certificate, not for another reason.
fn is_certificate_refusal(error: &ClientError) -> bool {
    matches!(error, ClientError::Transport(m) if m.contains("UnknownIssuer") || m.to_lowercase().contains("certificate"))
}

fn help_body() -> Vec<u8> {
    common::fixture("help.response.json")
}

#[tokio::test]
async fn a_server_signed_by_the_pinned_authority_is_trusted() {
    let ca = fixture_tls("ca.der");
    let server = server::tls(vec![server::json_response(200, &help_body())]);
    let client = client(server.port, Trust::pinned(&pin_of(&ca), ca).unwrap());
    let help: HelpResponse = client
        .get_json("/laris/help", &Interrupt::new())
        .await
        .unwrap();
    assert!(!format!("{help:?}").is_empty());
    assert_eq!(server.finish().len(), 1);
}

#[tokio::test]
async fn a_server_not_signed_by_the_pinned_authority_is_refused() {
    let other = fixture_tls("other.der");
    let server = server::tls(vec![server::json_response(200, &help_body())]);
    let client = client(server.port, Trust::pinned(&pin_of(&other), other).unwrap());
    let error = client
        .get_json::<HelpResponse>("/laris/help", &Interrupt::new())
        .await
        .unwrap_err();
    assert!(is_certificate_refusal(&error), "{error:?}");
    assert!(server.finish().is_empty(), "no request reached the server");
}

#[tokio::test]
async fn the_system_store_does_not_trust_a_private_authority() {
    let server = server::tls(vec![server::json_response(200, &help_body())]);
    let client = client(server.port, Trust::System);
    let error = client
        .get_json::<HelpResponse>("/laris/help", &Interrupt::new())
        .await
        .unwrap_err();
    assert!(is_certificate_refusal(&error), "{error:?}");
    assert!(server.finish().is_empty());
}
