//! Client address behind a reverse proxy (SR-S1): `X-Forwarded-For` is believed only when the peer that sent the
//! request is a trusted proxy, and then only up to the first address that is not itself a trusted proxy.

use std::net::IpAddr;

/// An address block: an address and a prefix length.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cidr {
    addr: IpAddr,
    prefix: u8,
}

impl Cidr {
    /// Parses `10.0.0.0/8`, `::1/128` or a bare address (a block of one).
    pub fn parse(text: &str) -> Option<Self> {
        let (addr, prefix) = match text.split_once('/') {
            Some((a, p)) => (a.parse::<IpAddr>().ok()?, Some(p.parse::<u8>().ok()?)),
            None => (text.parse::<IpAddr>().ok()?, None),
        };
        let addr = addr.to_canonical();
        let max = if addr.is_ipv4() { 32 } else { 128 };
        let prefix = prefix.unwrap_or(max);
        (prefix <= max).then_some(Self { addr, prefix })
    }

    /// Whether `ip` is inside the block.
    pub fn contains(&self, ip: IpAddr) -> bool {
        match (self.addr, ip.to_canonical()) {
            (IpAddr::V4(block), IpAddr::V4(ip)) => mask_eq(
                u128::from(u32::from(block)),
                u128::from(u32::from(ip)),
                32,
                self.prefix,
            ),
            (IpAddr::V6(block), IpAddr::V6(ip)) => {
                mask_eq(u128::from(block), u128::from(ip), 128, self.prefix)
            }
            _ => false,
        }
    }
}

fn mask_eq(a: u128, b: u128, width: u8, prefix: u8) -> bool {
    if prefix == 0 {
        return true;
    }
    let shift = u32::from(width - prefix);
    (a >> shift) == (b >> shift)
}

/// The proxies whose forwarding header is believed.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TrustedProxies(Vec<Cidr>);

impl TrustedProxies {
    /// A set of blocks; empty trusts nobody.
    pub fn new(blocks: Vec<Cidr>) -> Self {
        Self(blocks)
    }

    /// Whether `ip` is a trusted proxy.
    pub fn is_trusted(&self, ip: IpAddr) -> bool {
        self.0.iter().any(|c| c.contains(ip))
    }

    /// The address of the client.
    ///
    /// `peer` is the address of the TCP peer; `forwarded` holds the values of every `X-Forwarded-For` header in
    /// order. An untrusted peer is the client and the header is ignored (anyone can send it). From a trusted peer
    /// the chain is read from the right: each address that is itself a trusted proxy is skipped, the first other
    /// one is the client. A value that is not an address ends the walk at the address to its right, the nearest
    /// one a trusted proxy vouched for.
    pub fn client_ip<'a>(
        &self,
        peer: IpAddr,
        forwarded: impl IntoIterator<Item = &'a str>,
    ) -> IpAddr {
        let peer = peer.to_canonical();
        if !self.is_trusted(peer) {
            return peer;
        }
        let hops: Vec<&str> = forwarded
            .into_iter()
            .flat_map(|v| v.split(','))
            .map(str::trim)
            .collect();
        let mut current = peer;
        for hop in hops.into_iter().rev() {
            let Ok(ip) = hop.parse::<IpAddr>() else {
                return current;
            };
            current = ip.to_canonical();
            if !self.is_trusted(current) {
                return current;
            }
        }
        current
    }
}
