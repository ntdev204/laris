//! Reading public web pages for the client's `WebFetch` and `WebSearch` tools (SR-H17).
//!
//! The client has no key and no server here: it fetches whatever address the model names, so it must never reach
//! the user's own machine or network. Every address, the first and each redirect, must be a public one: a literal
//! address is checked before the request, a name is checked when it is resolved (so a name that points inside is
//! refused as well), and redirects are followed by hand so each hop is checked again. No proxy is used.

use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

/// What a page fetch may do.
#[derive(Debug, Clone)]
pub struct WebOptions {
    /// Longest wait for the whole request, redirects included.
    pub timeout: Duration,
    /// Most bytes read from the answer.
    pub max_bytes: usize,
    /// Most redirects followed.
    pub max_redirects: u32,
    /// `User-Agent` sent.
    pub user_agent: String,
}

/// An answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebPage {
    /// HTTP status of the last answer.
    pub status: u16,
    /// The address the body came from, after redirects.
    pub url: String,
    /// `Content-Type` of the body, empty when absent.
    pub content_type: String,
    /// The body, cut at `max_bytes`.
    pub body: Vec<u8>,
    /// Whether the body was cut.
    pub truncated: bool,
}

/// Why a fetch did not give a page. `code` is stable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebError {
    /// Stable code (`bad_url`, `refused_address`, `timeout`, `request_failed`, `too_many_redirects`).
    pub code: &'static str,
    /// What is wrong.
    pub message: String,
}

impl WebError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

/// Whether `ip` is an address on the public internet.
pub fn is_public(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => public_v4(v4),
        IpAddr::V6(v6) => public_v6(v6),
    }
}

fn public_v4(ip: Ipv4Addr) -> bool {
    let [a, b, ..] = ip.octets();
    !(ip.is_loopback()
        || ip.is_private()
        || ip.is_link_local()
        || ip.is_unspecified()
        || ip.is_broadcast()
        || ip.is_multicast()
        || ip.is_documentation()
        || a == 0
        || (a == 100 && (64..128).contains(&b)) // shared address space
        || (a == 198 && (18..20).contains(&b)) // benchmarking
        || a >= 240)
}

fn public_v6(ip: Ipv6Addr) -> bool {
    if let Some(v4) = ip.to_ipv4_mapped() {
        return public_v4(v4);
    }
    let first = ip.segments()[0];
    !(ip.is_loopback()
        || ip.is_unspecified()
        || ip.is_multicast()
        || (first & 0xfe00) == 0xfc00 // unique local
        || (first & 0xffc0) == 0xfe80 // link local
        || (first == 0x2001 && ip.segments()[1] == 0x0db8)) // documentation
}

fn private_name(host: &str) -> bool {
    let host = host.trim_end_matches('.').to_ascii_lowercase();
    host == "localhost"
        || host.ends_with(".localhost")
        || host.ends_with(".local")
        || host.ends_with(".internal")
        || host.ends_with(".lan")
        || !host.contains('.') && host.parse::<IpAddr>().is_err()
}

/// Resolves a name and keeps only public addresses; a name with none is an error.
struct PublicOnly;

impl Resolve for PublicOnly {
    fn resolve(&self, name: Name) -> Resolving {
        Box::pin(async move {
            let found = tokio::net::lookup_host((name.as_str(), 0)).await?;
            let public: Vec<SocketAddr> = found.filter(|a| is_public(a.ip())).collect();
            if public.is_empty() {
                return Err("the name has no public address".into());
            }
            let addrs: Addrs = Box::new(public.into_iter());
            Ok(addrs)
        })
    }
}

/// The client for public pages.
#[derive(Debug, Clone)]
pub struct WebClient {
    client: reqwest::Client,
    options: WebOptions,
}

impl WebClient {
    /// Builds the client.
    pub fn new(options: WebOptions) -> Result<Self, WebError> {
        let client = reqwest::Client::builder()
            .use_rustls_tls()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .dns_resolver(Arc::new(PublicOnly))
            .connect_timeout(options.timeout)
            .user_agent(options.user_agent.clone())
            .build()
            .map_err(|e| {
                WebError::new("request_failed", format!("cannot build the client: {e}"))
            })?;
        Ok(Self { client, options })
    }

    /// `GET url`, following redirects by hand. `accept` is the `Accept` header.
    pub async fn get(&self, url: &str, accept: &str) -> Result<WebPage, WebError> {
        match tokio::time::timeout(self.options.timeout, self.walk(url, accept)).await {
            Ok(result) => result,
            Err(_) => Err(WebError::new("timeout", "the request took too long")),
        }
    }

    async fn walk(&self, start: &str, accept: &str) -> Result<WebPage, WebError> {
        let mut url = check_url(start)?;
        for _ in 0..=self.options.max_redirects {
            let mut response = self
                .client
                .get(url.clone())
                .header(reqwest::header::ACCEPT, accept)
                .send()
                .await
                .map_err(|e| WebError::new("request_failed", describe(&e)))?;
            let status = response.status();
            if status.is_redirection()
                && let Some(next) = response
                    .headers()
                    .get(reqwest::header::LOCATION)
                    .and_then(|v| v.to_str().ok())
            {
                let target = url
                    .join(next)
                    .map_err(|_| WebError::new("bad_url", "a redirect to an unusable address"))?;
                url = check_url(target.as_str())?;
                continue;
            }
            let content_type = response
                .headers()
                .get(reqwest::header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .unwrap_or_default()
                .to_owned();
            let mut body = Vec::new();
            let mut truncated = false;
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|e| WebError::new("request_failed", describe(&e)))?
            {
                let room = self.options.max_bytes - body.len();
                if chunk.len() > room {
                    body.extend_from_slice(&chunk[..room]);
                    truncated = true;
                    break;
                }
                body.extend_from_slice(&chunk);
            }
            return Ok(WebPage {
                status: status.as_u16(),
                url: url.to_string(),
                content_type,
                body,
                truncated,
            });
        }
        Err(WebError::new(
            "too_many_redirects",
            format!("more than {} redirects", self.options.max_redirects),
        ))
    }
}

fn describe(error: &reqwest::Error) -> String {
    let mut text = error.to_string();
    let mut source = std::error::Error::source(error);
    while let Some(inner) = source {
        text.push_str(": ");
        text.push_str(&inner.to_string());
        source = inner.source();
    }
    text
}

/// A usable address: `http` or `https`, no credentials, and not an inside address when it is a literal one.
pub fn check_url(text: &str) -> Result<reqwest::Url, WebError> {
    let url = reqwest::Url::parse(text.trim())
        .map_err(|_| WebError::new("bad_url", "not a valid address"))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(WebError::new(
            "bad_url",
            "only http and https addresses are read",
        ));
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(WebError::new(
            "bad_url",
            "an address with a user name or password is refused",
        ));
    }
    let host = url
        .host_str()
        .ok_or_else(|| WebError::new("bad_url", "the address has no host"))?;
    let literal = host.trim_start_matches('[').trim_end_matches(']');
    match literal.parse::<IpAddr>() {
        Ok(ip) if !is_public(ip) => return Err(inside()),
        Ok(_) => {}
        Err(_) if private_name(host) => return Err(inside()),
        Err(_) => {}
    }
    Ok(url)
}

fn inside() -> WebError {
    WebError::new(
        "refused_address",
        "this address is on the user's own machine or network, and is not read",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inside_addresses_are_refused_and_public_ones_pass() {
        for bad in [
            "http://127.0.0.1/",
            "http://localhost:8080/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/",
            "http://[fd00::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://printer.local/",
            "http://intranet/",
            "http://100.64.0.1/",
            "http://0.0.0.0/",
            "file:///etc/passwd",
            "ftp://example.com/",
            "http://user:pw@example.com/",
        ] {
            assert!(check_url(bad).is_err(), "{bad} must be refused");
        }
        for good in [
            "https://example.com/a?b=1",
            "http://93.184.216.34/",
            "https://[2606:4700::1111]/",
        ] {
            assert!(check_url(good).is_ok(), "{good} must pass");
        }
    }
}
