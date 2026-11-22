//! `laris gap run | collect | score | sheet`: the research-gap workflow end to end, with every intermediate result
//! written to a run folder (T272).
//!
//! * `run TOPIC_DIR [--only P1,P2] [--until YEAR] [--from YEAR] [--out DIR] [--baselines closed,context,rag]`:
//!   reads `TOPIC_DIR/topic.toml` and `TOPIC_DIR/register.json`, reads every PDF on this machine (the text layer,
//!   then `pdftotext`, then OCR, as `vault.ocr` says), sends each paper to the server's extraction route, then the
//!   whole set to the analysis route, then runs the baselines with the same model. Unresolved references of every
//!   answer are looked up in the works index (`web.paperSearchUrl`).
//! * `collect --query TEXT --out DIR [--count N]`: step 1 from keywords: asks the works index, downloads the open
//!   copies (an arXiv copy first) and writes `register.json`; a paper that cannot be downloaded is listed as not read.
//! * `score RUN_DIR [--gold DIR] [--threshold T] [--verdicts FILE] [--ratings FILE] [--sheet FILE] [--full RUN_DIR]`:
//!   the measured numbers of a run, written to `RUN_DIR/metrics.json`.
//! * `sheet RUN_DIR... --out FILE`: a blind rating sheet of the gaps of the system and the baselines.
//!
//! Paper ids are given by the order of the register, so a subset run keeps the ids of the full run.

use crate::login::{self, Startup};
use crate::start::Started;
use laris_gap::analyze::Analysis;
use laris_gap::audit::{self, Audit};
use laris_gap::evaluate::{self, GoldItem, Rating, TagVerdict};
use laris_gap::text::{normalize, token_f1};
use laris_gap::{Paper, Topic};
use laris_model_client::{Interrupt, ModelClient, ReqwestTransport, WebClient, WebOptions};
use laris_tools::ingest::{self, PdfLimits};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The usage text.
pub const USAGE: &str = "usage: laris gap run TOPIC_DIR [--only P1,P2] [--until YEAR] [--from YEAR] [--out DIR] [--baselines closed,context,rag]\n\
       laris gap collect --query TEXT --out DIR [--count N]\n\
       laris gap score RUN_DIR [--gold DIR] [--threshold 0.5] [--verdicts FILE] [--ratings FILE] [--sheet FILE] [--full RUN_DIR]\n\
       laris gap sheet RUN_DIR... --out FILE";

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn positional(args: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    let mut skip = false;
    for a in args {
        if skip {
            skip = false;
            continue;
        }
        if a.starts_with("--") {
            skip = true;
            continue;
        }
        out.push(a.clone());
    }
    out
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)
            .map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    }
    std::fs::write(
        path,
        serde_json::to_string_pretty(value).unwrap_or_default(),
    )
    .map_err(|e| format!("cannot write {}: {e}", path.display()))
}

struct Server {
    client: ModelClient<ReqwestTransport>,
    runtime: tokio::runtime::Runtime,
}

impl Server {
    fn connect(started: &Started, timeout: f64) -> Result<Server, String> {
        let (server, key) = match login::decide(&started.home, &started.settings, &started.env) {
            Startup::Ready { server, key, .. } => (server, key),
            Startup::NoServer => return Err("no server address; set server.url".into()),
            Startup::NeedsLogin { server, .. } => {
                return Err(format!("not signed in to {server}; run laris login"));
            }
        };
        let mut cfg = started.settings.server.clone();
        cfg.url = server;
        cfg.timeout_seconds = cfg.timeout_seconds.max(timeout);
        cfg.idle_timeout_seconds = cfg.idle_timeout_seconds.max(timeout);
        cfg.max_retries = 0;
        cfg.max_response_bytes = cfg.max_response_bytes.max(64 << 20);
        let client = login::connect(&cfg, &key, true).map_err(|e| e.to_string())?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())?;
        Ok(Server { client, runtime })
    }

    fn post(&self, path: &str, body: &Value) -> Result<Value, String> {
        self.runtime
            .block_on(
                self.client
                    .post_json::<Value, Value>(path, body, &Interrupt::new()),
            )
            .map_err(|e| format!("{path}: {e}"))
    }

    fn get(&self, path: &str) -> Result<Value, String> {
        self.runtime
            .block_on(self.client.get_json::<Value>(path, &Interrupt::new()))
            .map_err(|e| format!("{path}: {e}"))
    }
}

fn web(started: &Started) -> Result<(WebClient, tokio::runtime::Runtime), String> {
    let client = WebClient::new(WebOptions {
        timeout: Duration::from_secs(started.settings.web.timeout_seconds.max(1)),
        max_bytes: 64 << 20,
        max_redirects: 8,
        user_agent: format!(
            "laris/{} (research-gap evaluation)",
            env!("CARGO_PKG_VERSION")
        ),
    })
    .map_err(|e| format!("{e:?}"))?;
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| e.to_string())?;
    Ok((client, rt))
}

fn percent(text: &str) -> String {
    text.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// Looks every unresolved reference of `a` up in the works index.
fn check_external(started: &Started, a: &mut Audit) {
    let pending: Vec<usize> = a
        .citations
        .iter()
        .enumerate()
        .filter(|(_, c)| {
            c.kind == "reference" && c.resolved.is_none() && c.exists_externally.is_none()
        })
        .map(|(i, _)| i)
        .collect();
    if pending.is_empty() {
        return;
    }
    let Ok((client, rt)) = web(started) else {
        return;
    };
    let base = started.settings.web.paper_search_url.clone();
    for i in pending {
        let text = a.citations[i].text.clone();
        let year = text
            .chars()
            .filter(char::is_ascii_digit)
            .collect::<String>();
        let year = (year.len() >= 4).then(|| year[year.len() - 4..].to_owned());
        let surname = text
            .split_whitespace()
            .next()
            .unwrap_or("")
            .trim_matches(|c: char| !c.is_alphabetic())
            .to_lowercase();
        let joiner = if base.contains('?') { '&' } else { '?' };
        // "Hanover et al., 2022": the works of that year whose text names the author; a title: the title itself
        let author_style = year.is_some()
            && text.chars().next().is_some_and(char::is_uppercase)
            && text.split_whitespace().count() <= 6;
        let url = match (&year, author_style) {
            (Some(y), true) => format!(
                "{base}{joiner}search={}&filter=publication_year:{y}&per-page=25&select=title,publication_year,authorships",
                percent(&surname)
            ),
            _ => format!(
                "{base}{joiner}search={}&per-page=5&select=title,publication_year,authorships",
                percent(&text)
            ),
        };
        std::thread::sleep(Duration::from_millis(250));
        let Ok(page) = rt.block_on(client.get(&url, "application/json")) else {
            continue;
        };
        let Ok(v) = serde_json::from_slice::<Value>(&page.body) else {
            continue;
        };
        let mut verdict = false;
        let mut seen = String::new();
        for w in v["results"].as_array().into_iter().flatten() {
            let title = w["title"].as_str().unwrap_or("");
            let wy = w["publication_year"].as_u64().map(|y| y.to_string());
            let authors: Vec<String> = w["authorships"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|x| x["author"]["display_name"].as_str())
                .map(str::to_lowercase)
                .collect();
            if seen.is_empty() {
                seen = format!("{title} ({})", wy.clone().unwrap_or_default());
            }
            // a reference written as a title exists only if a work of nearly that title does; one written as
            // author and year exists if a work of that author and year does
            let by_title = token_f1(title, &text) >= if year.is_some() { 0.7 } else { 0.85 };
            let by_author = year.is_some()
                && !surname.is_empty()
                && authors
                    .iter()
                    .any(|n| n.split_whitespace().last() == Some(surname.as_str()))
                && (year.is_none() || wy == year);
            if by_title || by_author {
                verdict = true;
                seen = format!("{title} ({})", wy.unwrap_or_default());
                break;
            }
        }
        a.citations[i].exists_externally = Some(verdict);
        a.citations[i].external_match = seen;
    }
    audit::recount(a);
}

fn register(dir: &Path) -> Result<Vec<Value>, String> {
    let reg = read_json(&dir.join("register.json"))?;
    reg.as_array()
        .cloned()
        .ok_or_else(|| "register.json is not a list".into())
}

fn read_papers(
    started: &Started,
    dir: &Path,
    out: &Path,
    select: &dyn Fn(&str, Option<u32>) -> bool,
) -> Result<(Vec<Paper>, Vec<Value>), String> {
    let limits = PdfLimits {
        max_stream_bytes: usize::try_from(started.settings.vault.ingest_max_bytes)
            .unwrap_or(usize::MAX)
            .saturating_mul(4),
        max_pages: 5_000,
    };
    let mut papers = Vec::new();
    let mut unread = Vec::new();
    for (n, entry) in register(dir)?.iter().enumerate() {
        let id = format!("P{}", n + 1);
        let year = entry["year"].as_u64().and_then(|y| u32::try_from(y).ok());
        if !select(&id, year) {
            continue;
        }
        let title = entry["title"].as_str().unwrap_or("").to_owned();
        let origin = entry["origin"].as_str().unwrap_or("").to_owned();
        let Some(file) = entry["file"].as_str() else {
            unread.push(json!({"id": id, "title": title, "origin": origin, "reason": entry["reason"].as_str().unwrap_or("no file")}));
            continue;
        };
        match ingest::read_document_with(
            &dir.join(file),
            started.settings.vault.ingest_max_bytes,
            &limits,
            Some(&started.settings.vault.ocr),
        ) {
            Ok((doc, method)) => {
                std::fs::create_dir_all(out.join("papers")).map_err(|e| e.to_string())?;
                std::fs::write(out.join("papers").join(format!("{id}.txt")), &doc.text)
                    .map_err(|e| e.to_string())?;
                papers.push(Paper {
                    id,
                    title,
                    origin,
                    year,
                    read_by: method.as_str().to_owned(),
                    text: doc.text,
                });
            }
            Err(e) => unread
                .push(json!({"id": id, "title": title, "origin": origin, "reason": e.to_string()})),
        }
    }
    Ok((papers, unread))
}

fn run(started: &Started, args: &[String]) -> Result<String, String> {
    let pos = positional(args);
    let dir = PathBuf::from(pos.first().ok_or(USAGE)?);
    let topic_text =
        std::fs::read_to_string(dir.join("topic.toml")).map_err(|e| format!("topic.toml: {e}"))?;
    let topic = Topic::from_toml(&topic_text)?;
    let only: Option<Vec<String>> =
        flag(args, "--only").map(|s| s.split(',').map(str::to_owned).collect());
    let until: Option<u32> = flag(args, "--until").and_then(|s| s.parse().ok());
    let from: Option<u32> = flag(args, "--from").and_then(|s| s.parse().ok());
    let label = flag(args, "--label").unwrap_or_else(|| "all".into());
    let out = flag(args, "--out").map_or_else(|| dir.join("runs").join(&label), PathBuf::from);
    let baselines: Vec<String> = flag(args, "--baselines")
        .unwrap_or_else(|| "closed,context,rag".into())
        .split(',')
        .filter(|s| !s.is_empty() && *s != "none")
        .map(str::to_owned)
        .collect();
    let timeout: f64 = flag(args, "--timeout")
        .and_then(|s| s.parse().ok())
        .unwrap_or(900.0);
    std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let started_at = Instant::now();
    let select = |id: &str, year: Option<u32>| {
        only.as_ref().is_none_or(|o| o.iter().any(|x| x == id))
            && until.is_none_or(|u| year.is_some_and(|y| y <= u))
            && from.is_none_or(|f| year.is_some_and(|y| y >= f))
    };
    let (papers, unread) = read_papers(started, &dir, &out, &select)?;
    eprintln!(
        "laris gap: {} papers read, {} not read",
        papers.len(),
        unread.len()
    );
    let server = Server::connect(started, timeout)?;
    let policy = server.get("/laris/gap/policy")?;
    write_json(&out.join("policy.json"), &policy)?;
    let settings: laris_gap::Settings =
        serde_json::from_value(policy.clone()).map_err(|e| format!("policy: {e}"))?;
    let mut records = serde_json::Map::new();
    let mut extract_seconds = 0.0;
    for p in &papers {
        let path = out.join("extract").join(format!("{}.json", p.id));
        let answer = if path.is_file() && args.iter().any(|a| a == "--resume") {
            read_json(&path)?
        } else {
            let a = server.post("/laris/gap/extract", &json!({"paper": p}))?;
            write_json(&path, &a)?;
            a
        };
        extract_seconds += answer["seconds"].as_f64().unwrap_or(0.0);
        eprintln!(
            "laris gap: extract {} {}s {}",
            p.id,
            answer["seconds"],
            if answer["error"].is_null() {
                "ok"
            } else {
                "error"
            }
        );
        records.insert(
            p.id.clone(),
            json!({"record": answer["record"], "error": answer["error"]}),
        );
    }
    let analysis = server.post(
        "/laris/gap/analyze",
        &json!({"topic": topic, "papers": papers, "records": records}),
    )?;
    let mut report_audit: Audit =
        serde_json::from_value(analysis["audit"].clone()).map_err(|e| e.to_string())?;
    check_external(started, &mut report_audit);
    write_json(&out.join("analysis.json"), &analysis["analysis"])?;
    std::fs::write(
        out.join("report.md"),
        analysis["report"].as_str().unwrap_or(""),
    )
    .map_err(|e| e.to_string())?;
    write_json(&out.join("audit.json"), &json!(report_audit))?;
    let mut base_summary = serde_json::Map::new();
    for mode in &baselines {
        let path = out.join("baselines").join(format!("{mode}.json"));
        let mut answer = if path.is_file() && args.iter().any(|a| a == "--resume") {
            // the saved answer, audited again with the policy of this run: no model call
            let mut saved = read_json(&path)?;
            let a = audit::audit(saved["answer"].as_str().unwrap_or(""), &papers, &settings);
            saved["audit"] = json!(a);
            saved
        } else {
            server.post(
                "/laris/gap/baseline",
                &json!({"mode": mode, "question": topic.question, "papers": papers}),
            )?
        };
        let mut a: Audit =
            serde_json::from_value(answer["audit"].clone()).map_err(|e| e.to_string())?;
        check_external(started, &mut a);
        answer["audit"] = json!(a);
        write_json(&path, &answer)?;
        eprintln!("laris gap: baseline {mode} {}s", answer["seconds"]);
        base_summary.insert(
            mode.clone(),
            json!({"seconds": answer["seconds"], "audit": a.counts}),
        );
    }
    let manifest = json!({
        "topic": topic.id,
        "label": label,
        "policy_version": policy["version"],
        "papers": papers.iter().map(|p| json!({"id": p.id, "title": p.title, "year": p.year, "origin": p.origin, "read_by": p.read_by, "chars": p.text.chars().count()})).collect::<Vec<_>>(),
        "not_read": unread,
        "filters": {"only": only, "until": until, "from": from},
        "extract_seconds": (extract_seconds * 10.0_f64).round() / 10.0,
        "analyze_milliseconds": analysis["milliseconds"],
        "total_seconds": started_at.elapsed().as_secs(),
        "report_audit": report_audit.counts,
        "baselines": base_summary,
        "laris": env!("CARGO_PKG_VERSION"),
    });
    write_json(&out.join("run.json"), &manifest)?;
    Ok(format!("run written to {}", out.display()))
}

fn collect(started: &Started, args: &[String]) -> Result<String, String> {
    let query = flag(args, "--query").ok_or(USAGE)?;
    let out = PathBuf::from(flag(args, "--out").ok_or(USAGE)?);
    let count: u64 = flag(args, "--count")
        .and_then(|s| s.parse().ok())
        .unwrap_or(15);
    let (client, rt) = web(started)?;
    let base = started.settings.web.paper_search_url.clone();
    let joiner = if base.contains('?') { '&' } else { '?' };
    let url = format!(
        "{base}{joiner}search={}&per-page={count}&filter=is_oa:true&select=id,doi,title,publication_year,best_oa_location,locations",
        percent(&query)
    );
    let page = rt
        .block_on(client.get(&url, "application/json"))
        .map_err(|e| format!("{e:?}"))?;
    let v: Value = serde_json::from_slice(&page.body).map_err(|e| format!("works index: {e}"))?;
    std::fs::create_dir_all(out.join("pdf")).map_err(|e| e.to_string())?;
    let mut register = Vec::new();
    for (n, w) in v["results"].as_array().into_iter().flatten().enumerate() {
        let title = w["title"].as_str().unwrap_or("").to_owned();
        let year = w["publication_year"].as_u64();
        let mut urls: Vec<String> = Vec::new();
        for loc in w["locations"].as_array().into_iter().flatten() {
            if let Some(u) = loc["pdf_url"].as_str() {
                if u.contains("arxiv.org") {
                    urls.insert(0, u.to_owned());
                } else {
                    urls.push(u.to_owned());
                }
            }
        }
        let mut entry = json!({"title": title, "year": year, "openalex": w["id"], "doi": w["doi"], "tried": urls});
        let mut reason = "no free PDF location".to_owned();
        for u in &urls {
            std::thread::sleep(Duration::from_millis(500));
            match rt.block_on(client.get(u, "application/pdf")) {
                Ok(p) if p.status < 400 && p.body.starts_with(b"%PDF") && !p.truncated => {
                    let file = format!("pdf/work{:02}.pdf", n + 1);
                    std::fs::write(out.join(&file), &p.body).map_err(|e| e.to_string())?;
                    entry["file"] = json!(file);
                    entry["origin"] = json!(u);
                    break;
                }
                Ok(p) => {
                    reason = format!(
                        "{u}: status {} {}",
                        p.status,
                        if p.body.starts_with(b"%PDF") {
                            ""
                        } else {
                            "(not a PDF)"
                        }
                    )
                }
                Err(e) => reason = format!("{u}: {e:?}"),
            }
        }
        if entry.get("file").is_none() {
            entry["reason"] = json!(reason);
            entry["origin"] = w["id"].clone();
        }
        register.push(entry);
    }
    let read = register.iter().filter(|e| e.get("file").is_some()).count();
    write_json(&out.join("register.json"), &json!(register))?;
    write_json(
        &out.join("collect.json"),
        &json!({"query": query, "url": url, "results": register.len(), "downloaded": read}),
    )?;
    Ok(format!(
        "{} works found, {read} downloaded; register written to {}",
        register.len(),
        out.display()
    ))
}

fn load_analysis(run: &Path) -> Result<Analysis, String> {
    // Analysis is Serialize only: rebuild what scoring needs through the JSON
    let v = read_json(&run.join("analysis.json"))?;
    analysis_from(&v)
}

fn analysis_from(v: &Value) -> Result<Analysis, String> {
    laris_gap::analyze::from_json(v)
}

fn gold_for(run: &Path, gold_dir: &Path) -> Result<BTreeMap<String, Vec<GoldItem>>, String> {
    let manifest = read_json(&run.join("run.json"))?;
    let mut out = BTreeMap::new();
    for p in manifest["papers"].as_array().into_iter().flatten() {
        let id = p["id"].as_str().unwrap_or("").to_owned();
        let origin = p["origin"].as_str().unwrap_or("");
        let arxiv = origin.rsplit('/').next().unwrap_or("");
        let path = gold_dir.join(format!("{arxiv}.json"));
        if let Ok(g) = read_json(&path) {
            let items: Vec<GoldItem> = serde_json::from_value(g["items"].clone())
                .map_err(|e| format!("{}: {e}", path.display()))?;
            out.insert(id, items);
        }
    }
    Ok(out)
}

fn score(args: &[String]) -> Result<String, String> {
    let pos = positional(args);
    let run = PathBuf::from(pos.first().ok_or(USAGE)?);
    let analysis = load_analysis(&run)?;
    let mut metrics = serde_json::Map::new();
    metrics.insert("counts".into(), json!(analysis.counts));
    let threshold: f64 = flag(args, "--threshold")
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.5);
    if let Some(g) = flag(args, "--gold") {
        let gold = gold_for(&run, Path::new(&g))?;
        let items: usize = gold.values().map(Vec::len).sum();
        let e = evaluate::extraction(&analysis, &gold, threshold);
        metrics.insert("gold_items".into(), json!(items));
        metrics.insert("gold_papers".into(), json!(gold.len()));
        metrics.insert("extraction".into(), json!(e));
    }
    if let Some(v) = flag(args, "--verdicts") {
        let verdicts: Vec<TagVerdict> =
            serde_json::from_value(read_json(Path::new(&v))?).map_err(|e| e.to_string())?;
        metrics.insert(
            "tag_precision".into(),
            json!(evaluate::tag_precision(&analysis, &verdicts)),
        );
    }
    if let (Some(r), Some(s)) = (flag(args, "--ratings"), flag(args, "--sheet")) {
        let ratings: Vec<Rating> =
            serde_json::from_value(read_json(Path::new(&r))?).map_err(|e| e.to_string())?;
        let sheet = read_json(Path::new(&s))?;
        let source_of: BTreeMap<String, String> = sheet["key"]
            .as_object()
            .into_iter()
            .flatten()
            .map(|(k, v)| (k.clone(), v["source"].as_str().unwrap_or("").to_owned()))
            .collect();
        metrics.insert(
            "ratings".into(),
            json!(evaluate::ratings(&ratings, &source_of)),
        );
    }
    if let Some(full) = flag(args, "--full") {
        let late = load_analysis(Path::new(&full))?;
        let early_ids: Vec<String> = analysis.papers.iter().map(|p| p.id.clone()).collect();
        let late_ids: Vec<String> = late
            .papers
            .iter()
            .map(|p| p.id.clone())
            .filter(|id| !early_ids.contains(id))
            .collect();
        let checks = evaluate::time_split(&analysis, &late, &late_ids);
        let closed = checks.iter().filter(|c| !c.addressed_by.is_empty()).count();
        metrics.insert("time_split".into(), json!({"later_papers": late_ids, "gaps": checks.len(), "addressed_later": closed, "checks": checks}));
    }
    let mut audits = serde_json::Map::new();
    if let Ok(a) = read_json(&run.join("audit.json")) {
        audits.insert("system".into(), a["counts"].clone());
    }
    for mode in ["closed", "context", "rag"] {
        if let Ok(b) = read_json(&run.join("baselines").join(format!("{mode}.json"))) {
            audits.insert(mode.into(), b["audit"]["counts"].clone());
        }
    }
    metrics.insert("audit".into(), json!(audits));
    write_json(&run.join("metrics.json"), &json!(metrics))?;
    Ok(serde_json::to_string_pretty(&json!(metrics)).unwrap_or_default())
}

/// The gaps of a baseline answer: its numbered items or headed blocks.
fn answer_gaps(answer: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for line in answer.lines() {
        let t = line.trim();
        let starts = t.starts_with("###")
            || t.starts_with("## ")
            || (t.chars().next().is_some_and(|c| c.is_ascii_digit())
                && t.chars().take(4).any(|c| c == '.' || c == ')'))
            || (t.starts_with("**") && out.is_empty());
        if starts {
            out.push(t.to_owned());
        } else if let Some(last) = out.last_mut()
            && !t.is_empty()
        {
            last.push('\n');
            last.push_str(t);
        }
    }
    out.retain(|g| g.split_whitespace().count() >= 8);
    out
}

fn sheet(args: &[String]) -> Result<String, String> {
    let runs = positional(args);
    let out = PathBuf::from(flag(args, "--out").ok_or(USAGE)?);
    let mut entries: Vec<(String, Value)> = Vec::new();
    for r in &runs {
        let run = PathBuf::from(r);
        let manifest = read_json(&run.join("run.json"))?;
        let topic = manifest["topic"].as_str().unwrap_or("").to_owned();
        let a = read_json(&run.join("analysis.json"))?;
        for rk in a["ranking"].as_array().into_iter().flatten() {
            let cid = rk["candidate"].as_str().unwrap_or("");
            if let Some(c) = a["candidates"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|c| c["id"] == cid)
            {
                let evidence: Vec<String> = c["evidence"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .take(6)
                    .map(|e| {
                        format!(
                            "{} ({}): \"{}\"",
                            e["paper"].as_str().unwrap_or(""),
                            e["section"].as_str().unwrap_or(""),
                            e["text"].as_str().unwrap_or("")
                        )
                    })
                    .collect();
                let text = format!(
                    "{}\n{}",
                    c["statement"].as_str().unwrap_or(""),
                    evidence.join("\n")
                );
                entries.push((
                    text,
                    json!({"source": "system", "topic": topic, "run": r, "ref": rk["gap"]}),
                ));
            }
        }
        for mode in ["closed", "context", "rag"] {
            if let Ok(b) = read_json(&run.join("baselines").join(format!("{mode}.json"))) {
                for (i, g) in answer_gaps(b["answer"].as_str().unwrap_or(""))
                    .into_iter()
                    .enumerate()
                {
                    entries.push((
                        g,
                        json!({"source": mode, "topic": topic, "run": r, "ref": i + 1}),
                    ));
                }
            }
        }
    }
    // a stable shuffle: order by a hash of the text, so the source cannot be read from the position
    let mut keyed: Vec<(String, String, Value)> = entries
        .into_iter()
        .map(|(t, k)| {
            let n = normalize(&t);
            let h = n.bytes().fold(1469598103934665603u64, |h, b| {
                (h ^ u64::from(b)).wrapping_mul(1099511628211)
            });
            (format!("{h:016x}"), t, k)
        })
        .collect();
    keyed.sort_by(|a, b| a.0.cmp(&b.0));
    let mut items = Vec::new();
    let mut key = serde_json::Map::new();
    for (i, (_, text, k)) in keyed.into_iter().enumerate() {
        let id = format!("R{:03}", i + 1);
        items.push(json!({"item": id, "topic": k["topic"], "text": text}));
        key.insert(id, k);
    }
    write_json(&out, &json!({"items": items, "key": key}))?;
    Ok(format!(
        "{} gaps on the sheet {}",
        items.len(),
        out.display()
    ))
}

/// Runs `args` (what follows `laris gap`).
pub fn main(started: &Started, args: &[String]) -> Result<String, String> {
    match args.first().map(String::as_str) {
        Some("run") => run(started, &args[1..]),
        Some("collect") => collect(started, &args[1..]),
        Some("score") => score(&args[1..]),
        Some("sheet") => sheet(&args[1..]),
        _ => Err(USAGE.into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numbered_gaps_are_split() {
        let a = "Intro line.\n1. **Robustness** is not studied on microcontrollers in any paper.\nMore text here.\n2. Another gap that has enough words to count as one.\n";
        let g = answer_gaps(a);
        assert_eq!(g.len(), 2);
        assert!(g[0].contains("More text here."));
    }

    #[test]
    fn flags_and_positionals() {
        let args: Vec<String> = ["dir", "--only", "P1,P2", "x"]
            .iter()
            .map(|s| (*s).to_owned())
            .collect();
        assert_eq!(flag(&args, "--only").as_deref(), Some("P1,P2"));
        assert_eq!(positional(&args), vec!["dir", "x"]);
    }
}
