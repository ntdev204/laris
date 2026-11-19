//! The credentials file (`~/.laris/credentials.json`): the API key and the server that accepted it.
//!
//! The key lives here and nowhere else on disk (the settings file refuses literal secrets). The file is created
//! private to the user from its first byte (mode 0600 on Unix; on Windows it inherits the user's profile
//! permissions) and replaced atomically, so a crash leaves the old file or the new one, never a half-written key.
//! The server is stored with the key so that a key accepted by one server is never sent to another.

use laris_config::settings::server_address;
use serde_json::{Value, json};
use std::fmt;
use std::io::Write;
use std::path::Path;

/// Larger files are refused.
const MAX_BYTES: u64 = 16 * 1024;

/// A saved key and the server that accepted it.
#[derive(Clone, PartialEq, Eq)]
pub struct Saved {
    /// The API key.
    pub api_key: String,
    /// The address of the server that accepted it, as written when it was saved.
    pub server: String,
}

impl fmt::Debug for Saved {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Saved")
            .field("api_key", &"***")
            .field("server", &self.server)
            .finish()
    }
}

impl Saved {
    /// Whether this key was accepted by `server` (compared as complete, case-insensitive addresses).
    pub fn is_for(&self, server: &str) -> bool {
        server_address(&self.server).eq_ignore_ascii_case(&server_address(server))
    }
}

/// Reads the file; a missing file is `None`. A file that is damaged or holds no key is an error, so that the
/// interface can say so and ask again instead of silently ignoring it.
pub fn read(path: &Path) -> Result<Option<Saved>, String> {
    let meta = match std::fs::metadata(path) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e.to_string()),
    };
    if meta.len() > MAX_BYTES {
        return Err(format!(
            "{} is larger than {MAX_BYTES} bytes",
            path.display()
        ));
    }
    #[cfg(unix)]
    tighten(path, &meta);
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let value: Value = serde_json::from_str(&text).map_err(|e| format!("invalid JSON: {e}"))?;
    let field = |name: &str| {
        value
            .get(name)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
    };
    match (field("apiKey"), field("server")) {
        (Some(api_key), Some(server)) => Ok(Some(Saved { api_key, server })),
        _ => Err("the file has no apiKey and server".to_owned()),
    }
}

/// A file that others can read is made private again (a key copied or restored with loose permissions).
#[cfg(unix)]
fn tighten(path: &Path, meta: &std::fs::Metadata) {
    use std::os::unix::fs::PermissionsExt;
    if meta.permissions().mode() & 0o077 != 0 {
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
    }
}

/// Writes the file atomically with private permissions.
pub fn write(path: &Path, saved: &Saved) -> std::io::Result<()> {
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        std::fs::create_dir_all(dir)?;
    }
    let mut text = serde_json::to_string_pretty(&json!({
        "apiKey": saved.api_key,
        "server": saved.server,
    }))?;
    text.push('\n');
    let temporary = path.with_extension("json.tmp");
    // A leftover from a crash is replaced, never reused: it may have looser permissions.
    let _ = std::fs::remove_file(&temporary);
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temporary)?;
    let written = file
        .write_all(text.as_bytes())
        .and_then(|()| file.sync_all());
    drop(file);
    if let Err(e) = written {
        let _ = std::fs::remove_file(&temporary);
        return Err(e);
    }
    std::fs::rename(&temporary, path).inspect_err(|_| {
        let _ = std::fs::remove_file(&temporary);
    })
}

/// Deletes the file; `false` when there was none.
pub fn remove(path: &Path) -> std::io::Result<bool> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e),
    }
}
