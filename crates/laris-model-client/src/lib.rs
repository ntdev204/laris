//! P1 client (SR-H12): the loop's only way to the server.
//!
//! * [`ModelClient`] holds the logic: `X-Laris-Protocol` on every request and a version check on every answer, the
//!   API key as a bearer token, a timeout for the answer headers and for silence inside a body, bounded retries with
//!   doubling backoff before a stream has started (never after), and an [`Interrupt`] that ends any call at once.
//! * [`ChatStream`] is pull-based: bytes are read only when the consumer asks for the next event.
//! * [`ReqwestTransport`] is the real network (rustls); [`Trust::pinned`] limits a connection to one private
//!   certificate authority whose fingerprint equals the configured pin.
//!
//! Every limit and the address come from the caller's [`ClientConfig`]; the API key comes from there or from the
//! `LARIS_API_KEY` environment variable, and is never printed.

mod client;
mod config;
mod error;
mod http;
mod interrupt;
mod pin;
mod transport;
mod web;

pub use client::{ChatStream, ModelClient};
pub use config::{API_KEY_ENV, ApiKey, ClientConfig};
pub use error::ClientError;
pub use http::{HttpOptions, ReqwestBody, ReqwestTransport};
pub use interrupt::Interrupt;
pub use pin::{Pin, Trust};
pub use transport::{BodyStream, HttpRequest, Method, ResponseHead, Transport, TransportError};
pub use web::{WebClient, WebError, WebOptions, WebPage, check_url, is_public};
