//! The knowledge tools (SR-H4, SR-H8, SR-H13): `ingest_document`, `search_corpus`, `write_vault_note` and
//! `propose_note`.
//!
//! * `ingest_document` reads a text, Markdown or PDF file (a scan by OCR, T261) of the project, cuts it into passages with exact character
//!   spans, keeps them in the project database and writes the document's Source note in the vault. The same file
//!   again replaces its passages and changes nothing in the note.
//! * `search_corpus` ranks the passages of every ingested document and the notes of the vault (never the proposals
//!   inbox) and returns hits `{source, rank, text, ...}`: exactly what the evidence gate matches a citation
//!   `[source #rank]` against. Its output is third-party content and is marked untrusted.
//! * `write_vault_note` writes a note of the schema with provenance; `propose_note` puts a suggestion in the inbox.
//!
//! Nothing here decides anything about the world: a document is read, cut, kept and found again.

use crate::args::{object_schema, opt_string, opt_u64, string};
use crate::context::Context;
use crate::error::ToolError;
use crate::ingest::{self, PdfLimits};
use crate::project_vault::{ProjectVault, VaultProblem};
use crate::registry::LocalTool;
use laris_retrieval::{
    Channel, GraphConfig, GraphRetriever, PassageIndex, PassageRecord, cite, fuse_ranked,
};
use laris_store::Store;
use laris_vault::Value as Prop;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::sync::Arc;

type Args = Map<String, Value>;

/// The vault and the database the knowledge tools work on.
pub struct Knowledge {
    /// The project vault.
    pub vault: ProjectVault,
    /// The project database (passages).
    pub store: Store,
}

fn problem(e: VaultProblem) -> ToolError {
    let code = match &e {
        VaultProblem::Conflict => "conflict",
        VaultProblem::Exists(_) => "exists",
        VaultProblem::Invalid(_) => "invalid_arguments",
        _ => "vault_error",
    };
    ToolError::new(code, e.to_string())
}

fn stored(e: laris_store::StoreError) -> ToolError {
    ToolError::new("store_error", format!("the project database failed: {e}"))
}

fn doc_id(origin: &str) -> String {
    let digest: String = Sha256::digest(origin.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    digest[..16].to_owned()
}

fn pdf_limits(ctx: &Context) -> PdfLimits {
    let bytes = usize::try_from(ctx.vault.ingest_max_bytes).unwrap_or(usize::MAX);
    PdfLimits {
        max_stream_bytes: bytes.saturating_mul(4),
        max_pages: 5_000,
    }
}

/// The tools, when the context has a vault and a database.
pub(crate) fn tools(ctx: &Arc<Context>) -> Vec<LocalTool> {
    if ctx.knowledge.is_none() {
        return Vec::new();
    }
    vec![
        ingest_tool(ctx),
        search_tool(ctx),
        note_tool(ctx),
        propose_tool(ctx),
    ]
}

fn ingest_tool(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "ingest_document",
        "Read a text, Markdown or PDF file of the project, keep its passages for search_corpus and write its \
         Source note in the vault. A scanned PDF is read by OCR when the programs are installed; `read_by` says how.",
        object_schema(
            json!({"path": {"type": "string"},
                   "domain": {"type": "string", "description": "Optional domain hub the Source note joins."}}),
            &["path"],
        ),
        true,
        false,
        move |args: &Args| {
            let Some(k) = &ctx.knowledge else {
                return Err(ToolError::new("no_vault", "this project has no vault"));
            };
            let path = ctx.scope.resolve(string(args, "path")?, false)?;
            if !path.is_file() {
                return Err(ToolError::new("not_found", "no such file"));
            }
            let origin = ctx.scope.display(&path);
            let (document, method) = ingest::read_document_with(
                &path,
                ctx.vault.ingest_max_bytes,
                &pdf_limits(&ctx),
                Some(&ctx.vault.ocr),
            )
            .map_err(|e| ToolError::new("cannot_ingest", e.to_string()))?;
            let max = usize::try_from(ctx.vault.passage_max_chars).unwrap_or(usize::MAX);
            let passages = ingest::split(&document.text, max);
            let rows: Vec<(usize, usize, String)> = passages
                .iter()
                .map(|p| (p.start, p.end, p.text.clone()))
                .collect();
            let id = doc_id(&origin);
            k.store
                .replace_document(&id, &origin, &document.title, &rows)
                .map_err(stored)?;
            let note = k
                .vault
                .source_note(
                    &document,
                    &origin,
                    passages.len(),
                    opt_string(args, "domain"),
                )
                .map_err(problem)?;
            Ok(json!({
                "title": document.title,
                "kind": document.kind.as_str(),
                "read_by": method.as_str(),
                "characters": document.text.chars().count(),
                "passages": passages.len(),
                "source_note": note.path,
                "note_status": format!("{:?}", note.status).to_lowercase(),
            }))
        },
    )
}

fn search_tool(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "search_corpus",
        "Search the ingested documents and the vault notes of this project. Each hit has a source and a rank: cite it \
         as [source #rank]. The proposals inbox is never searched.",
        object_schema(
            json!({"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1}}),
            &["query"],
        ),
        false,
        true,
        move |args: &Args| {
            let Some(k) = &ctx.knowledge else {
                return Err(ToolError::new("no_vault", "this project has no vault"));
            };
            let query = string(args, "query")?;
            let max = u64::from(ctx.vault.search_max_results);
            let top = usize::try_from(opt_u64(args, "top_k").unwrap_or(max).min(max)).unwrap_or(1);
            search(k, query, top)
        },
    )
}

/// Ranks passages and notes for `query` and shapes the hits.
pub(crate) fn search(k: &Knowledge, query: &str, top: usize) -> Result<Value, ToolError> {
    let rows = k.store.chunks().map_err(stored)?;
    let passages = PassageIndex::new(
        rows.iter()
            .map(|r| PassageRecord {
                id: r.chunk_id.clone(),
                source: r.title.clone(),
                start: usize::try_from(r.start).unwrap_or(0),
                end: usize::try_from(r.end).unwrap_or(0),
                text: r.text.clone(),
            })
            .collect(),
    );
    let by_passage = passages.search(query, top.saturating_mul(3));
    let index = k.vault.index().map_err(problem)?;
    let graph = GraphRetriever::new(&index, &[], GraphConfig::default());
    let notes: Vec<_> = graph
        .retrieve(query, top.saturating_mul(3))
        .into_iter()
        .filter(|r| {
            index
                .notes
                .get(&r.path)
                .is_some_and(|n| n.prop_list("type") != ["source"])
        })
        .collect();
    let cited = cite(&notes, &index, query);
    let fused = fuse_ranked(
        &[
            Channel {
                name: "passages".into(),
                weight: 1.0,
                qualified: true,
                items: by_passage
                    .iter()
                    .map(|h| format!("doc:{}", h.passage.id))
                    .collect(),
            },
            Channel {
                name: "notes".into(),
                weight: 1.0,
                qualified: true,
                items: notes.iter().map(|r| format!("note:{}", r.path)).collect(),
            },
        ],
        top,
    );
    let mut hits = Vec::new();
    for (i, f) in fused.iter().enumerate() {
        let rank = i + 1;
        if let Some(id) = f.id.strip_prefix("doc:") {
            let Some(row) = rows.iter().find(|r| r.chunk_id == id) else {
                continue;
            };
            hits.push(json!({
                "source": row.title, "rank": rank, "text": row.text, "kind": "passage",
                "path": row.source, "start": row.start, "end": row.end,
            }));
        } else if let Some(path) = f.id.strip_prefix("note:") {
            let Some(note) = index.notes.get(path) else {
                continue;
            };
            let text = cited
                .iter()
                .find(|c| c.result.path == path)
                .and_then(|c| c.span.as_ref().map(|s| s.snippet.clone()))
                .unwrap_or_else(|| note.body.chars().take(300).collect());
            hits.push(json!({
                "source": note.title, "rank": rank, "text": text, "kind": "note", "path": path,
            }));
        }
    }
    Ok(json!({
        "query": query,
        "hits": hits,
        "searched": {"passages": rows.len(), "notes": index.notes.len()},
    }))
}

fn note_tool(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "write_vault_note",
        "Write a note of the vault with its provenance: a type of the vault schema (analysis, decision, answer, \
         session, memory, claim ...), a title, the text and the titles of the notes it rests on. LARIS writes only \
         inside its own block; your text around it is never touched.",
        object_schema(
            json!({"kind": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"},
                   "sources": {"type": "array"}, "scope": {"type": "string"}, "session": {"type": "string"},
                   "trust": {"type": "string"}}),
            &["kind", "title", "body"],
        ),
        true,
        false,
        move |args: &Args| {
            let Some(k) = &ctx.knowledge else {
                return Err(ToolError::new("no_vault", "this project has no vault"));
            };
            let sources: Vec<String> = args
                .get("sources")
                .and_then(Value::as_array)
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str().map(str::to_owned))
                        .collect()
                })
                .unwrap_or_default();
            let mut extra = Vec::new();
            for key in ["scope", "session", "trust"] {
                if let Some(v) = opt_string(args, key) {
                    extra.push((key.to_owned(), Prop::Str(v.to_owned())));
                }
            }
            let written = k
                .vault
                .write_note(
                    string(args, "kind")?,
                    string(args, "title")?,
                    &(ctx.redact)(string(args, "body")?),
                    &extra,
                    "laris",
                    &sources,
                )
                .map_err(problem)?;
            Ok(
                json!({"path": written.path, "status": format!("{:?}", written.status).to_lowercase()}),
            )
        },
    )
}

fn propose_tool(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "propose_note",
        "Suggest a note without adding it to the vault: it goes to the proposals inbox, where a person accepts or \
         rejects it. The inbox is never searched.",
        object_schema(
            json!({"title": {"type": "string"}, "body": {"type": "string"},
                   "target_type": {"type": "string", "description": "The type the note would have."}}),
            &["title", "body", "target_type"],
        ),
        true,
        false,
        move |args: &Args| {
            let Some(k) = &ctx.knowledge else {
                return Err(ToolError::new("no_vault", "this project has no vault"));
            };
            let written = k
                .vault
                .propose(
                    string(args, "title")?,
                    &(ctx.redact)(string(args, "body")?),
                    "laris",
                    string(args, "target_type")?,
                )
                .map_err(problem)?;
            Ok(json!({"path": written.path, "status": "pending"}))
        },
    )
}
