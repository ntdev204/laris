//! The global home (`~/.laris`) and the project folder rules (SR-C3).
//!
//! The home holds, and only this build creates: `settings.json`, `credentials.json` (written by the client when a
//! key is accepted), `commands/`, `skills/`, `projects/` (one folder per project, with the SQLite file and the
//! folder's `state.json`), `LARIS.md` (optional, the user's own) and `.venv/` (built by the sandbox on first use).
//! [`Home::ensure`] only adds what is missing: it never rewrites, moves or deletes an existing entry, so a home
//! that holds other files (generation 1 left `config.yaml` and `runtime/` there) is left exactly as it was.
//!
//! A project's `./.laris/` holds only [`PROJECT_ENTRIES`]; anything else is reported by [`ProjectFolder::stray`]
//! and never read. Settings in a project folder are ignored by design (a cloned repository must not change policy).
//!
//! Locating the home reads names the caller passes in; this module never reads the process environment.

use std::fmt;
use std::path::{Path, PathBuf};

/// Environment variable that names the home folder; it wins over the user's home directory.
pub const HOME_ENV: &str = "LARIS_HOME";
/// Name of the Laris folder, in the user's home directory and in a project.
pub const DIR_NAME: &str = ".laris";
/// The settings file of the home.
pub const SETTINGS_FILE: &str = "settings.json";
/// The credentials file of the home.
pub const CREDENTIALS_FILE: &str = "credentials.json";
/// The user's own instructions, in the home and in a project.
pub const INSTRUCTIONS_FILE: &str = "LARIS.md";
/// Folders created in the home.
pub const HOME_DIRS: [&str; 3] = ["commands", "skills", "projects"];
/// The only entries of a project's `./.laris/`.
pub const PROJECT_ENTRIES: [&str; 4] = [INSTRUCTIONS_FILE, "skills", "commands", "memory"];

/// Why the home cannot be located or prepared.
#[derive(Debug)]
pub enum HomeError {
    /// Neither `LARIS_HOME` nor a user home directory is set.
    NoHome,
    /// `LARIS_HOME` is not an absolute path.
    NotAbsolute(String),
    /// An entry that must be a folder is something else.
    NotAFolder(PathBuf),
    /// A folder or file could not be created.
    Io {
        /// What was being created.
        path: PathBuf,
        /// The cause.
        source: std::io::Error,
    },
    /// A name outside [`PROJECT_ENTRIES`] was asked of a project folder.
    NotAProjectEntry(String),
}

impl fmt::Display for HomeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoHome => write!(
                f,
                "cannot find the home folder: set {HOME_ENV} or the user's home directory"
            ),
            Self::NotAbsolute(v) => write!(f, "{HOME_ENV} must be an absolute path, not {v:?}"),
            Self::NotAFolder(p) => write!(f, "{} exists and is not a folder", p.display()),
            Self::Io { path, source } => write!(f, "cannot create {}: {source}", path.display()),
            Self::NotAProjectEntry(n) => write!(
                f,
                "{n:?} is not a project entry (a project's {DIR_NAME} holds only {})",
                PROJECT_ENTRIES.join(", ")
            ),
        }
    }
}

impl std::error::Error for HomeError {}

fn value<'a>(env: &'a [(String, String)], name: &str) -> Option<&'a str> {
    env.iter()
        .find(|(k, _)| k == name)
        .map(|(_, v)| v.as_str())
        .filter(|v| !v.trim().is_empty())
}

/// Where the home is: `LARIS_HOME` if set (it must be absolute), else `.laris` in the user's home directory
/// (`HOME`, or `USERPROFILE` on Windows).
pub fn locate(env: &[(String, String)]) -> Result<PathBuf, HomeError> {
    if let Some(named) = value(env, HOME_ENV) {
        let path = PathBuf::from(named);
        return if path.is_absolute() {
            Ok(path)
        } else {
            Err(HomeError::NotAbsolute(named.to_owned()))
        };
    }
    let user = value(env, "HOME")
        .or_else(|| value(env, "USERPROFILE"))
        .ok_or(HomeError::NoHome)?;
    Ok(PathBuf::from(user).join(DIR_NAME))
}

/// What [`Home::ensure`] added.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Created {
    /// Folders that did not exist.
    pub folders: Vec<PathBuf>,
    /// Files that did not exist.
    pub files: Vec<PathBuf>,
}

impl Created {
    /// Whether nothing had to be added.
    pub fn is_empty(&self) -> bool {
        self.folders.is_empty() && self.files.is_empty()
    }
}

/// The global home folder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Home {
    root: PathBuf,
}

impl Home {
    /// The home at `root`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    /// The home named by the environment ([`locate`]).
    pub fn from_env(env: &[(String, String)]) -> Result<Self, HomeError> {
        locate(env).map(Self::new)
    }

    /// The folder.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// `settings.json`.
    pub fn settings_path(&self) -> PathBuf {
        self.root.join(SETTINGS_FILE)
    }

    /// `credentials.json`.
    pub fn credentials_path(&self) -> PathBuf {
        self.root.join(CREDENTIALS_FILE)
    }

    /// The user's own `LARIS.md`.
    pub fn instructions_path(&self) -> PathBuf {
        self.root.join(INSTRUCTIONS_FILE)
    }

    /// `commands/`.
    pub fn commands_dir(&self) -> PathBuf {
        self.root.join("commands")
    }

    /// `skills/`.
    pub fn skills_dir(&self) -> PathBuf {
        self.root.join("skills")
    }

    /// `projects/`.
    pub fn projects_dir(&self) -> PathBuf {
        self.root.join("projects")
    }

    /// Whether `path` is this home folder (after resolving links), so that it is not taken for a project's own
    /// `.laris`.
    pub fn is_home_folder(&self, path: &Path) -> bool {
        match (
            std::fs::canonicalize(&self.root),
            std::fs::canonicalize(path),
        ) {
            (Ok(a), Ok(b)) => a == b,
            _ => self.root == path,
        }
    }

    /// Adds what is missing: the folder (private to the user on Unix), the [`HOME_DIRS`], and an empty
    /// `settings.json`. Existing entries are not opened for writing, so nothing a user or an older generation put
    /// there changes.
    pub fn ensure(&self) -> Result<Created, HomeError> {
        let mut created = Created::default();
        make_dir(&self.root, true, &mut created)?;
        for name in HOME_DIRS {
            make_dir(&self.root.join(name), false, &mut created)?;
        }
        let settings = self.settings_path();
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&settings)
        {
            Ok(mut file) => {
                use std::io::Write;
                file.write_all(b"{}\n").map_err(|source| HomeError::Io {
                    path: settings.clone(),
                    source,
                })?;
                created.files.push(settings);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(source) => {
                return Err(HomeError::Io {
                    path: settings,
                    source,
                });
            }
        }
        Ok(created)
    }

    /// The project folder that holds `cwd`: the nearest folder, from `cwd` upwards, that has a `.laris` folder of
    /// its own (never this home) or a `.git` entry; `cwd` itself when there is none.
    pub fn project_root(&self, cwd: &Path) -> PathBuf {
        for dir in cwd.ancestors() {
            let dot = dir.join(DIR_NAME);
            if (dot.is_dir() && !self.is_home_folder(&dot)) || dir.join(".git").exists() {
                return dir.to_path_buf();
            }
        }
        cwd.to_path_buf()
    }
}

fn make_dir(path: &Path, private: bool, created: &mut Created) -> Result<(), HomeError> {
    match std::fs::metadata(path) {
        Ok(meta) if meta.is_dir() => return Ok(()),
        Ok(_) => return Err(HomeError::NotAFolder(path.to_path_buf())),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(source) => {
            return Err(HomeError::Io {
                path: path.to_path_buf(),
                source,
            });
        }
    }
    let io = |source| HomeError::Io {
        path: path.to_path_buf(),
        source,
    };
    // `create_dir_all` makes missing parents too (`LARIS_HOME` may name a nested path); only the last is ours.
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(io)?;
    }
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    if private {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    #[cfg(not(unix))]
    let _ = private;
    match builder.create(path) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => return Ok(()),
        Err(e) => return Err(io(e)),
    }
    created.folders.push(path.to_path_buf());
    Ok(())
}

/// A project's `./.laris/` folder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectFolder {
    dot: PathBuf,
}

impl ProjectFolder {
    /// The folder of the project at `project_root`.
    pub fn new(project_root: &Path) -> Self {
        Self {
            dot: project_root.join(DIR_NAME),
        }
    }

    /// The `.laris` folder.
    pub fn path(&self) -> &Path {
        &self.dot
    }

    /// The path of an allowed entry; `None` for any other name.
    pub fn entry(&self, name: &str) -> Option<PathBuf> {
        PROJECT_ENTRIES.contains(&name).then(|| self.dot.join(name))
    }

    /// Creates the folder of an allowed entry (`skills`, `commands`, `memory`), and `.laris` itself. Any other name,
    /// including `LARIS.md` (a file the user writes) and `settings.json`, is refused.
    pub fn create_dir(&self, name: &str) -> Result<PathBuf, HomeError> {
        if name == INSTRUCTIONS_FILE || !PROJECT_ENTRIES.contains(&name) {
            return Err(HomeError::NotAProjectEntry(name.to_owned()));
        }
        let path = self.dot.join(name);
        std::fs::create_dir_all(&path).map_err(|source| HomeError::Io {
            path: path.clone(),
            source,
        })?;
        Ok(path)
    }

    /// Names in `.laris` that are not [`PROJECT_ENTRIES`], sorted. They are ignored, never read as settings.
    pub fn stray(&self) -> Vec<String> {
        let Ok(entries) = std::fs::read_dir(&self.dot) else {
            return Vec::new();
        };
        let mut names: Vec<String> = entries
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| !PROJECT_ENTRIES.contains(&n.as_str()))
            .collect();
        names.sort();
        names
    }
}
