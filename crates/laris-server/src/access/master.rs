//! The master secret and the key digest (SR-S2).
//!
//! Key digests are keyed: `HMAC-SHA256(lookup key, key text)`, the lookup key derived from the master secret with
//! HKDF-style steps, so a stolen database cannot be used to test guesses without the master secret. The master
//! secret never enters the database.

use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::fmt;

type HmacSha256 = Hmac<Sha256>;

/// Shortest accepted master secret, in characters.
pub const MIN_MASTER_CHARS: usize = 16;

/// A master secret that is too short or unreadable.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct MasterError(pub &'static str);

/// The key that turns a key text into its stored digest.
#[derive(Clone)]
pub struct Master {
    lookup: [u8; 32],
}

impl fmt::Debug for Master {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Master(<redacted>)")
    }
}

fn mac(key: &[u8], parts: &[&[u8]]) -> [u8; 32] {
    // HMAC accepts a key of any length, so `new_from_slice` cannot fail here.
    let mut m = HmacSha256::new_from_slice(key)
        .unwrap_or_else(|_| unreachable!("HMAC takes any key length"));
    for p in parts {
        m.update(p);
    }
    m.finalize().into_bytes().into()
}

impl Master {
    /// Derives the lookup key from the master secret (at least [`MIN_MASTER_CHARS`] characters, surrounding
    /// whitespace ignored).
    pub fn new(secret: &str) -> Result<Self, MasterError> {
        let secret = secret.trim();
        if secret.chars().count() < MIN_MASTER_CHARS {
            return Err(MasterError("the master secret is too short"));
        }
        let prk = mac(b"laris-server-v1", &[secret.as_bytes()]);
        Ok(Self {
            lookup: mac(&prk, &[b"lookup", &[1]]),
        })
    }

    /// The stored digest of a key text, as 64 lowercase hex characters.
    pub fn digest(&self, key: &str) -> String {
        hex(&mac(&self.lookup, &[key.as_bytes()]))
    }
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(char::from(DIGITS[usize::from(b >> 4)]));
        out.push(char::from(DIGITS[usize::from(b & 15)]));
    }
    out
}

/// Equality that does not stop at the first difference.
pub(crate) fn same(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    let mut diff = a.len() ^ b.len();
    for i in 0..a.len().max(b.len()) {
        diff |= usize::from(a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(0));
    }
    diff == 0
}

/// `len` random bytes from the operating system.
pub(crate) fn random_bytes(len: usize) -> Result<Vec<u8>, MasterError> {
    use std::io::Read;
    let mut buf = vec![0u8; len];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut buf))
        .map_err(|_| MasterError("no source of randomness"))?;
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_is_stable() {
        // a recorded value: a change of the derivation would invalidate every stored key
        let m = Master::new("0123456789abcdef0123456789abcdef").unwrap();
        let key = "lk_deadbeef_secretsecretsecretsecretsecret";
        assert_eq!(
            m.digest(key),
            "c7574f3259642fa2f40e30dceeb0fe4a3fde1ed7b2b54a6590a69c3e3821aba7"
        );
    }

    #[test]
    fn another_master_gives_another_digest_and_short_ones_are_refused() {
        let a = Master::new("0123456789abcdef0123456789abcdef").unwrap();
        let b = Master::new("fedcba9876543210fedcba9876543210").unwrap();
        assert_ne!(a.digest("lk_x_y"), b.digest("lk_x_y"));
        assert!(Master::new("short").is_err());
        assert_eq!(format!("{a:?}"), "Master(<redacted>)");
    }

    #[test]
    fn same_compares_whole_values() {
        assert!(same("abc", "abc"));
        assert!(!same("abc", "abd"));
        assert!(!same("abc", "abcd"));
        assert!(!same("", "a"));
    }
}
