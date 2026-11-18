//! Checkpoints: the previous content of every file a tool changes, saved before the change, so `/rewind` can
//! restore it. One folder per session, an index of JSON lines and one blob per entry, newest last.

use crate::error::ToolError;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// What a rewind did to one file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rewound {
    /// The file.
    pub path: PathBuf,
    /// `restored`, `removed` or `skipped`.
    pub status: &'static str,
    /// Why a file was skipped.
    pub why: Option<&'static str>,
}

impl Rewound {
    /// As the JSON the model or the interface shows; `display` turns a path into what a person reads.
    pub fn to_value(&self, display: impl Fn(&Path) -> String) -> Value {
        let mut value = json!({"path": display(&self.path), "status": self.status});
        if let (Some(why), Some(map)) = (self.why, value.as_object_mut()) {
            map.insert("why".to_owned(), json!(why));
        }
        value
    }
}

#[derive(Clone, Debug)]
struct Entry {
    seq: u64,
    path: PathBuf,
    existed: bool,
    tool: String,
}

impl Entry {
    fn to_value(&self) -> Value {
        json!({"seq": self.seq, "path": self.path.to_string_lossy(), "existed": self.existed, "tool": self.tool})
    }

    fn from_value(value: &Value) -> Option<Self> {
        Some(Self {
            seq: value.get("seq")?.as_u64()?,
            path: PathBuf::from(value.get("path")?.as_str()?),
            existed: value.get("existed")?.as_bool()?,
            tool: value.get("tool")?.as_str()?.to_owned(),
        })
    }
}

/// The checkpoint folder of one session.
#[derive(Debug)]
pub struct Checkpoints {
    folder: PathBuf,
    keep: usize,
    lock: Mutex<()>,
}

impl Checkpoints {
    /// Checkpoints kept in `folder`, at most `keep` of them (the oldest are dropped).
    pub fn new(folder: impl Into<PathBuf>, keep: usize) -> Self {
        Self {
            folder: folder.into(),
            keep: keep.max(1),
            lock: Mutex::new(()),
        }
    }

    fn index(&self) -> PathBuf {
        self.folder.join("index.jsonl")
    }

    fn blob(&self, seq: u64) -> PathBuf {
        self.folder.join(format!("{seq}.blob"))
    }

    fn entries(&self) -> Vec<Entry> {
        std::fs::read_to_string(self.index())
            .unwrap_or_default()
            .lines()
            .filter_map(|line| serde_json::from_str::<Value>(line).ok())
            .filter_map(|value| Entry::from_value(&value))
            .collect()
    }

    fn write(&self, entries: &[Entry]) -> Result<(), ToolError> {
        let io = |e: std::io::Error| {
            ToolError::io("checkpoint_failed", "cannot write the checkpoint index", &e)
        };
        std::fs::create_dir_all(&self.folder).map_err(io)?;
        let text: String = entries
            .iter()
            .map(|e| format!("{}\n", e.to_value()))
            .collect();
        let temp = self.folder.join("index.jsonl.tmp");
        std::fs::write(&temp, text).map_err(io)?;
        std::fs::rename(&temp, self.index()).map_err(io)
    }

    /// Saves the present content of `path` (or the fact that it does not exist) before `tool` changes it.
    pub fn record(&self, path: &Path, tool: &str) -> Result<u64, ToolError> {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let mut entries = self.entries();
        let seq = entries.last().map_or(1, |e| e.seq + 1);
        let existed = path.is_file();
        std::fs::create_dir_all(&self.folder).map_err(|e| {
            ToolError::io(
                "checkpoint_failed",
                "cannot create the checkpoint folder",
                &e,
            )
        })?;
        if existed {
            std::fs::copy(path, self.blob(seq)).map_err(|e| {
                ToolError::io("checkpoint_failed", "cannot save the checkpoint", &e)
            })?;
        }
        entries.push(Entry {
            seq,
            path: path.to_path_buf(),
            existed,
            tool: tool.to_owned(),
        });
        let drop = entries.len().saturating_sub(self.keep);
        for old in entries.drain(..drop) {
            std::fs::remove_file(self.blob(old.seq)).ok();
        }
        self.write(&entries)?;
        Ok(seq)
    }

    /// Takes back the checkpoint `seq` after the change it guarded failed, so a failed edit leaves no trace.
    pub fn discard(&self, seq: u64) {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let mut entries = self.entries();
        entries.retain(|e| e.seq != seq);
        std::fs::remove_file(self.blob(seq)).ok();
        self.write(&entries).ok();
    }

    /// The edits saved, oldest first, as `(path, tool)`.
    pub fn list(&self) -> Vec<(PathBuf, String)> {
        self.entries()
            .into_iter()
            .map(|e| (e.path, e.tool))
            .collect()
    }

    /// Undoes the last `steps` edits (all when `None`), newest first. A path `allowed` refuses is skipped and
    /// reported, never written.
    pub fn rewind(
        &self,
        steps: Option<usize>,
        allowed: impl Fn(&Path) -> bool,
    ) -> Result<Vec<Rewound>, ToolError> {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let entries = self.entries();
        let count = steps.map_or(entries.len(), |n| n.min(entries.len()));
        let keep = entries.len() - count;
        let mut done = Vec::new();
        for entry in entries[keep..].iter().rev() {
            let blob = self.blob(entry.seq);
            let path = entry.path.clone();
            let outcome = if !allowed(&path) {
                Rewound {
                    path,
                    status: "skipped",
                    why: Some("not allowed"),
                }
            } else if entry.existed && blob.is_file() {
                match restore(&blob, &path) {
                    Ok(()) => Rewound {
                        path,
                        status: "restored",
                        why: None,
                    },
                    Err(_) => Rewound {
                        path,
                        status: "skipped",
                        why: Some("cannot write"),
                    },
                }
            } else if !entry.existed {
                match std::fs::remove_file(&path) {
                    Ok(()) => Rewound {
                        path,
                        status: "removed",
                        why: None,
                    },
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => Rewound {
                        path,
                        status: "removed",
                        why: None,
                    },
                    Err(_) => Rewound {
                        path,
                        status: "skipped",
                        why: Some("cannot remove"),
                    },
                }
            } else {
                Rewound {
                    path,
                    status: "skipped",
                    why: Some("checkpoint missing"),
                }
            };
            std::fs::remove_file(&blob).ok();
            done.push(outcome);
        }
        self.write(&entries[..keep])?;
        Ok(done)
    }
}

fn restore(blob: &Path, path: &Path) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut temp = path.as_os_str().to_owned();
    temp.push(".laris-rewind");
    let temp = PathBuf::from(temp);
    std::fs::copy(blob, &temp)?;
    std::fs::rename(&temp, path)
}
