//! The web tools (T255, SR-H17) over a scripted transport: page text, search results, refusals and the clock.
#![allow(missing_docs)]

mod common;

use common::temp_dir;
use laris_config::Settings;
use laris_tools::{Context, Page, Registry, ToolError, WebTransport};
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};

/// A borrowed argument map for `Registry::call` (the test process is short-lived).
fn leak(value: Value) -> &'static serde_json::Map<String, Value> {
    Box::leak(Box::new(value.as_object().expect("an object").clone()))
}

type Reply = Box<dyn Fn(&str) -> Result<Page, ToolError> + Send + Sync>;

struct Script {
    seen: Mutex<Vec<String>>,
    reply: Reply,
}

impl WebTransport for Script {
    fn get(&self, url: &str, _accept: &str) -> Result<Page, ToolError> {
        self.seen.lock().expect("lock").push(url.to_owned());
        (self.reply)(url)
    }
}

fn page(kind: &str, body: &str) -> Result<Page, ToolError> {
    Ok(Page {
        status: 200,
        url: "https://example.org/final".into(),
        content_type: kind.into(),
        body: body.as_bytes().to_vec(),
        truncated: false,
    })
}

fn registry(name: &str, web: Option<Arc<Script>>, change: impl FnOnce(&mut Settings)) -> Registry {
    let base = temp_dir(name);
    let project = base.join("project");
    std::fs::create_dir_all(&project).expect("project");
    let mut settings = Settings::default();
    change(&mut settings);
    let mut ctx = Context::new(&project, &settings).expect("context");
    ctx = ctx.with_redactor(Box::new(|t: &str| t.replace("sk-secret-123", "[redacted]")));
    if let Some(web) = web {
        ctx = ctx.with_web(web);
    }
    Registry::with_local_tools(ctx)
}

fn script(reply: impl Fn(&str) -> Result<Page, ToolError> + Send + Sync + 'static) -> Arc<Script> {
    Arc::new(Script {
        seen: Mutex::new(Vec::new()),
        reply: Box::new(reply),
    })
}

const HTML: &str = r#"<html><head><title>Perovskite &amp; solar</title><style>p{color:red}</style></head>
<body><script>alert(1)</script><h1>Intro</h1><p>Efficiency &gt; 25%&nbsp;now.</p><ul><li>one</li><li>two</li></ul>
<!-- hidden --></body></html>"#;

#[test]
fn a_page_becomes_text_and_is_marked_untrusted() {
    let web = script(|_| page("text/html; charset=utf-8", HTML));
    let mut r = registry("web-fetch", Some(web), |_| {});
    let out = r.call("WebFetch", leak(json!({"url": "https://example.org/a"})));
    assert_eq!(out["title"], "Perovskite & solar");
    let text = out["content"].as_str().expect("content");
    assert!(
        text.contains("Intro") && text.contains("Efficiency > 25% now."),
        "{text}"
    );
    assert!(
        text.contains("one")
            && !text.contains("alert")
            && !text.contains("color:red")
            && !text.contains("hidden")
    );
    assert_eq!(out["untrusted"], true);
}

#[test]
fn fetch_errors_are_typed() {
    let web = script(|url| match url {
        u if u.ends_with("/missing") => Ok(Page {
            status: 404,
            ..page("text/html", "x")?
        }),
        u if u.ends_with("/image") => page("image/png", "\u{1}"),
        _ => Err(ToolError::new("refused_address", "inside")),
    });
    let mut r = registry("web-errors", Some(web.clone()), |_| {});
    let code = |v: &Value| v["error"]["code"].as_str().unwrap_or_default().to_owned();
    assert_eq!(
        code(&r.call("WebFetch", leak(json!({"url": "https://e.org/missing"})))),
        "http_status"
    );
    assert_eq!(
        code(&r.call("WebFetch", leak(json!({"url": "https://e.org/image"})))),
        "unsupported_content"
    );
    assert_eq!(
        code(&r.call("WebFetch", leak(json!({"url": "http://127.0.0.1/"})))),
        "refused_address"
    );
    // a secret never leaves in an address or a query
    let before = web.seen.lock().expect("lock").len();
    assert_eq!(
        code(&r.call(
            "WebFetch",
            leak(json!({"url": "https://e.org/?k=sk-secret-123"}))
        )),
        "secret_in_request"
    );
    assert_eq!(
        code(&r.call("WebSearch", leak(json!({"query": "sk-secret-123"})))),
        "secret_in_request"
    );
    assert_eq!(
        web.seen.lock().expect("lock").len(),
        before,
        "nothing was sent"
    );
}

const RESULTS: &str = r#"<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpaper%3Fid%3D1&amp;rut=abc">Paper <b>one</b></a>
<a class="result__snippet" href="x">A study of <b>perovskites</b>.</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></div>
<div class="result"><a class="result__a" href="https://other.org/two">Two</a><a class="result__snippet">Second.</a></div>"#;

#[test]
fn search_returns_results_and_encodes_the_query() {
    let web = script(|_| page("text/html", RESULTS));
    let mut r = registry("web-search", Some(web.clone()), |_| {});
    let out = r.call(
        "WebSearch",
        leak(json!({"query": "perovskite solar & cells", "max_results": 5})),
    );
    let results = out["results"].as_array().expect("results");
    assert_eq!(results.len(), 2, "{out}");
    assert_eq!(results[0]["title"], "Paper one");
    assert_eq!(results[0]["url"], "https://example.org/paper?id=1");
    assert_eq!(results[0]["snippet"], "A study of perovskites.");
    assert_eq!(results[1]["url"], "https://other.org/two");
    assert_eq!(
        web.seen.lock().expect("lock")[0],
        "https://html.duckduckgo.com/html/?q=perovskite+solar+%26+cells"
    );
}

#[test]
fn a_check_page_is_reported_not_taken_for_no_results() {
    let web = script(|_| {
        page(
            "text/html",
            "<html>Unfortunately, bots use DuckDuckGo too. anomaly detected</html>",
        )
    });
    let mut r = registry("web-blocked", Some(web), |_| {});
    let out = r.call("WebSearch", leak(json!({"query": "x"})));
    assert_eq!(out["error"]["code"], "search_blocked");
}

#[test]
fn the_tools_follow_the_settings_and_the_transport() {
    let names = |r: &Registry| -> Vec<String> {
        r.schemas()
            .iter()
            .map(|s| s.function.name.clone())
            .collect()
    };
    let none = registry("web-none", None, |_| {});
    assert!(names(&none).contains(&"Now".to_owned()));
    assert!(
        !names(&none).contains(&"WebFetch".to_owned()),
        "no transport, no web tools"
    );
    let off = registry("web-off", Some(script(|_| page("text/plain", ""))), |s| {
        s.web.enabled = false
    });
    assert!(!names(&off).contains(&"WebSearch".to_owned()));
    let no_search = registry(
        "web-nosearch",
        Some(script(|_| page("text/plain", ""))),
        |s| s.web.search_url.clear(),
    );
    assert!(names(&no_search).contains(&"WebFetch".to_owned()));
    assert!(!names(&no_search).contains(&"WebSearch".to_owned()));
}

#[test]
fn now_gives_a_plausible_date() {
    let mut r = registry("web-now", None, |_| {});
    let out = r.call("Now", leak(json!({})));
    let utc = out["utc"].as_str().expect("utc");
    assert!(
        utc.starts_with("20") && utc.ends_with('Z') && utc.len() == 20,
        "{utc}"
    );
    assert!(out["unix"].as_u64().unwrap_or(0) > 1_700_000_000);
    assert!(out.get("untrusted").is_none(), "the clock is ours");
}
