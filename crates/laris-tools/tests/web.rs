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
fn a_check_page_is_reported_when_no_other_source_is_set() {
    let web = script(|_| {
        page(
            "text/html",
            "<html>Unfortunately, bots use DuckDuckGo too. anomaly detected</html>",
        )
    });
    let mut r = registry("web-blocked", Some(web), |s| {
        s.web.fallback_search_url.clear();
        s.web.paper_search_url.clear();
    });
    let out = r.call("WebSearch", leak(json!({"query": "x"})));
    assert_eq!(out["error"]["code"], "search_blocked");
}

#[test]
fn a_blocked_search_page_falls_back_to_the_encyclopedia_and_the_paper_index() {
    let web = script(|url| {
        if url.contains("duckduckgo") {
            page("text/html", "<html>anomaly detected</html>")
        } else if url.contains("wikipedia.org/w/api.php") {
            page(
                "application/json",
                r#"{"query":{"search":[{"title":"Model predictive control","snippet":"<span class=\"searchmatch\">MPC</span> is a method"}]}}"#,
            )
        } else if url.contains("openalex") {
            page(
                "application/json",
                r#"{"meta":{"count":1},"results":[{"id":"https://openalex.org/W1","doi":"https://doi.org/10.1/x","title":"Tiny MPC","publication_year":2024,"locations":[{"pdf_url":"https://arxiv.org/pdf/1"}]}]}"#,
            )
        } else {
            page("text/plain", "")
        }
    });
    let mut r = registry("web-fallback", Some(web.clone()), |_| {});
    let out = r.call(
        "WebSearch",
        leak(json!({"query": "model predictive control"})),
    );
    assert!(out.get("error").is_none(), "{out}");
    let results = out["results"].as_array().expect("results");
    assert_eq!(
        results[0]["url"],
        "https://en.wikipedia.org/wiki/Model_predictive_control"
    );
    assert_eq!(results[0]["snippet"], "MPC is a method");
    assert_eq!(results[1]["title"], "Tiny MPC (2024)");
    assert_eq!(results[1]["url"], "https://arxiv.org/pdf/1");
    assert_eq!(out["sources"], json!(["encyclopedia", "papers"]));
    // a Vietnamese query asks the Vietnamese encyclopedia
    let _ = r.call("WebSearch", leak(json!({"query": "điều khiển dự báo"})));
    assert!(
        web.seen
            .lock()
            .expect("lock")
            .iter()
            .any(|u| u.starts_with("https://vi.wikipedia.org/w/api.php"))
    );
}

#[test]
fn a_refused_paper_page_gives_the_record_from_the_index() {
    let web = script(|url| {
        if url.contains("openalex") {
            assert!(url.ends_with("/doi:10.3390/electronics14142775"), "{url}");
            page(
                "application/json",
                r#"{"id":"https://openalex.org/W2","title":"Tracking control on microcontrollers","publication_year":2025,
                   "authorships":[{"author":{"display_name":"A. Lee"}}],
                   "abstract_inverted_index":{"NMPC":[0],"runs":[1],"fast":[2]},
                   "locations":[{"pdf_url":"https://www.mdpi.com/x.pdf"}]}"#,
            )
        } else {
            Ok(Page {
                status: 403,
                url: url.to_owned(),
                content_type: "text/html".into(),
                body: b"Access Denied".to_vec(),
                truncated: false,
            })
        }
    });
    let mut r = registry("web-record", Some(web), |_| {});
    let out = r.call(
        "WebFetch",
        leak(json!({"url": "https://doi.org/10.3390/electronics14142775"})),
    );
    assert!(out.get("error").is_none(), "{out}");
    assert_eq!(out["read_by"], "paper_index");
    let content = out["content"].as_str().expect("content");
    assert!(content.contains("Tracking control on microcontrollers (2025)"));
    assert!(content.contains("Abstract: NMPC runs fast"));
    assert!(content.contains("https://www.mdpi.com/x.pdf"));
    // an address that names no paper is still a refusal
    let out = r.call("WebFetch", leak(json!({"url": "https://example.org/page"})));
    assert_eq!(out["error"]["code"], "http_status");
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
        |s| {
            s.web.search_url.clear();
            s.web.fallback_search_url.clear();
        },
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

#[test]
fn a_pdf_is_read_not_refused_and_a_scan_goes_to_ocr() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/ingest");
    let text_pdf = std::fs::read(dir.join("report.pdf")).expect("fixture");
    let scan_pdf = std::fs::read(dir.join("scanned_text.pdf")).expect("fixture");
    let web = script(move |url| {
        let body = if url.ends_with("/scan") {
            &scan_pdf
        } else {
            &text_pdf
        };
        Ok(Page {
            body: body.clone(),
            ..page("application/pdf", "")?
        })
    });
    let mut r = registry("web-pdf", Some(web), |_| {});
    let out = r.call("WebFetch", leak(json!({"url": "https://e.org/paper.pdf"})));
    assert_eq!(out["read_by"], "text_layer", "{out}");
    assert!(
        out["content"]
            .as_str()
            .expect("content")
            .contains("Perovskite solar cells"),
        "{out}"
    );
    let has = |p: &str| std::process::Command::new(p).arg("-v").output().is_ok();
    if has("pdftoppm") && has("tesseract") {
        let out = r.call("WebFetch", leak(json!({"url": "https://e.org/scan"})));
        assert_eq!(out["read_by"], "ocr", "{out}");
        assert!(
            out["content"]
                .as_str()
                .expect("content")
                .contains("perovskite")
        );
    }
}

const WORKS: &str = r#"{"meta": {"count": 2}, "results": [
 {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "title": "Embedded  NMPC",
  "publication_year": 2024,
  "authorships": [{"author": {"display_name": "A. One"}}, {"author": {"display_name": "B. Two"}},
                  {"author": {"display_name": "C. Three"}}, {"author": {"display_name": "D. Four"}},
                  {"author": {"display_name": "E. Five"}}],
  "abstract_inverted_index": {"control": [1], "We": [0], "drones.": [2]},
  "best_oa_location": {"pdf_url": "https://publisher.org/1.pdf"},
  "locations": [{"pdf_url": null}, {"pdf_url": "https://publisher.org/1.pdf"}, {"pdf_url": "https://arxiv.org/pdf/1"}],
  "primary_location": {"landing_page_url": "https://arxiv.org/abs/1"}},
 {"id": "https://openalex.org/W2", "doi": null, "title": "No text", "publication_year": 2020,
  "authorships": [], "abstract_inverted_index": null, "best_oa_location": null,
  "open_access": {"oa_url": "https://e.org/paper"}, "primary_location": null}]}"#;

#[test]
fn paper_search_returns_papers_with_abstract_and_free_text() {
    let web = script(|_| page("application/json", WORKS));
    let mut r = registry("paper-search", Some(web.clone()), |_| {});
    let out = r.call(
        "PaperSearch",
        leak(json!({"query": "nmpc & mcu", "max_results": 2, "from_year": 2020})),
    );
    let papers = out["results"].as_array().expect("results");
    assert_eq!(papers.len(), 2, "{out}");
    assert_eq!(papers[0]["title"], "Embedded NMPC");
    assert_eq!(papers[0]["authors"], "A. One, B. Two, C. Three et al.");
    assert_eq!(papers[0]["abstract"], "We control drones.");
    assert_eq!(papers[0]["pdf_url"], "https://arxiv.org/pdf/1");
    assert_eq!(
        papers[0]["other_pdf_urls"],
        json!(["https://publisher.org/1.pdf"])
    );
    assert_eq!(papers[0]["url"], "https://arxiv.org/abs/1");
    assert_eq!(papers[1]["pdf_url"], "https://e.org/paper");
    assert_eq!(papers[1]["url"], "https://openalex.org/W2");
    assert_eq!(out["total"], 2);
    let sent = web.seen.lock().expect("lock")[0].clone();
    assert!(
        sent.starts_with("https://api.openalex.org/works?search=nmpc+%26+mcu&per-page=2&"),
        "{sent}"
    );
    assert!(
        sent.ends_with("&filter=is_oa:true,from_publication_date:2020-01-01"),
        "{sent}"
    );
    // a secret never leaves; a page that is not JSON is a failed search; an empty address removes the tool
    assert_eq!(
        r.call("PaperSearch", leak(json!({"query": "sk-secret-123"})))["error"]["code"],
        "secret_in_request"
    );
    let mut bad = registry(
        "paper-bad",
        Some(script(|_| page("text/html", "<html>"))),
        |_| {},
    );
    assert_eq!(
        bad.call("PaperSearch", leak(json!({"query": "x"})))["error"]["code"],
        "search_failed"
    );
    let off = registry("paper-off", Some(script(|_| page("text/plain", ""))), |s| {
        s.web.paper_search_url.clear()
    });
    assert!(
        !off.schemas()
            .iter()
            .any(|s| s.function.name == "PaperSearch")
    );
}

#[test]
fn text_that_plainly_names_a_boolean_or_number_is_read_as_one() {
    let web = script(|_| page("application/json", WORKS));
    let mut r = registry("paper-coerce", Some(web.clone()), |_| {});
    let out = r.call(
        "PaperSearch",
        leak(json!({"query": "nmpc", "open_access_only": "True", "max_results": " 2 "})),
    );
    assert_eq!(out["results"].as_array().map(Vec::len), Some(2), "{out}");
    assert!(web.seen.lock().expect("lock")[0].contains("per-page=2&"));
    let out = r.call(
        "PaperSearch",
        leak(json!({"query": "nmpc", "open_access_only": "False"})),
    );
    assert!(
        !web.seen.lock().expect("lock")[1].contains("is_oa"),
        "{out}"
    );
    // text that names nothing is still refused
    let out = r.call(
        "PaperSearch",
        leak(json!({"query": "nmpc", "max_results": "tài nguyên"})),
    );
    assert_eq!(out["error"]["code"], "invalid_arguments");
}
