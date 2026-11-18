//! Protocol version of P1. A client and a server that disagree refuse each other (generation-1 D12).

use std::fmt;

/// Version of P1 spoken by this build.
pub const PROTOCOL_VERSION: &str = "1";
/// Header that carries the version on every `/v1/laris/*` request.
pub const PROTOCOL_HEADER: &str = "X-Laris-Protocol";

/// The peer sent a missing or different protocol version (HTTP 426).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionError {
    /// What the peer sent; `None` when the header is missing.
    pub sent: Option<String>,
}

impl fmt::Display for VersionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let shown = match &self.sent {
            None => "missing".to_owned(),
            Some(v) => format!("'{v}'"),
        };
        write!(
            f,
            "unsupported protocol version ({shown}); this server speaks {PROTOCOL_HEADER}: {PROTOCOL_VERSION}. Update the laris client."
        )
    }
}

impl std::error::Error for VersionError {}

/// Accepts exactly [`PROTOCOL_VERSION`]; the message equals the generation-1 server's.
pub fn check_version(sent: Option<&str>) -> Result<(), VersionError> {
    if sent == Some(PROTOCOL_VERSION) {
        Ok(())
    } else {
        Err(VersionError {
            sent: sent.map(str::to_owned),
        })
    }
}
