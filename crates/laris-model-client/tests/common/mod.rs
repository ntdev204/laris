//! Scripted transport and fixture helpers shared by the tests.

#![allow(dead_code, missing_docs)]

pub mod server;

use laris_model_client::{
    ApiKey, BodyStream, ClientConfig, HttpRequest, ResponseHead, Transport, TransportError,
};
use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

pub fn p1_fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../laris-protocol/tests/fixtures/p1")
}

pub fn fixture(name: &str) -> Vec<u8> {
    let path = p1_fixtures().join(name);
    std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

pub fn status_of(stem: &str) -> u16 {
    String::from_utf8(fixture(&format!("{stem}.status")))
        .unwrap()
        .trim()
        .parse()
        .unwrap()
}

pub fn config(max_retries: u32) -> ClientConfig {
    ClientConfig {
        base_url: "http://laris.test/v1/".to_owned(),
        api_key: Some(ApiKey::new("test-key-123").unwrap()),
        request_timeout: Duration::from_secs(10),
        idle_timeout: Duration::from_secs(5),
        max_retries,
        backoff_base: Duration::from_secs(1),
        backoff_max: Duration::from_secs(8),
        max_body_bytes: 64 * 1024,
    }
}

/// What a scripted attempt does.
pub enum Step {
    /// Answers with this status, headers and body chunks; then the body ends or hangs.
    Answer {
        status: u16,
        headers: Vec<(String, String)>,
        chunks: Vec<Vec<u8>>,
        hang_after: bool,
    },
    /// The connection fails.
    ConnectError(&'static str),
    /// Never answers.
    Hang,
}

pub fn answer(status: u16, chunks: Vec<Vec<u8>>) -> Step {
    Step::Answer {
        status,
        headers: Vec::new(),
        chunks,
        hang_after: false,
    }
}

/// Splits bytes into chunks of `size`.
pub fn split(bytes: &[u8], size: usize) -> Vec<Vec<u8>> {
    bytes.chunks(size).map(<[u8]>::to_vec).collect()
}

#[derive(Clone, Default)]
pub struct Script {
    steps: Arc<Mutex<VecDeque<Step>>>,
    pub requests: Arc<Mutex<Vec<HttpRequest>>>,
    /// Body chunks the consumer has pulled so far.
    pub pulled: Arc<AtomicUsize>,
}

impl Script {
    pub fn new(steps: Vec<Step>) -> Self {
        Self {
            steps: Arc::new(Mutex::new(steps.into())),
            ..Self::default()
        }
    }

    pub fn attempts(&self) -> usize {
        self.requests.lock().unwrap().len()
    }

    pub fn pulled(&self) -> usize {
        self.pulled.load(Ordering::SeqCst)
    }
}

#[derive(Debug)]
pub struct ScriptedBody {
    chunks: VecDeque<Vec<u8>>,
    hang_after: bool,
    pulled: Arc<AtomicUsize>,
}

impl BodyStream for ScriptedBody {
    async fn chunk(&mut self) -> Result<Option<Vec<u8>>, TransportError> {
        match self.chunks.pop_front() {
            Some(bytes) => {
                self.pulled.fetch_add(1, Ordering::SeqCst);
                Ok(Some(bytes))
            }
            None if self.hang_after => std::future::pending().await,
            None => Ok(None),
        }
    }
}

impl Transport for Script {
    type Body = ScriptedBody;

    async fn send(
        &self,
        request: &HttpRequest,
    ) -> Result<(ResponseHead, ScriptedBody), TransportError> {
        self.requests.lock().unwrap().push(request.clone());
        let step = self
            .steps
            .lock()
            .unwrap()
            .pop_front()
            .expect("script ran out of steps");
        match step {
            Step::Hang => std::future::pending().await,
            Step::ConnectError(message) => Err(TransportError::Connect(message.to_owned())),
            Step::Answer {
                status,
                headers,
                chunks,
                hang_after,
            } => Ok((
                ResponseHead { status, headers },
                ScriptedBody {
                    chunks: chunks.into(),
                    hang_after,
                    pulled: self.pulled.clone(),
                },
            )),
        }
    }
}

pub fn fixture_tls(name: &str) -> Vec<u8> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/tls")
        .join(name);
    std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}
