//! A tiny one-thread HTTP and HTTPS server for the wire tests. It answers each connection with a prepared response and
//! keeps the request it read.

#![allow(dead_code, missing_docs)]

use super::fixture_tls;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Arc;
use std::thread::JoinHandle;

pub struct Server {
    pub port: u16,
    handle: JoinHandle<Vec<Vec<u8>>>,
}

impl Server {
    /// Stops the server and returns the requests it read, one per answered connection.
    pub fn finish(self) -> Vec<Vec<u8>> {
        // The thread stops after its prepared responses; connect once more so a thread still in `accept` wakes.
        let _ = TcpStream::connect(("127.0.0.1", self.port));
        self.handle.join().expect("server thread")
    }
}

pub fn json_response(status: u16, body: &[u8]) -> Vec<u8> {
    let mut out = format!(
        "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .into_bytes();
    out.extend_from_slice(body);
    out
}

/// A chunked `text/event-stream` answer with one HTTP chunk per piece.
pub fn sse_response(pieces: &[Vec<u8>]) -> Vec<u8> {
    let mut out = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        .to_vec();
    for piece in pieces {
        out.extend_from_slice(format!("{:x}\r\n", piece.len()).as_bytes());
        out.extend_from_slice(piece);
        out.extend_from_slice(b"\r\n");
    }
    out.extend_from_slice(b"0\r\n\r\n");
    out
}

pub fn plain(responses: Vec<Vec<u8>>) -> Server {
    spawn(responses, None)
}

pub fn tls(responses: Vec<Vec<u8>>) -> Server {
    let chain = vec![CertificateDer::from(fixture_tls("leaf.der"))];
    let key = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(fixture_tls("leaf.key.der")));
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let config = rustls::ServerConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_no_client_auth()
        .with_single_cert(chain, key)
        .unwrap();
    spawn(responses, Some(Arc::new(config)))
}

fn spawn(responses: Vec<Vec<u8>>, tls: Option<Arc<rustls::ServerConfig>>) -> Server {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let handle = std::thread::spawn(move || {
        let mut requests = Vec::new();
        for response in responses {
            let Ok((tcp, _)) = listener.accept() else {
                break;
            };
            let served = match &tls {
                None => serve(tcp, &response),
                Some(config) => match rustls::ServerConnection::new(config.clone()) {
                    Ok(conn) => serve(rustls::StreamOwned::new(conn, tcp), &response),
                    Err(_) => None,
                },
            };
            match served {
                Some(request) => requests.push(request),
                None => {
                    // A failed handshake or a connection the client dropped: nothing was served; wait for the next.
                    continue;
                }
            }
        }
        requests
    });
    Server { port, handle }
}

/// Reads one request (headers and `Content-Length` body), writes `response`, returns the request.
fn serve<S: Read + Write>(mut stream: S, response: &[u8]) -> Option<Vec<u8>> {
    let mut request = Vec::new();
    let mut buf = [0u8; 4096];
    loop {
        let n = stream.read(&mut buf).ok()?;
        if n == 0 {
            return None;
        }
        request.extend_from_slice(&buf[..n]);
        if let Some(end) = request.windows(4).position(|w| w == b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&request[..end]).to_lowercase();
            let wanted = head
                .lines()
                .find_map(|l| l.strip_prefix("content-length:"))
                .and_then(|v| v.trim().parse::<usize>().ok())
                .unwrap_or(0);
            if request.len() >= end + 4 + wanted {
                break;
            }
        }
    }
    stream.write_all(response).ok()?;
    stream.flush().ok()?;
    Some(request)
}
