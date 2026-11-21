//! Document ingestion (SR-H13): a text, Markdown or PDF file becomes a [`Document`] and its passages.
//!
//! * [`read_document`] reads one file with a size limit and says what it is. Text is read as lossy UTF-8 with
//!   universal newlines (the same as the vault does), so the character offsets of a passage are the same
//!   everywhere. A PDF goes through [`pdf`], which reads the text layer and nothing else.
//! * [`passages::split`] cuts the text into passages with exact character spans.
//!
//! A PDF the built-in reader cannot use (a scan, or fonts it cannot decode) goes to [`ocr`], which runs the programs
//! named in `vault.ocr` (T261). When they are missing or read nothing, the error says so; nothing is guessed.

pub mod inflate;
pub mod ocr;
pub mod passages;
pub mod pdf;

use sha2::{Digest, Sha256};
use std::path::Path;

pub use ocr::Method;
pub use passages::{Passage, split};
pub use pdf::{PdfError, PdfLimits};

use laris_config::settings::Ocr;

/// What a file is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// Plain text.
    Text,
    /// Markdown.
    Markdown,
    /// PDF with a text layer.
    Pdf,
}

impl Kind {
    /// The word written in a Source note.
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Markdown => "markdown",
            Kind::Pdf => "pdf",
        }
    }
}

/// A document ready to be cut into passages.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    /// What it was.
    pub kind: Kind,
    /// A title: a Markdown title, or the file name without its extension.
    pub title: String,
    /// The text. For a PDF, the text of the pages joined by a blank line.
    pub text: String,
    /// SHA-256 of the file's bytes.
    pub sha256: String,
}

/// A file that cannot be ingested. The message is for the person and the model.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum IngestError {
    /// The extension is not one of `txt`, `md`, `markdown`, `pdf`.
    #[error("cannot ingest this kind of file ({0}); use .txt, .md or .pdf")]
    Unsupported(String),
    /// The file cannot be read.
    #[error("cannot read the file: {0}")]
    Unreadable(String),
    /// The file is larger than the limit.
    #[error("the file is larger than {0} bytes")]
    TooLarge(u64),
    /// A PDF problem.
    #[error(transparent)]
    Pdf(#[from] PdfError),
    /// The built-in reader and the external readers all failed.
    #[error("{builtin}; the external readers also failed: {external}")]
    ReaderFailed {
        /// What the built-in reader said.
        builtin: String,
        /// What the external readers said.
        external: String,
    },
    /// The file holds no text.
    #[error("the file holds no text")]
    Empty,
}

/// Reads `path` with at most `max_bytes` bytes.
pub fn read_document(
    path: &Path,
    max_bytes: u64,
    limits: &PdfLimits,
) -> Result<Document, IngestError> {
    read_document_with(path, max_bytes, limits, None).map(|(d, _)| d)
}

/// Like [`read_document`], with the external PDF readers `ocr` and the method that gave the text.
pub fn read_document_with(
    path: &Path,
    max_bytes: u64,
    limits: &PdfLimits,
    ocr: Option<&Ocr>,
) -> Result<(Document, Method), IngestError> {
    let extension = path
        .extension()
        .and_then(|e| e.to_str())
        .map(str::to_lowercase)
        .unwrap_or_default();
    let kind = match extension.as_str() {
        "txt" | "text" => Kind::Text,
        "md" | "markdown" => Kind::Markdown,
        "pdf" => Kind::Pdf,
        other => return Err(IngestError::Unsupported(other.to_owned())),
    };
    let meta =
        std::fs::metadata(path).map_err(|e| IngestError::Unreadable(e.kind().to_string()))?;
    if meta.len() > max_bytes {
        return Err(IngestError::TooLarge(max_bytes));
    }
    let bytes = std::fs::read(path).map_err(|e| IngestError::Unreadable(e.kind().to_string()))?;
    document_from_with(kind, path, &bytes, limits, ocr)
}

/// A document from bytes already read.
pub fn document_from(
    kind: Kind,
    path: &Path,
    bytes: &[u8],
    limits: &PdfLimits,
) -> Result<Document, IngestError> {
    document_from_with(kind, path, bytes, limits, None).map(|(d, _)| d)
}

/// Like [`document_from`]; a PDF the built-in reader cannot use goes to the external readers when `ocr` is given.
pub fn document_from_with(
    kind: Kind,
    path: &Path,
    bytes: &[u8],
    limits: &PdfLimits,
    ocr: Option<&Ocr>,
) -> Result<(Document, Method), IngestError> {
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("document")
        .to_owned();
    let sha256: String = Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let mut method = Method::TextLayer;
    let (text, title) = match kind {
        Kind::Pdf => {
            let builtin = pdf::extract(bytes, limits).map(|p| p.text());
            match (builtin, ocr) {
                (Ok(text), _) if ocr::readable(&text) => (text, stem),
                (Ok(text), None) => (text, stem),
                (Err(e), None) => return Err(e.into()),
                (built, Some(cfg)) => {
                    let said = match &built {
                        Ok(_) => "the built-in reader found only unreadable text".to_owned(),
                        Err(e) => e.to_string(),
                    };
                    match ocr::read(bytes, cfg) {
                        Ok((text, how)) => {
                            method = how;
                            (text, stem)
                        }
                        Err(external) => {
                            return Err(IngestError::ReaderFailed {
                                builtin: said,
                                external,
                            });
                        }
                    }
                }
            }
        }
        Kind::Text | Kind::Markdown => {
            let raw = String::from_utf8_lossy(bytes)
                .replace("\r\n", "\n")
                .replace('\r', "\n");
            let title = if kind == Kind::Markdown {
                markdown_title(&raw).unwrap_or(stem)
            } else {
                stem
            };
            (raw, title)
        }
    };
    if text.trim().is_empty() {
        return Err(IngestError::Empty);
    }
    Ok((
        Document {
            kind,
            title,
            text,
            sha256,
        },
        method,
    ))
}

/// The `title` of the front matter, or the first level-one heading.
fn markdown_title(text: &str) -> Option<String> {
    let mut lines = text.lines();
    if lines.clone().next() == Some("---") {
        lines.next();
        for line in lines.by_ref() {
            if line == "---" {
                break;
            }
            if let Some(v) = line.strip_prefix("title:") {
                let v = v.trim().trim_matches(['"', '\'']).trim();
                if !v.is_empty() {
                    return Some(v.to_owned());
                }
            }
        }
    }
    text.lines()
        .find_map(|l| l.strip_prefix("# "))
        .map(|t| t.trim().to_owned())
        .filter(|t| !t.is_empty())
}
