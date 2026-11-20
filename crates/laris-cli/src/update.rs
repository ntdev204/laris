//! Automatic updates of the client (T251, SR-C6). Always on, and quiet: while the interface runs, a background thread
//! asks the release address for the latest signed checksum list, and when a newer version is there it downloads the
//! archive for this machine, checks it and replaces the program on disk. The running session is not touched: it
//! is told that a version is installed, and `/restart` starts the program again with the session resumed.
//!
//! What makes it safe is the same as for the installers: nothing is used before the signature of `SHA256SUMS` is
//! checked with the release key the client was built with (ECDSA P-256 over SHA-256, the signature `openssl dgst
//! -sign` writes), and the archive must match its line of that signed list. The list also carries the latest version
//! (the file `VERSION`), so a downgrade cannot be made by serving an old, validly signed list under `latest`: only
//! a strictly newer version is ever installed.

use laris_config::settings::Update;
use laris_model_client::{BodyStream, HttpRequest, Method, ReqwestTransport, Transport};
use ring::{digest, signature};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

/// Largest file taken from the release address: an archive.
const MAX_ARCHIVE: usize = 256 * 1024 * 1024;
/// Largest list or small file taken from it.
const MAX_SMALL: usize = 64 * 1024;
/// Longest wait for a connection.
const CONNECT: Duration = Duration::from_secs(15);

/// Gets the bytes of a URL; `Err` is a short reason. A test supplies its own.
pub trait Fetch {
    /// The body of `url`, at most `limit` bytes.
    fn get(&self, url: &str, limit: usize) -> Result<Vec<u8>, String>;
}

/// The real fetcher: HTTPS with the system's trust, redirects followed.
pub struct HttpFetch {
    transport: ReqwestTransport,
}

impl HttpFetch {
    /// A fetcher; `Err` when the HTTP client cannot be built.
    pub fn new() -> Result<Self, String> {
        ReqwestTransport::for_downloads(CONNECT, true)
            .map(|transport| Self { transport })
            .map_err(|e| e.to_string())
    }
}

impl Fetch for HttpFetch {
    fn get(&self, url: &str, limit: usize) -> Result<Vec<u8>, String> {
        let request = HttpRequest {
            method: Method::Get,
            url: url.to_owned(),
            headers: Vec::new(),
            body: None,
        };
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())?;
        runtime.block_on(async {
            let (head, mut body) =
                tokio::time::timeout(Duration::from_secs(60), self.transport.send(&request))
                    .await
                    .map_err(|_| "no answer".to_owned())?
                    .map_err(|e| format!("{e:?}"))?;
            if head.status != 200 {
                return Err(format!("status {}", head.status));
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = tokio::time::timeout(Duration::from_secs(60), body.chunk())
                .await
                .map_err(|_| "the download stalled".to_owned())?
                .map_err(|e| format!("{e:?}"))?
            {
                if bytes.len() + chunk.len() > limit {
                    return Err("the file is larger than allowed".to_owned());
                }
                bytes.extend_from_slice(&chunk);
            }
            Ok(bytes)
        })
    }
}

/// What the check found.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Found {
    /// Nothing newer than the running version.
    Current,
    /// A newer release: its version and the signed SHA-256 of the archive for this machine.
    Newer {
        /// The version, `1.2.3`.
        version: String,
        /// Lowercase hex SHA-256 of this machine's archive.
        archive_sha256: String,
    },
}

/// `major.minor.patch` of a version text (a pre-release or build suffix is ignored); `None` if it is not one.
pub fn parse_version(text: &str) -> Option<(u64, u64, u64)> {
    let core = text.trim().split(['-', '+']).next()?;
    let mut parts = core.split('.');
    let mut next = || parts.next()?.parse::<u64>().ok();
    let version = (next()?, next()?, next()?);
    parts.next().is_none().then_some(version)
}

/// The release target of this machine, as the archives are named.
pub fn this_target() -> Option<&'static str> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("linux", "x86_64") => Some("x86_64-unknown-linux-musl"),
        ("linux", "aarch64") => Some("aarch64-unknown-linux-musl"),
        ("macos", "x86_64") => Some("x86_64-apple-darwin"),
        ("macos", "aarch64") => Some("aarch64-apple-darwin"),
        ("windows", "x86_64") => Some("x86_64-pc-windows-msvc"),
        _ => None,
    }
}

/// The archive's file name for `target`.
pub fn archive_name(target: &str) -> String {
    if target.contains("windows") {
        format!("laris-{target}.zip")
    } else {
        format!("laris-{target}.tar.gz")
    }
}

fn base64_value(c: u8) -> Option<u8> {
    match c {
        b'A'..=b'Z' => Some(c - b'A'),
        b'a'..=b'z' => Some(c - b'a' + 26),
        b'0'..=b'9' => Some(c - b'0' + 52),
        b'+' => Some(62),
        b'/' => Some(63),
        _ => None,
    }
}

/// The uncompressed P-256 point inside a PEM (or bare base64) `SubjectPublicKeyInfo`.
fn public_point(pem: &str) -> Option<Vec<u8>> {
    let body: String = pem
        .lines()
        .map(str::trim)
        .filter(|l| !l.starts_with("-----") && !l.is_empty())
        .collect();
    let mut bits = 0u32;
    let mut have = 0;
    let mut der = Vec::new();
    for c in body.bytes().take_while(|&c| c != b'=') {
        bits = (bits << 6) | u32::from(base64_value(c)?);
        have += 6;
        if have >= 8 {
            have -= 8;
            der.push(u8::try_from((bits >> have) & 0xff).ok()?);
        }
    }
    // 91 bytes: the fixed header of an EC P-256 key (26 bytes) and the 65-byte point that starts with 4
    (der.len() == 91 && der[26] == 4).then(|| der[26..].to_vec())
}

/// Whether `signature` (DER, as `openssl dgst -sign` writes it) is a valid signature of `data` by the key `pem`.
pub fn signature_is_valid(pem: &str, data: &[u8], signed: &[u8]) -> bool {
    let Some(point) = public_point(pem) else {
        return false;
    };
    signature::UnparsedPublicKey::new(&signature::ECDSA_P256_SHA256_ASN1, point)
        .verify(data, signed)
        .is_ok()
}

fn sha256_hex(bytes: &[u8]) -> String {
    digest::digest(&digest::SHA256, bytes)
        .as_ref()
        .iter()
        .fold(String::new(), |mut out, b| {
            out.push_str(&format!("{b:02x}"));
            out
        })
}

fn listed<'a>(sums: &'a str, name: &str) -> Option<&'a str> {
    sums.lines().find_map(|line| {
        let (hash, file) = line.split_once("  ")?;
        (file == name && hash.len() == 64).then_some(hash)
    })
}

/// Asks the release address for the latest signed list and says whether it holds a version newer than `current`.
pub fn check(
    fetch: &dyn Fetch,
    source: &Update,
    current: &str,
    target: &str,
) -> Result<Found, String> {
    let base = format!("{}/latest", source.url.trim_end_matches('/'));
    let sums = fetch.get(&format!("{base}/SHA256SUMS"), MAX_SMALL)?;
    let signed = fetch.get(&format!("{base}/SHA256SUMS.sig"), MAX_SMALL)?;
    if !signature_is_valid(&source.signature_verifier, &sums, &signed) {
        return Err("the signature of the release list is not valid".to_owned());
    }
    let sums = String::from_utf8(sums).map_err(|_| "the release list is not text".to_owned())?;
    let version_hash =
        listed(&sums, "VERSION").ok_or("the signed list names no version".to_owned())?;
    let version = fetch.get(&format!("{base}/VERSION"), 64)?;
    if sha256_hex(&version) != version_hash {
        return Err("the version file does not match the signed list".to_owned());
    }
    let version = String::from_utf8_lossy(&version).trim().to_owned();
    let (Some(latest), Some(running)) = (parse_version(&version), parse_version(current)) else {
        return Err(format!("not a version: {version}"));
    };
    if latest <= running {
        return Ok(Found::Current);
    }
    let archive = archive_name(target);
    let archive_sha256 = listed(&sums, &archive)
        .ok_or_else(|| format!("{archive} is not in the signed list"))?
        .to_owned();
    Ok(Found::Newer {
        version,
        archive_sha256,
    })
}

/// Downloads the archive of `version` and checks it against the signed checksum.
pub fn download(
    fetch: &dyn Fetch,
    source: &Update,
    version: &str,
    target: &str,
    archive_sha256: &str,
) -> Result<Vec<u8>, String> {
    if version.contains(['/', '\\']) || version.contains("..") {
        return Err("bad version".to_owned());
    }
    let url = format!(
        "{}/{version}/{}",
        source.url.trim_end_matches('/'),
        archive_name(target)
    );
    let bytes = fetch.get(&url, MAX_ARCHIVE)?;
    if sha256_hex(&bytes) != archive_sha256 {
        return Err("the archive does not match the signed list".to_owned());
    }
    Ok(bytes)
}

/// Unpacks the checked archive into `work` and returns the program inside. The system's `tar` reads both formats
/// (`bsdtar` on Windows reads the zip); the archive must hold exactly the program.
fn unpack(archive: &Path, work: &Path, target: &str) -> Result<PathBuf, String> {
    let name = if target.contains("windows") {
        "laris.exe"
    } else {
        "laris"
    };
    let listing = Command::new("tar")
        .arg("-tf")
        .arg(archive)
        .output()
        .map_err(|e| format!("cannot run tar: {e}"))?;
    let names = String::from_utf8_lossy(&listing.stdout);
    if !listing.status.success() || names.trim() != name {
        return Err("the archive holds unexpected files".to_owned());
    }
    let out = work.join("unpacked");
    std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let status = Command::new("tar")
        .arg("-xf")
        .arg(archive)
        .arg("-C")
        .arg(&out)
        .status()
        .map_err(|e| format!("cannot run tar: {e}"))?;
    let program = out.join(name);
    if !status.success() || !program.is_file() {
        return Err("cannot unpack the archive".to_owned());
    }
    Ok(program)
}

/// Puts `new` in place of the program at `exe`. On Unix a rename replaces the running file; on Windows a running
/// program cannot be overwritten but can be renamed, so the old one is moved aside first.
fn replace(new: &Path, exe: &Path) -> Result<(), String> {
    let dir = exe.parent().ok_or("the program has no folder")?;
    let staged = dir.join(".laris.new");
    std::fs::copy(new, &staged).map_err(|e| format!("cannot write in {}: {e}", dir.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&staged, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| e.to_string())?;
    }
    let put = || -> std::io::Result<()> {
        #[cfg(windows)]
        {
            let aside = dir.join("laris.old");
            let _ = std::fs::remove_file(&aside);
            std::fs::rename(exe, &aside)?;
            if let Err(e) = std::fs::rename(&staged, exe) {
                let _ = std::fs::rename(&aside, exe);
                return Err(e);
            }
            Ok(())
        }
        #[cfg(not(windows))]
        std::fs::rename(&staged, exe)
    };
    put().map_err(|e| {
        let _ = std::fs::remove_file(&staged);
        format!("cannot replace {}: {e}", exe.display())
    })
}

/// Downloads, checks, unpacks and installs `version`, replacing the program at `exe`.
pub fn install(
    fetch: &dyn Fetch,
    source: &Update,
    found: &Found,
    target: &str,
    exe: &Path,
    scratch: &Path,
) -> Result<String, String> {
    let Found::Newer {
        version,
        archive_sha256,
    } = found
    else {
        return Err("nothing to install".to_owned());
    };
    let bytes = download(fetch, source, version, target, archive_sha256)?;
    let work = scratch.join(format!("update-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&work);
    std::fs::create_dir_all(&work).map_err(|e| e.to_string())?;
    let result = (|| {
        let archive = work.join(archive_name(target));
        std::fs::write(&archive, &bytes).map_err(|e| e.to_string())?;
        let program = unpack(&archive, &work, target)?;
        replace(&program, exe)
    })();
    let _ = std::fs::remove_dir_all(&work);
    result.map(|()| version.clone())
}

/// One round: check, and install a newer version. `Ok(Some(version))` when a new version is now on disk.
pub fn run_once(
    fetch: &dyn Fetch,
    source: &Update,
    current: &str,
    exe: &Path,
    scratch: &Path,
) -> Result<Option<String>, String> {
    let target = this_target().ok_or("no release for this machine")?;
    let found = check(fetch, source, current, target)?;
    match found {
        Found::Current => Ok(None),
        Found::Newer { .. } => install(fetch, source, &found, target, exe, scratch).map(Some),
    }
}

/// Whether there is a source to update from: a release address and its key.
pub fn configured(source: &Update) -> bool {
    !source.url.is_empty() && public_point(&source.signature_verifier).is_some()
}

/// Runs on its own thread for the life of the interface: a round now and then every `intervalMinutes`. `notify` is
/// told the version each time a new one has been installed (once per version). A failed round is silent: the next
/// one tries again.
pub fn watch(
    source: Update,
    current: String,
    exe: PathBuf,
    scratch: PathBuf,
    notify: impl Fn(&str) + Send + 'static,
) {
    if !configured(&source) {
        return;
    }
    let Ok(fetch) = HttpFetch::new() else {
        return;
    };
    let mut installed: Option<String> = None;
    loop {
        if let Ok(Some(version)) = run_once(&fetch, &source, &current, &exe, &scratch)
            && installed.as_deref() != Some(&version)
        {
            notify(&version);
            installed = Some(version);
        }
        std::thread::sleep(Duration::from_secs(source.interval_minutes.max(1) * 60));
    }
}

/// Starts [`watch`] on a thread of its own, for this program's version.
pub fn spawn_watch(
    source: Update,
    exe: PathBuf,
    scratch: PathBuf,
    notify: Box<dyn Fn(&str) + Send>,
) {
    if !configured(&source) {
        return;
    }
    let _ = std::thread::Builder::new()
        .name("update".to_owned())
        .spawn(move || {
            watch(
                source,
                env!("CARGO_PKG_VERSION").to_owned(),
                exe,
                scratch,
                notify,
            );
        });
}
