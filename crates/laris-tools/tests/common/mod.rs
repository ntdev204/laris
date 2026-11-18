//! Shared rig: a project folder in a temporary place, with checkpoints, memory and skills beside it.
#![allow(dead_code, missing_docs)]

use laris_config::Settings;
use laris_tools::{Context, Registry};
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

pub struct Rig {
    pub base: PathBuf,
    pub project: PathBuf,
    pub registry: Registry,
}

pub fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-tools-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir.canonicalize().expect("canonical")
}

pub fn rig(name: &str) -> Rig {
    rig_with(name, |_| {})
}

pub fn rig_with(name: &str, change: impl FnOnce(&mut Settings)) -> Rig {
    let base = temp_dir(name);
    let project = base.join("project");
    std::fs::create_dir_all(&project).expect("project");
    let mut settings = Settings::default();
    change(&mut settings);
    let ctx = Context::new(&project, &settings)
        .expect("context")
        .with_checkpoints(base.join("checkpoints"))
        .with_memory_dir(base.join("memory"))
        .with_skill_dirs(vec![base.join("skills")]);
    Rig {
        base,
        project,
        registry: Registry::with_local_tools(ctx),
    }
}

pub fn args(value: Value) -> Map<String, Value> {
    value.as_object().expect("an object").clone()
}

impl Rig {
    pub fn call(&mut self, name: &str, arguments: Value) -> Value {
        self.registry.call(name, &args(arguments))
    }

    /// The result, which must be a success.
    pub fn ok(&mut self, name: &str, arguments: Value) -> Value {
        let result = self.call(name, arguments);
        assert!(result.get("error").is_none(), "{name} failed: {result}");
        result
    }

    /// The code of the error, which must be one.
    pub fn code(&mut self, name: &str, arguments: Value) -> String {
        let result = self.call(name, arguments);
        result["error"]["code"]
            .as_str()
            .unwrap_or_else(|| panic!("{name} did not fail: {result}"))
            .to_owned()
    }

    pub fn write_file(&self, relative: &str, content: &str) {
        let path = self.project.join(relative);
        std::fs::create_dir_all(path.parent().expect("parent")).expect("folders");
        std::fs::write(path, content).expect("file");
    }

    pub fn read_file(&self, relative: &str) -> String {
        std::fs::read_to_string(self.project.join(relative)).expect("file")
    }
}

pub fn exists(path: &Path) -> bool {
    path.symlink_metadata().is_ok()
}

pub fn marker() -> Value {
    json!(true)
}
