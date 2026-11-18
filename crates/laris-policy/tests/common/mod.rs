//! Shared rig: a project folder and a home in a temporary place, and an approver that answers from a script.
#![allow(dead_code, missing_docs)]

use laris_config::Settings;
use laris_config::settings::Permissions;
use laris_policy::{Answer, ApprovalRequest, Approver, Engine, ProjectState};
use laris_tools::Scope;
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

pub fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-policy-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir.canonicalize().expect("canonical")
}

pub fn args(value: Value) -> Map<String, Value> {
    value.as_object().expect("an object").clone()
}

pub struct Rig {
    pub base: PathBuf,
    pub project: PathBuf,
    pub home: PathBuf,
}

pub fn rig(name: &str) -> Rig {
    let base = temp_dir(name);
    let project = base.join("project");
    let home = base.join("home");
    std::fs::create_dir_all(&project).expect("project");
    std::fs::create_dir_all(&home).expect("home");
    Rig {
        base,
        project,
        home,
    }
}

impl Rig {
    pub fn scope(&self) -> Scope {
        Scope::new(&self.project, &[], &Settings::default().tools.denied_files).expect("scope")
    }

    pub fn settings_file(&self) -> PathBuf {
        self.home.join("settings.json")
    }

    pub fn engine_with(&self, permissions: Permissions, allow_bypass: bool) -> Engine {
        Engine::new(
            permissions,
            self.scope(),
            ProjectState::new(&self.home, &self.project),
            Some(self.settings_file()),
            allow_bypass,
        )
    }

    pub fn engine(&self) -> Engine {
        self.engine_with(Permissions::default(), false)
    }

    pub fn read(&self, relative: &str) -> String {
        std::fs::read_to_string(self.project.join(relative)).expect("file")
    }

    pub fn write_file(&self, relative: &str, content: &str) {
        let path = self.project.join(relative);
        std::fs::create_dir_all(path.parent().expect("parent")).expect("folders");
        std::fs::write(path, content).expect("file");
    }
}

pub fn permissions(allow: &[&str], ask: &[&str], deny: &[&str]) -> Permissions {
    let own = |rules: &[&str]| rules.iter().map(|r| (*r).to_owned()).collect();
    Permissions {
        allow: own(allow),
        ask: own(ask),
        deny: own(deny),
        ..Permissions::default()
    }
}

/// Answers from a script and keeps what it was asked.
#[derive(Clone)]
pub struct Scripted {
    answers: Arc<Mutex<Vec<Answer>>>,
    pub asked: Arc<Mutex<Vec<ApprovalRequest>>>,
}

impl Scripted {
    pub fn new(answers: Vec<Answer>) -> Self {
        Self {
            answers: Arc::new(Mutex::new(answers)),
            asked: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn count(&self) -> usize {
        self.asked.lock().expect("lock").len()
    }
}

impl Approver for Scripted {
    fn approve(&self, request: &ApprovalRequest) -> Answer {
        self.asked.lock().expect("lock").push(request.clone());
        let mut answers = self.answers.lock().expect("lock");
        if answers.is_empty() {
            Answer::Deny
        } else {
            answers.remove(0)
        }
    }
}

pub fn exists(path: &Path) -> bool {
    path.symlink_metadata().is_ok()
}
