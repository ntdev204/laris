//! The real transport: `reqwest` with rustls. Redirects are never followed (the key must not leave the configured
//! server). With a pinned authority the connection trusts that certificate and nothing else.

use crate::error::ClientError;
use crate::pin::Trust;
use crate::transport::{BodyStream, HttpRequest, Method, ResponseHead, Transport, TransportError};
use std::sync::Arc;
use std::time::Duration;

/// How to build the HTTP client.
#[derive(Debug, Clone)]
pub struct HttpOptions {
    /// Longest wait for the TCP and TLS handshake.
    pub connect_timeout: Duration,
    /// Trust anchors.
    pub trust: Trust,
    /// Honour `HTTPS_PROXY` and friends; off for tests that talk to localhost.
    pub use_env_proxy: bool,
}

/// Transport over `reqwest`.
#[derive(Debug, Clone)]
pub struct ReqwestTransport {
    client: reqwest::Client,
}

impl ReqwestTransport {
    /// Builds the client.
    pub fn new(options: &HttpOptions) -> Result<Self, ClientError> {
        let mut builder = reqwest::Client::builder()
            .connect_timeout(options.connect_timeout)
            .redirect(reqwest::redirect::Policy::none());
        if !options.use_env_proxy {
            builder = builder.no_proxy();
        }
        builder = match &options.trust {
            Trust::System => builder.use_rustls_tls(),
            Trust::Pinned { authority_der, .. } => {
                builder.use_preconfigured_tls(pinned_tls(authority_der)?)
            }
        };
        let client = builder
            .build()
            .map_err(|e| ClientError::Config(format!("cannot build the HTTP client: {e}")))?;
        Ok(Self { client })
    }
}

fn pinned_tls(authority_der: &[u8]) -> Result<rustls::ClientConfig, ClientError> {
    let config_error = |e: &dyn std::fmt::Display| {
        ClientError::Config(format!("cannot use the pinned authority: {e}"))
    };
    let mut roots = rustls::RootCertStore::empty();
    roots
        .add(rustls::pki_types::CertificateDer::from(
            authority_der.to_vec(),
        ))
        .map_err(|e| config_error(&e))?;
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    Ok(rustls::ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .map_err(|e| config_error(&e))?
        .with_root_certificates(roots)
        .with_no_client_auth())
}

/// Body of a `reqwest` answer.
#[derive(Debug)]
pub struct ReqwestBody {
    response: reqwest::Response,
}

impl BodyStream for ReqwestBody {
    async fn chunk(&mut self) -> Result<Option<Vec<u8>>, TransportError> {
        self.response
            .chunk()
            .await
            .map(|chunk| chunk.map(|bytes| bytes.to_vec()))
            .map_err(|e| TransportError::Read(e.to_string()))
    }
}

impl Transport for ReqwestTransport {
    type Body = ReqwestBody;

    async fn send(
        &self,
        request: &HttpRequest,
    ) -> Result<(ResponseHead, ReqwestBody), TransportError> {
        let method = match request.method {
            Method::Get => reqwest::Method::GET,
            Method::Post => reqwest::Method::POST,
        };
        let mut builder = self.client.request(method, &request.url);
        for (name, value) in &request.headers {
            builder = builder.header(name, value);
        }
        if let Some(body) = &request.body {
            builder = builder.body(body.clone());
        }
        let response = builder
            .send()
            .await
            .map_err(|e| TransportError::Connect(describe(&e)))?;
        let head = ResponseHead {
            status: response.status().as_u16(),
            headers: response
                .headers()
                .iter()
                .filter_map(|(n, v)| {
                    v.to_str()
                        .ok()
                        .map(|v| (n.as_str().to_owned(), v.to_owned()))
                })
                .collect(),
        };
        Ok((head, ReqwestBody { response }))
    }
}

/// The error and its causes, which reqwest keeps in `source()` (the handshake error is there).
fn describe(error: &reqwest::Error) -> String {
    let mut text = error.to_string();
    let mut source = std::error::Error::source(error);
    while let Some(cause) = source {
        text.push_str(": ");
        text.push_str(&cause.to_string());
        source = cause.source();
    }
    text
}
