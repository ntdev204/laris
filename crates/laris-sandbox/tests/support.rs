//! Shared helpers: a self-deleting temporary folder (no `tempfile` crate is approved).
#![allow(dead_code, missing_docs)]

use std::path::{Path, PathBuf};

pub struct Tmp(PathBuf);

impl Tmp {
    pub fn new(label: &str) -> Self {
        use std::sync::atomic::{AtomicU32, Ordering};
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-sandbox-{label}-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&dir).expect("temporary folder");
        Self(dir.canonicalize().expect("canonical"))
    }
    pub fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for Tmp {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.0).ok();
    }
}
