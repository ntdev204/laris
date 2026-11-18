//! The real transport over a plain local socket: what goes on the wire, a chunked SSE stream, refusals, redirects.

mod common;

use common::server;

use common::*;
use laris_model_client::{
    ApiKey, ClientConfig, ClientError, HttpOptions, Interrupt, ModelClient, ReqwestTransport, Trust,
};
use laris_protocol::p1::ChatRequest;
use laris_protocol::sse::{P1Event, SseDecoder};
use std::time::Duration;

fn client(port: u16) -> ModelClient<ReqwestTransport> {
    let transport = ReqwestTransport::new(&HttpOptions {
        connect_timeout: Duration::from_secs(5),
        trust: Trust::System,
        use_env_proxy: false,
    })
    .unwrap();
    let config = ClientConfig {
        base_url: format!("http://127.0.0.1:{port}/v1"),
        api_key: Some(ApiKey::new("wire-key-456").unwrap()),
        request_timeout: Duration::from_secs(10),
        idle_timeout: Duration::from_secs(10),
        max_retries: 0,
        backoff_base: Duration::from_millis(10),
        backoff_max: Duration::from_millis(10),
        max_body_bytes: 1 << 20,
    };
    ModelClient::new(transport, config).unwrap()
}

fn request(stem: &str) -> ChatRequest {
    serde_json::from_slice(&fixture(&format!("{stem}.request.json"))).unwrap()
}

#[tokio::test]
async fn a_chunked_chat_stream_arrives_event_by_event() {
    let body = fixture("chat_tool_call.response.sse");
    let mut expected = Vec::new();
    for data in SseDecoder::new().feed(&body).unwrap() {
        expected.push(P1Event::from_data(&data).unwrap());
    }
    // Cut mid-event so the HTTP chunks do not line up with the SSE events.
    let server = server::plain(vec![server::sse_response(&split(&body, 37))]);
    let client = client(server.port);
    let mut stream = client
        .chat(&request("chat_tool_call"), &Interrupt::new())
        .await
        .unwrap();
    let mut events = Vec::new();
    while let Some(event) = stream.next().await.unwrap() {
        events.push(event);
    }
    assert_eq!(events, expected);

    let requests = server.finish();
    let sent = String::from_utf8(requests[0].clone()).unwrap();
    let lower = sent.to_lowercase();
    assert!(sent.starts_with("POST /v1/laris/chat HTTP/1.1"), "{sent}");
    assert!(lower.contains("x-laris-protocol: 1"));
    assert!(lower.contains("authorization: bearer wire-key-456"));
    assert!(lower.contains("accept: text/event-stream"));
    assert!(lower.contains("content-type: application/json"));
    let json = sent.split("\r\n\r\n").nth(1).unwrap();
    let body: serde_json::Value = serde_json::from_str(json).unwrap();
    assert_eq!(body["stream"], true);
}

#[tokio::test]
async fn a_426_over_the_wire_is_a_version_error() {
    let body = fixture("error_protocol_mismatch.response.json");
    let server = server::plain(vec![server::json_response(426, &body)]);
    let error = client(server.port)
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(&error, ClientError::Version(m) if m.contains("unsupported protocol version")),
        "{error:?}"
    );
    server.finish();
}

#[tokio::test]
async fn a_redirect_is_an_error_and_the_key_is_not_sent_on() {
    let target = server::plain(vec![server::json_response(200, b"{}")]);
    let redirect = format!(
        "HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{}/v1/laris/chat\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        target.port
    );
    let server = server::plain(vec![redirect.into_bytes()]);
    let error = client(server.port)
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(error, ClientError::Http { status: 302, .. }),
        "{error:?}"
    );
    server.finish();
    // Nobody connected to the redirect target: `finish` connects once to wake the thread, which sends no request.
    assert!(target.finish().is_empty());
}

#[tokio::test]
async fn a_server_that_is_not_there_is_a_transport_error() {
    let port = {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        listener.local_addr().unwrap().port()
    };
    let error = client(port)
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(matches!(error, ClientError::Transport(_)), "{error:?}");
}
