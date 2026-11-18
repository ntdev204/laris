//! Fixture tests of the P1 client against a scripted transport (generation-1 fixtures of `laris-protocol`).

mod common;

use common::*;
use laris_model_client::{ClientError, Interrupt, ModelClient};
use laris_protocol::p1::{ChatRequest, ChatResponseChunk};
use laris_protocol::sse::{P1Event, SseDecoder};
use std::time::Duration;
use tokio::time::Instant;

const CHAT_STEMS: [&str; 7] = [
    "chat_text",
    "chat_tool_call",
    "chat_brain",
    "chat_layers",
    "chat_summarize",
    "chat_workflow",
    "chat_midstream_error",
];

fn request(stem: &str) -> ChatRequest {
    serde_json::from_slice(&fixture(&format!("{stem}.request.json"))).unwrap()
}

/// The events a plain decoder reads from the whole fixture body: the reference.
fn reference_events(stem: &str) -> Vec<P1Event> {
    let mut decoder = SseDecoder::new();
    decoder
        .feed(&fixture(&format!("{stem}.response.sse")))
        .unwrap()
        .iter()
        .map(|data| P1Event::from_data(data).unwrap())
        .collect()
}

async fn collect<B: laris_model_client::BodyStream>(
    stream: &mut laris_model_client::ChatStream<B>,
) -> Result<Vec<P1Event>, ClientError> {
    let mut out = Vec::new();
    while let Some(event) = stream.next().await? {
        out.push(event);
    }
    Ok(out)
}

#[tokio::test(start_paused = true)]
async fn every_chat_fixture_streams_the_same_events_whatever_the_chunking() {
    for stem in CHAT_STEMS {
        let body = fixture(&format!("{stem}.response.sse"));
        let expected = reference_events(stem);
        assert!(
            matches!(expected.last(), Some(P1Event::Done)),
            "{stem} ends with [DONE]"
        );
        for size in [1, 7, 64, body.len()] {
            let script = Script::new(vec![answer(status_of(stem), split(&body, size))]);
            let client = ModelClient::new(script, config(0)).unwrap();
            let mut stream = client
                .chat(&request(stem), &Interrupt::new())
                .await
                .unwrap();
            let events = collect(&mut stream).await.unwrap();
            assert_eq!(events, expected, "{stem}, chunks of {size}");
            assert!(
                stream.next().await.unwrap().is_none(),
                "{stem}: nothing after [DONE]"
            );
        }
    }
}

#[tokio::test(start_paused = true)]
async fn the_midstream_error_arrives_as_an_event_then_done() {
    let body = fixture("chat_midstream_error.response.sse");
    let script = Script::new(vec![answer(200, vec![body])]);
    let client = ModelClient::new(script, config(2)).unwrap();
    let mut stream = client
        .chat(&request("chat_midstream_error"), &Interrupt::new())
        .await
        .unwrap();
    let events = collect(&mut stream).await.unwrap();
    let n = events.len();
    assert!(matches!(events[n - 2], P1Event::Error(_)));
    assert_eq!(events[n - 1], P1Event::Done);
    assert!(
        events[..n - 2]
            .iter()
            .all(|e| matches!(e, P1Event::Chunk(_))),
        "text arrived before the error"
    );
}

#[tokio::test(start_paused = true)]
async fn requests_carry_version_key_and_forced_streaming() {
    let script = Script::new(vec![answer(200, vec![fixture("chat_text.response.sse")])]);
    let client = ModelClient::new(script.clone(), config(0)).unwrap();
    let mut req = request("chat_text");
    req.stream = false;
    client.chat(&req, &Interrupt::new()).await.unwrap();

    let sent = script.requests.lock().unwrap()[0].clone();
    assert_eq!(sent.url, "http://laris.test/v1/laris/chat");
    assert_eq!(sent.header("x-laris-protocol"), Some("1"));
    assert_eq!(sent.header("authorization"), Some("Bearer test-key-123"));
    assert_eq!(sent.header("accept"), Some("text/event-stream"));
    let body: serde_json::Value = serde_json::from_slice(sent.body.as_deref().unwrap()).unwrap();
    assert_eq!(body["stream"], true);
}

#[tokio::test(start_paused = true)]
async fn the_key_never_shows_in_debug_output() {
    let cfg = config(0);
    assert!(!format!("{cfg:?}").contains("test-key-123"));
    assert!(laris_model_client::ApiKey::new("two words").is_err());
    assert!(laris_model_client::ApiKey::new("line\nbreak").is_err());
}

#[tokio::test(start_paused = true)]
async fn a_426_is_a_version_error_and_is_not_retried() {
    let body = fixture("error_protocol_mismatch.response.json");
    let script = Script::new(vec![answer(
        status_of("error_protocol_mismatch"),
        vec![body],
    )]);
    let client = ModelClient::new(script.clone(), config(3)).unwrap();
    let error = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    match error {
        ClientError::Version(message) => assert!(
            message.contains("unsupported protocol version"),
            "{message}"
        ),
        other => panic!("expected a version error, got {other:?}"),
    }
    assert_eq!(script.attempts(), 1);
}

#[tokio::test(start_paused = true)]
async fn an_answer_with_another_protocol_version_is_refused_even_on_200() {
    let step = Step::Answer {
        status: 200,
        headers: vec![("X-Laris-Protocol".to_owned(), "2".to_owned())],
        chunks: vec![fixture("chat_text.response.sse")],
        hang_after: false,
    };
    let client = ModelClient::new(Script::new(vec![step]), config(3)).unwrap();
    let error = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(&error, ClientError::Version(m) if m.contains("'2'")),
        "{error:?}"
    );
}

#[tokio::test(start_paused = true)]
async fn a_matching_protocol_header_is_accepted() {
    let step = Step::Answer {
        status: 200,
        headers: vec![("x-laris-protocol".to_owned(), "1".to_owned())],
        chunks: vec![fixture("chat_text.response.sse")],
        hang_after: false,
    };
    let client = ModelClient::new(Script::new(vec![step]), config(0)).unwrap();
    assert!(
        client
            .chat(&request("chat_text"), &Interrupt::new())
            .await
            .is_ok()
    );
}

#[tokio::test(start_paused = true)]
async fn a_401_is_an_unauthorized_error_and_is_not_retried() {
    let body = fixture("error_unauthorized.response.json");
    let script = Script::new(vec![answer(status_of("error_unauthorized"), vec![body])]);
    let client = ModelClient::new(script.clone(), config(3)).unwrap();
    let error = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(&error, ClientError::Unauthorized(m) if m == "invalid API key"),
        "{error:?}"
    );
    assert_eq!(script.attempts(), 1);
}

#[tokio::test(start_paused = true)]
async fn a_400_is_an_http_error_and_is_not_retried() {
    let body = fixture("error_invalid_request.response.json");
    let script = Script::new(vec![answer(status_of("error_invalid_request"), vec![body])]);
    let client = ModelClient::new(script.clone(), config(3)).unwrap();
    let error = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(error, ClientError::Http { status: 400, .. }),
        "{error:?}"
    );
    assert_eq!(script.attempts(), 1);
}

#[tokio::test(start_paused = true)]
async fn retries_before_the_stream_back_off_and_then_succeed() {
    let refused = fixture("chat_refused_before_stream.response.json");
    let script = Script::new(vec![
        answer(502, vec![refused.clone()]),
        Step::ConnectError("connection refused"),
        answer(502, vec![refused]),
        answer(200, vec![fixture("chat_text.response.sse")]),
    ]);
    let client = ModelClient::new(script.clone(), config(3)).unwrap();
    let started = Instant::now();
    let mut stream = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    // Waits of 1 s, 2 s and 4 s between four attempts.
    assert_eq!(started.elapsed(), Duration::from_secs(7));
    assert_eq!(script.attempts(), 4);
    assert_eq!(
        collect(&mut stream).await.unwrap(),
        reference_events("chat_text")
    );
}

#[tokio::test(start_paused = true)]
async fn retries_are_bounded_and_the_last_error_is_returned() {
    let refused = fixture("chat_refused_before_stream.response.json");
    let script = Script::new(vec![
        answer(502, vec![refused.clone()]),
        answer(502, vec![refused.clone()]),
        answer(502, vec![refused]),
    ]);
    let client = ModelClient::new(script.clone(), config(2)).unwrap();
    let error = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(&error, ClientError::Http { status: 502, message } if message == "model died"),
        "{error:?}"
    );
    assert_eq!(script.attempts(), 3);
}

#[tokio::test(start_paused = true)]
async fn the_backoff_is_capped_and_honours_retry_after() {
    let slow = |after: &str| Step::Answer {
        status: 429,
        headers: vec![("Retry-After".to_owned(), after.to_owned())],
        chunks: vec![b"{\"error\": \"slow down\"}".to_vec()],
        hang_after: false,
    };
    let script = Script::new(vec![
        slow("5"),
        slow("3600"),
        answer(200, vec![fixture("chat_text.response.sse")]),
    ]);
    let client = ModelClient::new(script.clone(), config(5)).unwrap();
    let started = Instant::now();
    client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    // First wait: Retry-After 5 s beats the 1 s backoff. Second: 3600 s is cut to the 8 s cap.
    assert_eq!(started.elapsed(), Duration::from_secs(13));
}

#[tokio::test(start_paused = true)]
async fn no_answer_headers_in_time_is_a_timeout_after_the_retries() {
    let script = Script::new(vec![Step::Hang, Step::Hang]);
    let client = ModelClient::new(script.clone(), config(1)).unwrap();
    let started = Instant::now();
    let error = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap_err();
    assert!(
        matches!(error, ClientError::Timeout(d) if d == Duration::from_secs(10)),
        "{error:?}"
    );
    // 10 s + 1 s backoff + 10 s.
    assert_eq!(started.elapsed(), Duration::from_secs(21));
    assert_eq!(script.attempts(), 2);
}

#[tokio::test(start_paused = true)]
async fn a_stream_that_started_is_never_retried_and_silence_is_an_idle_timeout() {
    let body = fixture("chat_text.response.sse");
    let first = body.split(|b| *b == b'\n').next().unwrap().to_vec();
    let mut chunk = first;
    chunk.extend_from_slice(b"\n\n");
    let script = Script::new(vec![Step::Answer {
        status: 200,
        headers: Vec::new(),
        chunks: vec![chunk],
        hang_after: true,
    }]);
    let client = ModelClient::new(script.clone(), config(3)).unwrap();
    let mut stream = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    assert!(matches!(
        stream.next().await.unwrap(),
        Some(P1Event::Chunk(_))
    ));
    let error = stream.next().await.unwrap_err();
    assert!(
        matches!(error, ClientError::IdleTimeout(d) if d == Duration::from_secs(5)),
        "{error:?}"
    );
    assert_eq!(script.attempts(), 1, "no second request");
    assert!(
        stream.next().await.unwrap().is_none(),
        "the stream is finished"
    );
}

#[tokio::test(start_paused = true)]
async fn a_body_that_ends_before_done_is_truncated() {
    let body = fixture("chat_text.response.sse");
    let cut = String::from_utf8(body).unwrap();
    let cut = cut
        .split("data: [DONE]")
        .next()
        .unwrap()
        .as_bytes()
        .to_vec();
    let client = ModelClient::new(Script::new(vec![answer(200, vec![cut])]), config(0)).unwrap();
    let mut stream = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    let last = loop {
        match stream.next().await {
            Ok(Some(_)) => {}
            other => break other,
        }
    };
    assert!(matches!(last, Err(ClientError::Truncated)), "{last:?}");
}

#[tokio::test(start_paused = true)]
async fn an_interrupt_ends_a_stream_that_is_waiting() {
    let body = fixture("chat_text.response.sse");
    let mut first = body.split(|b| *b == b'\n').next().unwrap().to_vec();
    first.extend_from_slice(b"\n\n");
    let script = Script::new(vec![Step::Answer {
        status: 200,
        headers: Vec::new(),
        chunks: vec![first],
        hang_after: true,
    }]);
    let client = ModelClient::new(script, config(0)).unwrap();
    let interrupt = Interrupt::new();
    let mut stream = client
        .chat(&request("chat_text"), &interrupt)
        .await
        .unwrap();
    assert!(matches!(
        stream.next().await.unwrap(),
        Some(P1Event::Chunk(_))
    ));

    let trigger = interrupt.clone();
    let started = Instant::now();
    let (result, ()) = tokio::join!(stream.next(), async move {
        tokio::time::sleep(Duration::from_secs(2)).await;
        trigger.trigger();
    });
    assert!(
        matches!(result, Err(ClientError::Interrupted)),
        "{result:?}"
    );
    assert_eq!(
        started.elapsed(),
        Duration::from_secs(2),
        "ended at the interrupt, not at the idle timeout"
    );
    assert!(stream.next().await.unwrap().is_none());
}

#[tokio::test(start_paused = true)]
async fn an_interrupt_ends_a_connect_and_a_backoff_wait() {
    // While the answer is awaited.
    let client = ModelClient::new(Script::new(vec![Step::Hang]), config(3)).unwrap();
    let interrupt = Interrupt::new();
    let trigger = interrupt.clone();
    let req = request("chat_text");
    let (result, ()) = tokio::join!(client.chat(&req, &interrupt), async move {
        tokio::time::sleep(Duration::from_secs(1)).await;
        trigger.trigger();
    });
    assert!(matches!(result, Err(ClientError::Interrupted)));

    // While waiting to retry.
    let refused = fixture("chat_refused_before_stream.response.json");
    let script = Script::new(vec![answer(502, vec![refused])]);
    let client = ModelClient::new(script.clone(), config(3)).unwrap();
    let interrupt = Interrupt::new();
    let trigger = interrupt.clone();
    let started = Instant::now();
    let (result, ()) = tokio::join!(client.chat(&req, &interrupt), async move {
        tokio::time::sleep(Duration::from_millis(300)).await;
        trigger.trigger();
    });
    assert!(matches!(result, Err(ClientError::Interrupted)));
    assert_eq!(started.elapsed(), Duration::from_millis(300));
    assert_eq!(
        script.attempts(),
        1,
        "no further attempt after the interrupt"
    );
}

#[tokio::test(start_paused = true)]
async fn an_interrupt_that_was_already_triggered_stops_the_call_before_any_request() {
    let script = Script::new(vec![answer(200, vec![fixture("chat_text.response.sse")])]);
    let client = ModelClient::new(script.clone(), config(0)).unwrap();
    let interrupt = Interrupt::new();
    interrupt.trigger();
    let result = client.chat(&request("chat_text"), &interrupt).await;
    assert!(matches!(result, Err(ClientError::Interrupted)));
    assert_eq!(script.attempts(), 0);
}

#[tokio::test(start_paused = true)]
async fn the_consumer_sets_the_pace() {
    // One event per chunk: reading one event must pull one chunk, not the whole body.
    let text = String::from_utf8(fixture("chat_text.response.sse")).unwrap();
    let chunks: Vec<Vec<u8>> = text
        .split_inclusive("\n\n")
        .map(|part| part.as_bytes().to_vec())
        .collect();
    assert!(chunks.len() >= 4, "the fixture has several events");
    let script = Script::new(vec![answer(200, chunks)]);
    let client = ModelClient::new(script.clone(), config(0)).unwrap();
    let mut stream = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    assert_eq!(
        script.pulled(),
        0,
        "nothing is read before the consumer asks"
    );
    stream.next().await.unwrap();
    assert_eq!(script.pulled(), 1);
    stream.next().await.unwrap();
    assert_eq!(script.pulled(), 2);
}

#[tokio::test(start_paused = true)]
async fn an_event_without_an_end_is_cut_off_at_the_limit() {
    let endless = vec![b'x'; 40 * 1024];
    let script = Script::new(vec![answer(200, vec![endless.clone(), endless])]);
    let client = ModelClient::new(script, config(0)).unwrap();
    let mut stream = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    let error = stream.next().await.unwrap_err();
    assert!(matches!(error, ClientError::Stream(_)), "{error:?}");
}

#[tokio::test(start_paused = true)]
async fn a_malformed_event_is_a_stream_error() {
    let client = ModelClient::new(
        Script::new(vec![answer(200, vec![b"data: {not json\n\n".to_vec()])]),
        config(0),
    )
    .unwrap();
    let mut stream = client
        .chat(&request("chat_text"), &Interrupt::new())
        .await
        .unwrap();
    assert!(matches!(stream.next().await, Err(ClientError::Stream(_))));
}

#[tokio::test(start_paused = true)]
async fn json_routes_decode_their_fixtures() {
    use laris_protocol::p1::{
        AccountResponse, EmbedRequest, EmbedResponse, HelpResponse, ModelList, WorkflowsResponse,
    };
    let interrupt = Interrupt::new();
    let get = |stem: &'static str| {
        Script::new(vec![answer(
            status_of(stem),
            vec![fixture(&format!("{stem}.response.json"))],
        )])
    };

    let client = ModelClient::new(get("account"), config(0)).unwrap();
    client
        .get_json::<AccountResponse>("/laris/account", &interrupt)
        .await
        .unwrap();
    let client = ModelClient::new(get("help"), config(0)).unwrap();
    client
        .get_json::<HelpResponse>("/laris/help", &interrupt)
        .await
        .unwrap();
    let client = ModelClient::new(get("workflows"), config(0)).unwrap();
    client
        .get_json::<WorkflowsResponse>("/laris/workflows", &interrupt)
        .await
        .unwrap();
    let client = ModelClient::new(get("models"), config(0)).unwrap();
    client
        .get_json::<ModelList>("/models", &interrupt)
        .await
        .unwrap();

    let script = get("embed");
    let client = ModelClient::new(script.clone(), config(0)).unwrap();
    let body: EmbedRequest = serde_json::from_slice(&fixture("embed.request.json")).unwrap();
    client
        .post_json::<_, EmbedResponse>("/laris/embed", &body, &interrupt)
        .await
        .unwrap();
    assert_eq!(
        script.requests.lock().unwrap()[0].header("content-type"),
        Some("application/json")
    );
}

#[tokio::test(start_paused = true)]
async fn a_json_answer_of_the_wrong_shape_is_a_decode_error() {
    let script = Script::new(vec![answer(200, vec![b"[1, 2]".to_vec()])]);
    let client = ModelClient::new(script, config(0)).unwrap();
    let error = client
        .get_json::<laris_protocol::p1::HelpResponse>("/laris/help", &Interrupt::new())
        .await
        .unwrap_err();
    assert!(matches!(error, ClientError::Decode(_)), "{error:?}");
}

#[tokio::test(start_paused = true)]
async fn a_bad_configuration_is_refused() {
    let mut cfg = config(0);
    cfg.base_url = "laris.example.com".to_owned();
    assert!(matches!(
        ModelClient::new(Script::default(), cfg),
        Err(ClientError::Config(_))
    ));
    let mut cfg = config(0);
    cfg.idle_timeout = Duration::ZERO;
    assert!(matches!(
        ModelClient::new(Script::default(), cfg),
        Err(ClientError::Config(_))
    ));
}

#[test]
fn the_chat_chunk_type_is_the_one_the_stream_yields() {
    // Compile-time check that the events are the protocol crate's own types.
    fn takes(_: &ChatResponseChunk) {}
    if let P1Event::Chunk(chunk) = &reference_events("chat_text")[0] {
        takes(chunk);
    }
}

#[tokio::test(start_paused = true)]
async fn an_interrupt_stops_the_stream_even_when_events_are_already_waiting() {
    // The whole body arrives in one chunk, so every event is decoded and queued at once.
    let body = fixture("chat_text.response.sse");
    let client = ModelClient::new(Script::new(vec![answer(200, vec![body])]), config(0)).unwrap();
    let interrupt = Interrupt::new();
    let mut stream = client
        .chat(&request("chat_text"), &interrupt)
        .await
        .unwrap();
    assert!(stream.next().await.unwrap().is_some());
    interrupt.trigger();
    assert!(matches!(stream.next().await, Err(ClientError::Interrupted)));
    assert!(stream.next().await.unwrap().is_none());
}
