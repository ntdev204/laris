//! Certificate pinning for a server with a private certificate authority.
//!
//! The pin is the SHA-256 of the authority's DER certificate (`sha256:<hex>`, as `server.caFingerprint`). The
//! authority certificate itself is supplied by the caller; this module checks that it matches the pin and makes it the
//! only trust anchor of the connection. A certificate that does not match is refused before any connection exists.

use crate::error::ClientError;
use sha2::{Digest, Sha256};

/// A parsed `sha256:<hex>` pin.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pin([u8; 32]);

impl Pin {
    /// Parses `sha256:` followed by 64 hexadecimal digits (either case).
    pub fn parse(text: &str) -> Result<Self, ClientError> {
        let bad = || {
            ClientError::Config(
                "the pin must be sha256: followed by 64 hexadecimal digits".to_owned(),
            )
        };
        let hex = text.trim().strip_prefix("sha256:").ok_or_else(bad)?;
        if hex.len() != 64 || !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(bad());
        }
        let mut out = [0u8; 32];
        for (slot, pair) in out.iter_mut().zip(hex.as_bytes().chunks(2)) {
            let digits = std::str::from_utf8(pair).map_err(|_| bad())?;
            *slot = u8::from_str_radix(digits, 16).map_err(|_| bad())?;
        }
        Ok(Self(out))
    }

    /// `sha256:<lowercase hex>`.
    pub fn render(&self) -> String {
        render(&self.0)
    }

    /// Whether this DER certificate has the pinned fingerprint.
    pub fn matches(&self, der: &[u8]) -> bool {
        Sha256::digest(der).as_slice() == self.0
    }

    /// The fingerprint of a DER certificate, in pin form.
    pub fn fingerprint(der: &[u8]) -> String {
        render(Sha256::digest(der).as_slice())
    }
}

fn render(bytes: &[u8]) -> String {
    let mut out = String::from("sha256:");
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

/// Trust anchors for one connection.
#[derive(Debug, Clone)]
pub enum Trust {
    /// The operating system's certificate store (a server with a public certificate).
    System,
    /// Only this authority, after its fingerprint has been checked against the pin.
    Pinned {
        /// The configured pin.
        pin: Pin,
        /// The authority certificate, DER.
        authority_der: Vec<u8>,
    },
}

impl Trust {
    /// A pinned trust; fails with [`ClientError::PinMismatch`] when the certificate does not have the pin.
    pub fn pinned(pin: &str, authority_der: Vec<u8>) -> Result<Self, ClientError> {
        let pin = Pin::parse(pin)?;
        if !pin.matches(&authority_der) {
            return Err(ClientError::PinMismatch {
                expected: pin.render(),
                actual: Pin::fingerprint(&authority_der),
            });
        }
        Ok(Self::Pinned { pin, authority_der })
    }
}
