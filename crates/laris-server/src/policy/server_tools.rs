//! Server tools (T273): the tools the server runs itself for a client that has none, as Claude's `web_search` and
//! `web_fetch` are run by the platform. The web client has no folder and no network of its own, so a research
//! question asked there is answered by searching the works index and the web and reading the papers here.
//!
//! The tools are the terminal client's own web tools (`laris_tools`, `WebSearch`, `WebFetch`, `PaperSearch`), over a
//! registry that holds nothing else: no file, shell or memory tool can be reached. Every address goes through the
//! public-only [`WebClient`]: an address that points to this machine or its network is refused, redirects included.
//! A call runs on a blocking thread; its result goes back to the model, cut to a budget, and a short record of it
//! (tool, query or address, outcome, sources) goes to the client so it can show what was done.

use laris_model_client::{WebClient, WebOptions};
use laris_protocol::chat::ToolSchema;
use laris_tools::{Context, Page, Registry, ToolError, WebTransport};
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

/// The tools the server may run for a client.
pub const SERVER_TOOLS: [&str; 3] = ["WebSearch", "WebFetch", "PaperSearch"];

/// The research-gap analysis over the papers read in one answer (laris-gap, rules G1–G4).
pub const GAP_TOOL: &str = "analyze_research_gaps";

/// Longest text of one fetched document kept for the analysis.
const DOCUMENT_CHARS: u64 = 200_000;

/// Settings of the server tools, from `LARIS_SERVER__SERVER_TOOLS*` and `LARIS_SERVER__WEB_*` variables.
#[derive(Debug, Clone, PartialEq)]
pub struct ServerToolSettings {
    /// Offer the tools at all.
    pub enabled: bool,
    /// Most calls in one answer.
    pub max_calls: usize,
    /// Most characters of one result given to the model.
    pub result_chars: usize,
    /// Papers registered after which the model is told to run the research-gap analysis.
    pub gap_papers: usize,
    /// Word overlap (token F1) of two titles above which two documents are one paper (an archive's and a
    /// publisher's copy).
    pub same_title: f64,
    /// Addresses, limits and agent of the web tools.
    pub web: laris_config::settings::Web,
}

impl Default for ServerToolSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            max_calls: 12,
            result_chars: 12_000,
            gap_papers: 4,
            same_title: 0.9,
            web: laris_config::settings::Web::default(),
        }
    }
}

/// What one call gave: the text for the model and the record for the client.
#[derive(Debug, Clone)]
pub struct Outcome {
    /// The result as the model reads it.
    pub text: String,
    /// `{name, input, ok, error, sources: [{title, url}]}`.
    pub record: Value,
    /// A document read in full (`WebFetch`).
    pub document: Option<Document>,
}

/// A document the server read: a fetched page or PDF, or a file the user attached.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    /// Address or file name.
    pub origin: String,
    /// Title, when known.
    pub title: String,
    /// The text.
    pub text: String,
    /// How the text was obtained (`text_layer`, `html`, `attachment`, ...).
    pub read_by: String,
}

/// The papers of one answer, with the extraction record of each once it is made.
#[derive(Debug, Default)]
pub struct Library {
    /// Papers in the order they were read: `P1`, `P2`, ...
    pub papers: Vec<laris_gap::Paper>,
    /// Records by paper id.
    pub records: std::collections::BTreeMap<String, Result<laris_gap::Record, String>>,
    years: std::collections::HashMap<String, u32>,
    titles: std::collections::HashMap<String, String>,
}

impl Library {
    /// Keeps the years and titles a search result gave, so a paper fetched from its address gets them (a PDF
    /// often has no title of its own).
    pub fn note_years(&mut self, record: &Value) {
        for s in record["sources"].as_array().into_iter().flatten() {
            let Some(url) = s["url"].as_str() else {
                continue;
            };
            if let Some(year) = s["year"].as_u64() {
                self.years
                    .insert(url.to_owned(), u32::try_from(year).unwrap_or_default());
            }
            if let Some(title) = s["title"].as_str().filter(|t| *t != url) {
                self.titles.insert(url.to_owned(), title.to_owned());
            }
        }
    }

    /// Registers `doc` and returns its new id, or `None` when it is already in (same address, or a title whose
    /// word overlap with one already in is `same_title` or more) or too short to be a paper.
    pub fn add(&mut self, mut doc: Document, same_title: f64) -> Option<String> {
        if let Some(known) = self.titles.get(&doc.origin) {
            // the works index's title is the paper's; a PDF's own is often a file name or empty
            doc.title.clone_from(known);
        }
        let title = doc.title.trim();
        if doc.text.split_whitespace().count() < 200
            || self.papers.iter().any(|p| {
                p.origin == doc.origin
                    || (!title.is_empty()
                        && laris_gap::text::token_f1(&p.title, title) >= same_title)
            })
        {
            return None;
        }
        let id = format!("P{}", self.papers.len() + 1);
        let title = if doc.title.trim().is_empty() {
            doc.origin.clone()
        } else {
            doc.title.trim().to_owned()
        };
        self.papers.push(laris_gap::Paper {
            id: id.clone(),
            title,
            year: self.years.get(&doc.origin).copied(),
            origin: doc.origin,
            read_by: doc.read_by,
            text: doc.text,
        });
        Some(id)
    }

    /// The papers that have no record yet.
    pub fn unextracted(&self) -> Vec<laris_gap::Paper> {
        self.papers
            .iter()
            .filter(|p| !self.records.contains_key(&p.id))
            .cloned()
            .collect()
    }
}

/// The schema of [`GAP_TOOL`].
pub fn gap_schema() -> ToolSchema {
    let terms = json!({"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}});
    serde_json::from_value(json!({
        "type": "function",
        "function": {
            "name": GAP_TOOL,
            "description": "Finds research gaps in the papers read in this answer (every WebFetch of a paper and \
                every attached file is registered as P1, P2, ...). It extracts each paper's own limitations and \
                future work with quotations checked against the text, tags them with your concepts and applies the \
                rules G1-G4 (shared limitation, unresolved conflict, unexplored combination, stated future work). \
                Give 2 to 8 concepts per facet, each with the words that mark it in the papers. Returns the report: \
                give it to the user as it is, with its paper ids and quotations; do not add papers or quotations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The research question, in English."},
                    "concepts": {
                        "type": "object",
                        "description": "{\"method\": {\"Concept name\": [\"term\", ...]}, \"setting\": {...}, \"issue\": {...}}",
                        "properties": {"method": terms, "setting": terms, "issue": terms},
                        "required": ["method", "setting", "issue"]
                    }
                },
                "required": ["question", "concepts"]
            }
        }
    }))
    .expect("the schema is valid")
}

/// The topic of a [`GAP_TOOL`] call, checked: three facets, each with named concepts that have terms.
pub fn topic_from(
    args: &Value,
    settings: &laris_gap::Settings,
) -> Result<laris_gap::Topic, String> {
    let question = args["question"].as_str().unwrap_or_default().trim();
    if question.is_empty() {
        return Err("`question` is empty".into());
    }
    let mut concepts = std::collections::BTreeMap::new();
    for facet in ["method", "setting", "issue"] {
        let mut named = std::collections::BTreeMap::new();
        for (name, terms) in args["concepts"][facet].as_object().into_iter().flatten() {
            let terms: Vec<String> = terms
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(|t| t.trim().to_lowercase())
                .filter(|t| t.chars().count() >= 2)
                .collect();
            if !terms.is_empty() && !name.trim().is_empty() {
                named.insert(name.trim().to_owned(), terms);
            }
        }
        if named.is_empty() {
            return Err(format!(
                "no `{facet}` concept with terms; give `concepts` as {{\"method\": {{\"Name\": [\"term\", ...]}}, \"setting\": {{...}}, \"issue\": {{...}}}}"
            ));
        }
        concepts.insert(facet.to_owned(), named);
    }
    Ok(laris_gap::Topic {
        id: "chat".into(),
        title: question.to_owned(),
        question: question.to_owned(),
        cutoff_year: None,
        concepts,
        conflict: settings.conflict.clone(),
    })
}

/// The server tools of a running server.
pub struct ServerTools {
    settings: ServerToolSettings,
    client: WebClient,
    schemas: Vec<ToolSchema>,
    root: PathBuf,
}

/// Lets the sync tools use the async client from a blocking thread.
struct Bridge {
    client: WebClient,
    handle: tokio::runtime::Handle,
}

impl WebTransport for Bridge {
    fn get(&self, url: &str, accept: &str) -> Result<Page, ToolError> {
        let page = self
            .handle
            .block_on(self.client.get(url, accept))
            .map_err(|e| ToolError::new(e.code, e.message))?;
        Ok(Page {
            status: page.status,
            url: page.url,
            content_type: page.content_type,
            body: page.body,
            truncated: page.truncated,
        })
    }
}

impl ServerTools {
    /// The tools of `settings`, or `None` when they are off.
    pub fn new(settings: ServerToolSettings) -> Result<Option<Self>, String> {
        if !settings.enabled {
            return Ok(None);
        }
        let client = WebClient::new(WebOptions {
            timeout: Duration::from_secs(settings.web.timeout_seconds.max(1)),
            max_bytes: usize::try_from(settings.web.max_bytes).unwrap_or(usize::MAX),
            max_redirects: settings.web.max_redirects,
            user_agent: settings.web.user_agent.clone(),
        })
        .map_err(|e| format!("server tools: {e:?}"))?;
        let root = std::env::temp_dir();
        // the schemas once, from a registry that is never called
        let ctx = Self::context(&settings, &root)?;
        let ctx = ctx.with_web(Arc::new(Refuse));
        let schemas = Registry::web_only(ctx)
            .schemas()
            .into_iter()
            .filter(|s| SERVER_TOOLS.contains(&s.function.name.as_str()))
            .collect();
        Ok(Some(Self {
            settings,
            client,
            schemas,
            root,
        }))
    }

    fn context(settings: &ServerToolSettings, root: &std::path::Path) -> Result<Context, String> {
        let mut all = laris_config::settings::Settings {
            web: laris_config::settings::Web {
                enabled: true,
                ..settings.web.clone()
            },
            ..Default::default()
        };
        // the registry keeps whole documents; what the model reads is cut in `outcome`
        all.tools.result_max_chars = u32::try_from(DOCUMENT_CHARS * 2).unwrap_or(u32::MAX);
        // the server image has no PDF programs: the built-in reader only
        all.vault.ocr.enabled = false;
        Context::new(root, &all).map_err(|e| format!("server tools: {}", e.message))
    }

    /// The schemas of the tools named in `allowed` (all when `None`) that the client does not offer itself.
    pub fn offered(&self, allowed: Option<&[String]>, client: &[String]) -> Vec<ToolSchema> {
        self.schemas
            .iter()
            .filter(|s| allowed.is_none_or(|a| a.contains(&s.function.name)))
            .filter(|s| !client.contains(&s.function.name))
            .cloned()
            .collect()
    }

    /// Most characters of one result given to the model.
    pub fn result_chars(&self) -> usize {
        self.settings.result_chars
    }

    /// Title overlap above which two documents are one paper.
    pub fn same_title(&self) -> f64 {
        self.settings.same_title
    }

    /// Papers after which the model is told to run the analysis.
    pub fn gap_papers(&self) -> usize {
        self.settings.gap_papers
    }

    /// Most calls in one answer.
    pub fn max_calls(&self) -> usize {
        self.settings.max_calls
    }

    /// Runs `name` with the JSON `arguments`.
    pub async fn call(&self, name: &str, arguments: &str) -> Outcome {
        let mut args: Map<String, Value> = serde_json::from_str(arguments).unwrap_or_default();
        if name == "WebFetch" {
            // the whole document for the analysis; the model gets the cut below
            args.insert("max_chars".into(), json!(DOCUMENT_CHARS));
        }
        let input = args
            .get("query")
            .or_else(|| args.get("url"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let handle = tokio::runtime::Handle::current();
        let (client, settings, root) = (
            self.client.clone(),
            self.settings.clone(),
            self.root.clone(),
        );
        let owned = name.to_owned();
        let ran = tokio::task::spawn_blocking(move || {
            let ctx =
                Self::context(&settings, &root)?.with_web(Arc::new(Bridge { client, handle }));
            Ok::<Value, String>(Registry::web_only(ctx).call(&owned, &args))
        })
        .await;
        let value = match ran {
            Ok(Ok(v)) => v,
            Ok(Err(e)) => json!({"error": {"code": "server_tool_failed", "message": e}}),
            Err(e) => json!({"error": {"code": "server_tool_failed", "message": e.to_string()}}),
        };
        self.outcome(name, &input, &value)
    }

    fn outcome(&self, name: &str, input: &str, value: &Value) -> Outcome {
        let error = value
            .get("error")
            .map(|e| {
                e.get("message")
                    .and_then(Value::as_str)
                    .map_or_else(|| e.to_string(), str::to_owned)
            })
            .unwrap_or_default();
        let mut sources = Vec::new();
        let mut push = |v: &Value| {
            let url = ["pdf_url", "url"]
                .iter()
                .find_map(|k| v.get(*k).and_then(Value::as_str).filter(|u| !u.is_empty()));
            if let Some(url) = url {
                sources.push(json!({
                    "title": v.get("title").and_then(Value::as_str).unwrap_or(url),
                    "url": url,
                    "year": v.get("year").cloned().unwrap_or(Value::Null),
                }));
            }
        };
        match value.get("results").and_then(Value::as_array) {
            Some(list) => list.iter().for_each(&mut push),
            None if error.is_empty() => push(value),
            None => {}
        }
        let document = (name == "WebFetch" && error.is_empty())
            .then(|| {
                let text = value.get("content").and_then(Value::as_str)?;
                let field = |k: &str| value.get(k).and_then(Value::as_str).unwrap_or_default();
                Some(Document {
                    origin: value
                        .get("url")
                        .and_then(Value::as_str)
                        .unwrap_or(input)
                        .to_owned(),
                    title: field("title").to_owned(),
                    text: text.to_owned(),
                    read_by: if field("read_by").is_empty() {
                        "html".to_owned()
                    } else {
                        field("read_by").to_owned()
                    },
                })
            })
            .flatten();
        let full = value.to_string();
        let text = cut(&full, self.settings.result_chars);
        Outcome {
            text,
            record: json!({
                "name": name,
                "input": input,
                "ok": error.is_empty(),
                "error": error,
                "sources": sources,
            }),
            document,
        }
    }
}

/// A transport for the schemas only.
struct Refuse;

impl WebTransport for Refuse {
    fn get(&self, _url: &str, _accept: &str) -> Result<Page, ToolError> {
        Err(ToolError::new("web_unavailable", "not a call"))
    }
}

/// `text` cut to `limit` characters, with a note when cut.
pub fn cut(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit {
        return text.to_owned();
    }
    let kept: String = text.chars().take(limit).collect();
    format!("{kept}\n[cut at {limit} characters]")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tools() -> ServerTools {
        ServerTools::new(ServerToolSettings {
            enabled: true,
            ..ServerToolSettings::default()
        })
        .unwrap()
        .unwrap()
    }

    #[test]
    fn off_by_default_and_only_web_tools() {
        assert!(
            ServerTools::new(ServerToolSettings::default())
                .unwrap()
                .is_none()
        );
        let t = tools();
        let names: Vec<_> = t
            .offered(None, &[])
            .into_iter()
            .map(|s| s.function.name)
            .collect();
        assert!(names.iter().all(|n| SERVER_TOOLS.contains(&n.as_str())));
        assert!(names.contains(&"PaperSearch".to_owned()));
        assert!(
            !names
                .iter()
                .any(|n| n == "Bash" || n == "Read" || n == "Write")
        );
    }

    #[test]
    fn a_tool_the_client_runs_itself_is_not_offered() {
        let t = tools();
        let allowed = vec!["PaperSearch".to_owned(), "WebFetch".to_owned()];
        let names: Vec<_> = t
            .offered(Some(&allowed), &["WebFetch".to_owned()])
            .into_iter()
            .map(|s| s.function.name)
            .collect();
        assert_eq!(names, vec!["PaperSearch".to_owned()]);
    }

    #[test]
    fn a_result_names_its_sources() {
        let t = tools();
        let found = json!({"query": "q", "results": [
            {"title": "A", "url": "https://a.org/x", "pdf_url": "https://a.org/x.pdf", "year": 2024},
            {"title": "B", "url": "https://b.org/y", "pdf_url": ""}]});
        let o = t.outcome("PaperSearch", "q", &found);
        assert_eq!(o.record["sources"][0]["url"], "https://a.org/x.pdf");
        assert_eq!(o.record["sources"][1]["url"], "https://b.org/y");
        let read = json!({"url": "https://a.org/x.pdf", "title": "A", "content": "text"});
        let o = t.outcome("WebFetch", "https://a.org/x.pdf", &read);
        assert_eq!(o.document.unwrap().text, "text");
        let failed = json!({"error": {"code": "blocked", "message": "not public"}});
        let o = t.outcome("WebFetch", "http://10.0.0.1/", &failed);
        assert_eq!(o.record["ok"], false);
        assert_eq!(o.record["error"], "not public");
        assert!(cut(&"x".repeat(50), 10).starts_with("xxxxxxxxxx\n[cut"));
    }

    #[test]
    fn a_topic_needs_three_facets_and_a_paper_needs_text() {
        let settings = laris_gap::Settings::from_toml(
            &std::fs::read_to_string(
                std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.laris/gap.toml"),
            )
            .unwrap(),
        )
        .unwrap();
        let ok = json!({"question": "q?", "concepts": {
            "method": {"Probe": ["probe", "probing"]}, "setting": {"QA": ["qa"]}, "issue": {"Cost": ["cost"]}}});
        let topic = topic_from(&ok, &settings).unwrap();
        assert_eq!(topic.concepts["method"]["Probe"], ["probe", "probing"]);
        assert!(!topic.conflict.negative.is_empty(), "the policy's cues");
        let missing = json!({"question": "q?", "concepts": {"method": {"Probe": ["probe"]}}});
        assert!(
            topic_from(&missing, &settings)
                .unwrap_err()
                .contains("setting")
        );
        let mut lib = Library::default();
        lib.note_years(
            &json!({"sources": [{"url": "https://a.org/x.pdf", "year": 2024,
            "title": "RAGTruth: A Hallucination Corpus for Retrieval-Augmented Models"}]}),
        );
        let doc = |origin: &str, words: usize| Document {
            origin: origin.into(),
            title: "RAGTruth: A Hallucination Corpus for Retrieval-Augmented Models".into(),
            text: "word ".repeat(words),
            read_by: "text_layer".into(),
        };
        assert_eq!(
            lib.add(doc("https://a.org/x.pdf", 300), 0.9).as_deref(),
            Some("P1")
        );
        assert_eq!(lib.papers[0].year, Some(2024));
        assert!(lib.papers[0].title.starts_with("RAGTruth"));
        assert!(
            lib.add(doc("https://a.org/x.pdf", 300), 0.9).is_none(),
            "once"
        );
        assert!(
            lib.add(doc("https://b.org/", 20), 0.9).is_none(),
            "too short"
        );
        let mut copy = doc("https://c.org/abs", 300);
        copy.title = "RAGTruth: a hallucination corpus for retrieval-augmented models".into();
        assert!(
            lib.add(copy, 0.9).is_none(),
            "the same title from another address"
        );
        assert_eq!(lib.unextracted().len(), 1);
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_private_address_is_refused() {
        let t = tools();
        let o = t
            .call("WebFetch", r#"{"url": "http://127.0.0.1:1/"}"#)
            .await;
        assert_eq!(o.record["ok"], false, "{:?}", o.record);
    }
}
