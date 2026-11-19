//! Helpers shared by the client tests: temporary folders and a small HTTP server that knows one valid key.

#![allow(dead_code, missing_docs)]

use laris_cli::login::{KeyVerifier, VerifyError};
use laris_config::settings::Server;
use laris_model_client::ApiKey;
use laris_protocol::p1::AccountResponse;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

pub fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-cli-t155-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

pub fn env(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
        .collect()
}

/// Answers `GET /v1/laris/account` with the role `user` for one key and 401 for any other.
pub struct KeyServer {
    pub url: String,
    stop: Arc<AtomicBool>,
    seen: Arc<Mutex<Vec<String>>>,
    handle: Option<JoinHandle<()>>,
}

impl KeyServer {
    pub fn start(valid_key: &str) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let stop = Arc::new(AtomicBool::new(false));
        let seen = Arc::new(Mutex::new(Vec::new()));
        let (stop_in, seen_in, valid) = (stop.clone(), seen.clone(), valid_key.to_owned());
        let handle = std::thread::spawn(move || {
            for stream in listener.incoming() {
                if stop_in.load(Ordering::SeqCst) {
                    break;
                }
                if let Ok(stream) = stream {
                    answer(stream, &valid, &seen_in);
                }
            }
        });
        Self {
            url: format!("http://127.0.0.1:{port}/v1"),
            stop,
            seen,
            handle: Some(handle),
        }
    }

    /// The `Authorization` headers the server has seen, in order.
    pub fn authorizations(&self) -> Vec<String> {
        self.seen.lock().unwrap().clone()
    }
}

impl Drop for KeyServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        let port = self
            .url
            .rsplit(':')
            .next()
            .and_then(|p| p.split('/').next());
        if let Some(port) = port.and_then(|p| p.parse::<u16>().ok()) {
            let _ = TcpStream::connect(("127.0.0.1", port));
        }
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

fn answer(mut stream: TcpStream, valid: &str, seen: &Mutex<Vec<String>>) {
    let mut request = Vec::new();
    let mut buf = [0u8; 2048];
    while !request.windows(4).any(|w| w == b"\r\n\r\n") {
        match stream.read(&mut buf) {
            Ok(0) | Err(_) => return,
            Ok(n) => request.extend_from_slice(&buf[..n]),
        }
    }
    let text = String::from_utf8_lossy(&request).into_owned();
    let auth = text
        .lines()
        .find_map(|l| {
            l.to_ascii_lowercase()
                .starts_with("authorization:")
                .then(|| l.split_once(':').map(|(_, v)| v.trim().to_owned()))
                .flatten()
        })
        .unwrap_or_default();
    seen.lock().unwrap().push(auth.clone());
    let ok = text.starts_with("GET /v1/laris/account ") && auth == format!("Bearer {valid}");
    let (status, body) = if ok {
        (200, r#"{"role":"user"}"#)
    } else {
        (401, r#"{"error":"invalid key"}"#)
    };
    let reply = format!(
        "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(reply.as_bytes());
    let _ = stream.flush();
}

/// A verifier that accepts one key and counts its calls.
pub struct Scripted {
    pub accept: &'static str,
    pub unreachable: bool,
    pub calls: AtomicUsize,
}

impl Scripted {
    pub fn accepting(key: &'static str) -> Self {
        Self {
            accept: key,
            unreachable: false,
            calls: AtomicUsize::new(0),
        }
    }
}

impl KeyVerifier for Scripted {
    fn verify(&self, _server: &Server, key: &ApiKey) -> Result<AccountResponse, VerifyError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.unreachable {
            return Err(VerifyError::Other("connection refused".to_owned()));
        }
        if *key == ApiKey::new(self.accept).unwrap() {
            Ok(serde_json::from_str(r#"{"role":"user"}"#).unwrap())
        } else {
            Err(VerifyError::Refused)
        }
    }
}
