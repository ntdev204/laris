//! Trusted-proxy rule of SR-S1: the forwarding header is believed only through trusted proxies.

use laris_server::proxy::{Cidr, TrustedProxies};
use std::net::IpAddr;

fn ip(s: &str) -> IpAddr {
    s.parse().unwrap()
}

fn proxies(list: &[&str]) -> TrustedProxies {
    TrustedProxies::new(list.iter().map(|s| Cidr::parse(s).unwrap()).collect())
}

#[test]
fn cidr_parse_and_contains() {
    assert!(
        Cidr::parse("10.0.0.0/8")
            .unwrap()
            .contains(ip("10.255.0.1"))
    );
    assert!(!Cidr::parse("10.0.0.0/8").unwrap().contains(ip("11.0.0.1")));
    assert!(Cidr::parse("192.0.2.7").unwrap().contains(ip("192.0.2.7")));
    assert!(!Cidr::parse("192.0.2.7").unwrap().contains(ip("192.0.2.8")));
    assert!(
        Cidr::parse("0.0.0.0/0")
            .unwrap()
            .contains(ip("203.0.113.9"))
    );
    assert!(Cidr::parse("fd00::/8").unwrap().contains(ip("fd12::1")));
    assert!(!Cidr::parse("fd00::/8").unwrap().contains(ip("fe80::1")));
    assert!(!Cidr::parse("10.0.0.0/8").unwrap().contains(ip("fd00::1")));
    assert!(Cidr::parse("10.0.0.0/33").is_none());
    assert!(Cidr::parse("nonsense").is_none());
    assert!(Cidr::parse("10.0.0.0/x").is_none());
}

#[test]
fn mapped_ipv4_matches_ipv4_block() {
    assert!(
        Cidr::parse("10.0.0.0/8")
            .unwrap()
            .contains(ip("::ffff:10.1.2.3"))
    );
}

#[test]
fn untrusted_peer_ignores_header() {
    let p = proxies(&["10.0.0.0/8"]);
    assert_eq!(
        p.client_ip(ip("198.51.100.4"), ["1.2.3.4"]),
        ip("198.51.100.4")
    );
    assert_eq!(
        TrustedProxies::default().client_ip(ip("10.0.0.1"), ["1.2.3.4"]),
        ip("10.0.0.1")
    );
}

#[test]
fn trusted_peer_reads_chain_from_the_right() {
    let p = proxies(&["10.0.0.0/8"]);
    assert_eq!(
        p.client_ip(ip("10.0.0.1"), ["203.0.113.9"]),
        ip("203.0.113.9")
    );
    // a spoofed leftmost entry is behind the real client
    assert_eq!(
        p.client_ip(ip("10.0.0.1"), ["6.6.6.6, 203.0.113.9, 10.0.0.2"]),
        ip("203.0.113.9")
    );
    // several header lines count as one chain, in order
    assert_eq!(
        p.client_ip(ip("10.0.0.1"), ["6.6.6.6", "203.0.113.9"]),
        ip("203.0.113.9")
    );
}

#[test]
fn trusted_peer_without_header_or_all_trusted() {
    let p = proxies(&["10.0.0.0/8"]);
    assert_eq!(p.client_ip(ip("10.0.0.1"), []), ip("10.0.0.1"));
    assert_eq!(
        p.client_ip(ip("10.0.0.1"), ["10.0.0.7, 10.0.0.8"]),
        ip("10.0.0.7")
    );
}

#[test]
fn garbage_stops_the_walk_at_the_vouched_address() {
    let p = proxies(&["10.0.0.0/8"]);
    assert_eq!(
        p.client_ip(ip("10.0.0.1"), ["1.1.1.1, unknown"]),
        ip("10.0.0.1")
    );
    assert_eq!(
        p.client_ip(ip("10.0.0.1"), ["garbage, 203.0.113.9"]),
        ip("203.0.113.9")
    );
    assert_eq!(p.client_ip(ip("10.0.0.1"), [""]), ip("10.0.0.1"));
}
