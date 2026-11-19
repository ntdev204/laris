//! What every command does first: find the home, add what it lacks, read the settings, find the project (SR-C3).

use laris_config::home::{Created, Home, ProjectFolder};
use laris_config::layers::LoadOptions;
use laris_config::packaged::{ENV as PACKAGED_ENV, Packaged};
use laris_config::settings::Settings;
use std::path::{Path, PathBuf};

/// The client's starting point.
#[derive(Debug)]
pub struct Started {
    /// The global home.
    pub home: Home,
    /// What the home lacked and was added.
    pub created: Created,
    /// The resolved settings: environment over `settings.json` over the packaged defaults over the built-in ones.
    pub settings: Settings,
    /// The project folder.
    pub project: PathBuf,
    /// The environment the settings were resolved from.
    pub env: Vec<(String, String)>,
}

impl Started {
    /// The project's `./.laris/`.
    pub fn project_folder(&self) -> ProjectFolder {
        ProjectFolder::new(&self.project)
    }
}

/// Prepares the home and reads the settings. `exe` is the running executable (its folder may hold the packaged
/// `defaults.json`). Errors are texts for the user and name the file or variable at fault.
pub fn start(
    env: Vec<(String, String)>,
    cwd: &Path,
    exe: Option<&Path>,
) -> Result<Started, String> {
    let home = Home::from_env(&env).map_err(|e| e.to_string())?;
    let created = home.ensure().map_err(|e| e.to_string())?;
    let named = env
        .iter()
        .find(|(k, _)| k == PACKAGED_ENV)
        .map(|(_, v)| v.as_str());
    let packaged = Packaged::discover(named, exe);
    let settings = laris_config::load(&LoadOptions {
        settings_path: Some(&home.settings_path()),
        packaged: &packaged,
        env: &env,
    })
    .map_err(|e| e.to_string())?;
    let project = home.project_root(cwd);
    Ok(Started {
        home,
        created,
        settings,
        project,
        env,
    })
}
