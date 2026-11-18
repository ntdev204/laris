//! The seam between the client logic and the network. The logic (version check, key, retries, timeouts, stream
//! decoding, interrupt) lives in [`crate::ModelClient`] and is tested against scripted transports; the real one is
//! [`crate::ReqwestTransport`].

use std::future::Future;

/// HTTP method of a P1 route.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    /// `GET`.
    Get,
    /// `POST`.
    Post,
}

/// One request, ready to send.
#[derive(Debug, Clone)]
pub struct HttpRequest {
    /// Method.
    pub method: Method,
    /// Complete URL.
    pub url: String,
    /// Header names and values.
    pub headers: Vec<(String, String)>,
    /// Body bytes, for `POST`.
    pub body: Option<Vec<u8>>,
}

impl HttpRequest {
    /// First header with this name, ignoring case.
    pub fn header(&self, name: &str) -> Option<&str> {
        find_header(&self.headers, name)
    }
}

/// Status and headers of an answer.
#[derive(Debug, Clone)]
pub struct ResponseHead {
    /// Status code.
    pub status: u16,
    /// Header names and values.
    pub headers: Vec<(String, String)>,
}

impl ResponseHead {
    /// First header with this name, ignoring case.
    pub fn header(&self, name: &str) -> Option<&str> {
        find_header(&self.headers, name)
    }
}

fn find_header<'a>(headers: &'a [(String, String)], name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|(n, _)| n.eq_ignore_ascii_case(name))
        .map(|(_, v)| v.as_str())
}

/// A failure below HTTP.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransportError {
    /// The connection or the TLS handshake failed.
    Connect(String),
    /// The connection broke while reading.
    Read(String),
}

impl TransportError {
    pub(crate) fn message(&self) -> &str {
        match self {
            Self::Connect(m) | Self::Read(m) => m,
        }
    }
}

/// The body of an answer, read chunk by chunk. Nothing is read until the caller asks (backpressure), and dropping
/// the body closes the connection.
pub trait BodyStream: Send {
    /// The next bytes, or `None` at the end.
    fn chunk(&mut self) -> impl Future<Output = Result<Option<Vec<u8>>, TransportError>> + Send;
}

/// Sends requests.
pub trait Transport: Send + Sync {
    /// The body type of an answer.
    type Body: BodyStream;

    /// Sends one request and returns once the answer headers are in.
    fn send(
        &self,
        request: &HttpRequest,
    ) -> impl Future<Output = Result<(ResponseHead, Self::Body), TransportError>> + Send;
}
