//! `cargo xtask dist`: release packaging of the client (T159, SR-C6).
//!
//! Subcommands, in the order a release uses them:
//! - `keygen --out DIR` makes the release signing key pair (ECDSA P-256; the private key never goes into Git).
//! - `package --target T --bin FILE --out DIR` makes `laris-T.tar.gz` (`.zip` for Windows) holding only `laris`.
//! - `manifest --dir DIR` writes `SHA256SUMS` over the archives and `size-report.md`.
//! - `sign --dir DIR` signs `SHA256SUMS` with the key named by `LARIS_RELEASE_KEY` (a file path).
//! - `scripts --dir DIR --url URL --pubkey FILE` renders `install.sh`, `install.ps1` and the npm wrapper with the
//!   release address and the public key; nothing is hardcoded in the templates.
//! - `verify --dir DIR --pubkey FILE` checks the signature and every checksum, as the installers do.
//!
//! Signing uses `openssl` (already on the machine; ADR-021 section 4 addendum): `dgst -sha256` with an ECDSA P-256
//! key. The same signature is checked by `openssl` in `install.sh`, by .NET in `install.ps1` and by Node's crypto in
//! the npm wrapper.

use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

/// Release targets and the platform names the installers map to them.
pub const TARGETS: [&str; 5] = [
    "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc",
];

const URL_PLACEHOLDER: &str = "__LARIS_RELEASE_URL__";
const KEY_PLACEHOLDER: &str = "__LARIS_RELEASE_PUBKEY__";
const VERSION_PLACEHOLDER: &str = "__LARIS_VERSION__";

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn required(args: &[String], name: &str) -> Result<String, String> {
    flag(args, name).ok_or_else(|| format!("missing {name}"))
}

/// Archive file name of a target.
pub fn archive_name(target: &str) -> String {
    if target.contains("windows") {
        format!("laris-{target}.zip")
    } else {
        format!("laris-{target}.tar.gz")
    }
}

fn binary_name(target: &str) -> &'static str {
    if target.contains("windows") {
        "laris.exe"
    } else {
        "laris"
    }
}

/// SHA-256 of a file as lowercase hex.
pub fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    Ok(sha256_bytes(&bytes))
}

fn sha256_bytes(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut out, byte| {
            out.push_str(&format!("{byte:02x}"));
            out
        })
}

fn run(command: &mut Command, what: &str) -> Result<(), String> {
    let output = command
        .output()
        .map_err(|e| format!("{what}: cannot start: {e}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "{what} failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ))
    }
}

fn workspace_version(root: &Path) -> Result<String, String> {
    let text = fs::read_to_string(root.join("Cargo.toml")).map_err(|e| e.to_string())?;
    let in_package = text
        .split("[workspace.package]")
        .nth(1)
        .ok_or("no [workspace.package]")?;
    in_package
        .lines()
        .find_map(|l| {
            let l = l.trim();
            l.strip_prefix("version = \"")
                .and_then(|v| v.strip_suffix('"'))
        })
        .map(str::to_owned)
        .ok_or_else(|| "no workspace version".to_owned())
}

fn keygen(args: &[String]) -> Result<String, String> {
    let out = PathBuf::from(required(args, "--out")?);
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let private = out.join("release.key");
    let public = out.join("release.pub");
    if private.exists() {
        return Err(format!(
            "{} exists; refusing to replace it",
            private.display()
        ));
    }
    run(
        Command::new("openssl")
            .args([
                "ecparam",
                "-name",
                "prime256v1",
                "-genkey",
                "-noout",
                "-out",
            ])
            .arg(&private),
        "openssl ecparam",
    )?;
    run(
        Command::new("openssl")
            .args(["ec", "-pubout", "-in"])
            .arg(&private)
            .arg("-out")
            .arg(&public),
        "openssl ec",
    )?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&private, fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
    }
    Ok(format!(
        "private key {} (keep it outside Git); public key {}",
        private.display(),
        public.display()
    ))
}

fn package(args: &[String]) -> Result<String, String> {
    let target = required(args, "--target")?;
    if !TARGETS.contains(&target.as_str()) {
        return Err(format!(
            "unknown target {target}; known: {}",
            TARGETS.join(", ")
        ));
    }
    let bin = PathBuf::from(required(args, "--bin")?);
    let out = PathBuf::from(required(args, "--out")?);
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let size = fs::metadata(&bin)
        .map_err(|e| format!("cannot read {}: {e}", bin.display()))?
        .len();
    // Stage the binary under its release name so the archive holds exactly one member.
    let stage = out.join(format!(".stage-{target}"));
    let _ = fs::remove_dir_all(&stage);
    fs::create_dir_all(&stage).map_err(|e| e.to_string())?;
    fs::copy(&bin, stage.join(binary_name(&target))).map_err(|e| e.to_string())?;
    let archive = out.join(archive_name(&target));
    let _ = fs::remove_file(&archive);
    let member = binary_name(&target);
    let made = if target.contains("windows") {
        // bsdtar (Windows, macOS) writes zip with -a; `zip` is the fallback where tar is GNU.
        run(
            Command::new("tar")
                .args(["-a", "-c", "-f"])
                .arg(&archive)
                .arg("-C")
                .arg(&stage)
                .arg(member),
            "tar zip",
        )
        .or_else(|_| {
            run(
                Command::new("zip")
                    .arg("-q")
                    .arg(&archive)
                    .arg(member)
                    .current_dir(&stage),
                "zip",
            )
        })
    } else {
        run(
            Command::new("tar")
                .args(["-c", "-z", "-f"])
                .arg(&archive)
                .arg("-C")
                .arg(&stage)
                .arg(member),
            "tar",
        )
    };
    let _ = fs::remove_dir_all(&stage);
    made?;
    fs::write(out.join(format!("laris-{target}.size")), size.to_string())
        .map_err(|e| e.to_string())?;
    Ok(format!("{} ({size} bytes of binary)", archive.display()))
}

fn archives(dir: &Path) -> Result<Vec<PathBuf>, String> {
    let mut found: Vec<PathBuf> = TARGETS
        .iter()
        .map(|t| dir.join(archive_name(t)))
        .filter(|p| p.exists())
        .collect();
    found.sort();
    if found.is_empty() {
        Err(format!("no release archives in {}", dir.display()))
    } else {
        Ok(found)
    }
}

fn file_name(path: &Path) -> String {
    path.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// `SHA256SUMS` text for the archives in `dir` (the format `sha256sum -c` reads).
pub fn manifest_text(dir: &Path) -> Result<String, String> {
    let mut text = String::new();
    for archive in archives(dir)? {
        text.push_str(&format!(
            "{}  {}\n",
            sha256_file(&archive)?,
            file_name(&archive)
        ));
    }
    Ok(text)
}

fn human(bytes: u64) -> String {
    format!("{:.2} MiB", bytes as f64 / 1_048_576.0)
}

/// The size report: binary and archive size per target.
pub fn size_report(dir: &Path) -> Result<String, String> {
    let mut report = String::from(
        "# Size report\n\nSize of the `laris` binary (strip, LTO) and of its archive per target.\n\n| Target | Binary | Archive |\n|---|---|---|\n",
    );
    let mut archive_total = 0u64;
    for archive in archives(dir)? {
        let name = file_name(&archive);
        let target = name
            .trim_start_matches("laris-")
            .trim_end_matches(".tar.gz")
            .trim_end_matches(".zip");
        let archive_size = fs::metadata(&archive).map_err(|e| e.to_string())?.len();
        archive_total += archive_size;
        let binary = fs::read_to_string(dir.join(format!("laris-{target}.size")))
            .ok()
            .and_then(|s| s.trim().parse::<u64>().ok())
            .map_or_else(
                || "not recorded".to_owned(),
                |b| format!("{} ({b} bytes)", human(b)),
            );
        report.push_str(&format!(
            "| {target} | {binary} | {} ({archive_size} bytes) |\n",
            human(archive_size)
        ));
    }
    report.push_str(&format!(
        "\nAll archives together: {}.\n",
        human(archive_total)
    ));
    Ok(report)
}

fn manifest(args: &[String]) -> Result<String, String> {
    let dir = PathBuf::from(required(args, "--dir")?);
    let text = manifest_text(&dir)?;
    fs::write(dir.join("SHA256SUMS"), &text).map_err(|e| e.to_string())?;
    let _ = fs::remove_file(dir.join("SHA256SUMS.sig"));
    fs::write(dir.join("size-report.md"), size_report(&dir)?).map_err(|e| e.to_string())?;
    Ok(format!(
        "{} archives listed in SHA256SUMS; size-report.md written",
        text.lines().count()
    ))
}

fn sign(args: &[String]) -> Result<String, String> {
    let dir = PathBuf::from(required(args, "--dir")?);
    let key = std::env::var("LARIS_RELEASE_KEY")
        .map_err(|_| "LARIS_RELEASE_KEY must name the private key file".to_owned())?;
    run(
        Command::new("openssl")
            .args(["dgst", "-sha256", "-sign"])
            .arg(&key)
            .arg("-out")
            .arg(dir.join("SHA256SUMS.sig"))
            .arg(dir.join("SHA256SUMS")),
        "openssl dgst -sign",
    )?;
    Ok("SHA256SUMS.sig written".to_owned())
}

/// Checks `SHA256SUMS.sig` against the public key and every checksum against its archive.
pub fn verify_release(dir: &Path, pubkey: &Path) -> Result<usize, String> {
    run(
        Command::new("openssl")
            .args(["dgst", "-sha256", "-verify"])
            .arg(pubkey)
            .arg("-signature")
            .arg(dir.join("SHA256SUMS.sig"))
            .arg(dir.join("SHA256SUMS")),
        "signature check",
    )
    .map_err(|e| format!("signature refused: {e}"))?;
    let text = fs::read_to_string(dir.join("SHA256SUMS")).map_err(|e| e.to_string())?;
    let mut checked = 0;
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let (hash, name) = line
            .split_once("  ")
            .ok_or_else(|| format!("bad manifest line: {line}"))?;
        if name.contains('/') || name.contains('\\') || name.starts_with('.') {
            return Err(format!("unsafe name in manifest: {name}"));
        }
        if sha256_file(&dir.join(name))? != hash {
            return Err(format!("checksum mismatch: {name}"));
        }
        checked += 1;
    }
    Ok(checked)
}

fn verify(args: &[String]) -> Result<String, String> {
    let dir = PathBuf::from(required(args, "--dir")?);
    let pubkey = PathBuf::from(required(args, "--pubkey")?);
    let checked = verify_release(&dir, &pubkey)?;
    Ok(format!(
        "signature good; {checked} archives match their checksums"
    ))
}

fn fill(template: &str, url: &str, pubkey: &str, version: &str, json: bool) -> String {
    let pubkey = pubkey.trim();
    let pubkey = if json {
        pubkey.replace('\n', "\\n")
    } else {
        pubkey.to_owned()
    };
    template
        .replace(URL_PLACEHOLDER, url)
        .replace(KEY_PLACEHOLDER, &pubkey)
        .replace(VERSION_PLACEHOLDER, version)
}

fn scripts(root: &Path, args: &[String]) -> Result<String, String> {
    let dir = PathBuf::from(required(args, "--dir")?);
    let url = flag(args, "--url")
        .or_else(|| std::env::var("LARIS_RELEASE_URL").ok())
        .ok_or("the release address: --url or LARIS_RELEASE_URL")?;
    if !url.starts_with("https://") {
        return Err("the release address must start with https://".to_owned());
    }
    let url = url.trim_end_matches('/').to_owned();
    let pubkey = fs::read_to_string(required(args, "--pubkey")?).map_err(|e| e.to_string())?;
    if !pubkey.contains("BEGIN PUBLIC KEY") {
        return Err("--pubkey must be a PEM public key".to_owned());
    }
    let version = workspace_version(root)?;
    let source = root.join("distribution");
    let mut written = Vec::new();
    let files = [
        ("install.sh", "install.sh"),
        ("install.ps1", "install.ps1"),
        ("npm/package.json", "npm/package.json"),
        ("npm/config.json", "npm/config.json"),
        ("npm/install.js", "npm/install.js"),
        ("npm/bin/laris.js", "npm/bin/laris.js"),
        ("npm/check/verify.js", "npm/check/verify.js"),
        ("npm/README.md", "npm/README.md"),
    ];
    for (from, to) in files {
        let template =
            fs::read_to_string(source.join(from)).map_err(|e| format!("template {from}: {e}"))?;
        let target = dir.join(to);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::write(
            &target,
            fill(&template, &url, &pubkey, &version, to.ends_with(".json")),
        )
        .map_err(|e| e.to_string())?;
        written.push(to);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        for exec in ["install.sh", "npm/bin/laris.js"] {
            fs::set_permissions(dir.join(exec), fs::Permissions::from_mode(0o755))
                .map_err(|e| e.to_string())?;
        }
    }
    Ok(format!("rendered {} for {url}", written.join(", ")))
}

/// Entry point of `cargo xtask dist`.
pub fn run_dist(root: &Path, args: &[String]) -> ExitCode {
    let rest = args.get(1..).unwrap_or_default();
    let result = match args.first().map(String::as_str) {
        Some("keygen") => keygen(rest),
        Some("package") => package(rest),
        Some("manifest") => manifest(rest),
        Some("sign") => sign(rest),
        Some("scripts") => scripts(root, rest),
        Some("verify") => verify(rest),
        _ => Err("usage: cargo xtask dist <keygen --out DIR | package --target T --bin FILE --out DIR | manifest --dir DIR | sign --dir DIR | scripts --dir DIR --url URL --pubkey FILE | verify --dir DIR --pubkey FILE>".to_owned()),
    };
    match result {
        Ok(message) => {
            println!("{message}");
            ExitCode::SUCCESS
        }
        Err(message) => {
            eprintln!("dist: {message}");
            ExitCode::from(1)
        }
    }
}
