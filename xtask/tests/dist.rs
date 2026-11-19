//! T159: the release path end to end with a fake binary: package, manifest, sign, render the installers, install
//! from a local mirror, and refuse every tampered release. Needs `openssl`, `tar`, `curl`, `sh` (and `node` for the
//! npm wrapper); a missing tool fails the test rather than skipping it.
#![cfg(unix)]

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicUsize, Ordering};

static COUNTER: AtomicUsize = AtomicUsize::new(0);

fn xtask(args: &[&str], key: Option<&Path>) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_xtask"));
    command.arg("dist").args(args);
    if let Some(key) = key {
        command.env("LARIS_RELEASE_KEY", key);
    }
    command.output().expect("xtask runs")
}

fn ok(output: &Output) {
    assert!(
        output.status.success(),
        "stdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "laris-dist-{name}-{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("scratch");
    dir
}

fn p(path: &Path) -> &str {
    path.to_str().expect("utf-8 path")
}

/// A signed release in `<root>/mirror/latest`, rendered installers in `<root>/rendered`.
struct Release {
    root: PathBuf,
    key: PathBuf,
    public: PathBuf,
}

impl Release {
    fn latest(&self) -> PathBuf {
        self.root.join("mirror/latest")
    }
    fn mirror_url(&self) -> String {
        format!("file://{}", self.root.join("mirror").display())
    }
    fn rendered(&self) -> PathBuf {
        self.root.join("rendered")
    }
}

fn keys(root: &Path, name: &str) -> (PathBuf, PathBuf) {
    let dir = root.join(name);
    ok(&xtask(&["keygen", "--out", p(&dir)], None));
    (dir.join("release.key"), dir.join("release.pub"))
}

fn release(name: &str) -> Release {
    let root = scratch(name);
    let (key, public) = keys(&root, "keys");
    let binary = root.join("laris");
    fs::write(&binary, "#!/bin/sh\necho \"laris 2.0.0-test $*\"\n").expect("fake binary");
    let latest = root.join("mirror/latest");
    for target in [
        "x86_64-unknown-linux-musl",
        "aarch64-unknown-linux-musl",
        "x86_64-apple-darwin",
        "aarch64-apple-darwin",
    ] {
        ok(&xtask(
            &[
                "package",
                "--target",
                target,
                "--bin",
                p(&binary),
                "--out",
                p(&latest),
            ],
            None,
        ));
    }
    ok(&xtask(&["manifest", "--dir", p(&latest)], None));
    ok(&xtask(&["sign", "--dir", p(&latest)], Some(&key)));
    let rendered = root.join("rendered");
    ok(&xtask(
        &[
            "scripts",
            "--dir",
            p(&rendered),
            "--url",
            "https://releases.example.test/laris",
            "--pubkey",
            p(&public),
        ],
        None,
    ));
    Release { root, key, public }
}

fn install(release: &Release) -> (Output, PathBuf) {
    let target = release.root.join("bin");
    let output = Command::new("sh")
        .arg(release.rendered().join("install.sh"))
        .env("LARIS_RELEASE_URL", release.mirror_url())
        .env("LARIS_INSTALL_DIR", &target)
        .env("HOME", &release.root)
        .output()
        .expect("sh runs");
    (output, target)
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn refused(release: &Release, reason: &str) {
    let (output, target) = install(release);
    assert!(!output.status.success(), "a bad release was installed");
    assert!(
        stderr(&output).contains(reason),
        "stderr: {}",
        stderr(&output)
    );
    assert!(!target.join("laris").exists(), "a binary was left behind");
}

fn flip_a_byte(path: &Path) {
    let mut bytes = fs::read(path).expect("read");
    let last = bytes.len() - 1;
    bytes[last] ^= 0x01;
    fs::write(path, bytes).expect("write");
}

fn archive(release: &Release) -> PathBuf {
    release
        .latest()
        .join("laris-x86_64-unknown-linux-musl.tar.gz")
}

#[test]
fn a_good_release_installs_and_starts() {
    let release = release("good");
    let (output, target) = install(&release);
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let run = Command::new(target.join("laris"))
        .arg("--version")
        .output()
        .expect("runs");
    assert!(String::from_utf8_lossy(&run.stdout).contains("laris 2.0.0-test"));
    // The installed file is the packaged one, executable, and no temporary file is left.
    assert!(!target.join(".laris.new").exists());
}

#[test]
fn verify_accepts_a_good_release_and_refuses_a_changed_one() {
    let release = release("verify");
    ok(&xtask(
        &[
            "verify",
            "--dir",
            p(&release.latest()),
            "--pubkey",
            p(&release.public),
        ],
        None,
    ));
    flip_a_byte(&archive(&release));
    let output = xtask(
        &[
            "verify",
            "--dir",
            p(&release.latest()),
            "--pubkey",
            p(&release.public),
        ],
        None,
    );
    assert!(!output.status.success());
    assert!(stderr(&output).contains("checksum mismatch"));
}

#[test]
fn a_tampered_archive_is_refused() {
    let release = release("tampered-archive");
    flip_a_byte(&archive(&release));
    refused(&release, "checksum");
}

#[test]
fn a_tampered_manifest_is_refused() {
    let release = release("tampered-manifest");
    // The attacker swaps the archive and rewrites the checksum list to match, without the key.
    flip_a_byte(&archive(&release));
    ok(&xtask(&["manifest", "--dir", p(&release.latest())], None));
    // `manifest` removes the old signature; put a stale one back to model an attacker reusing it.
    let stale = release.root.join("stale.sig");
    ok(&xtask(
        &["sign", "--dir", p(&release.latest())],
        Some(&release.key),
    ));
    fs::rename(release.latest().join("SHA256SUMS.sig"), &stale).expect("keep signature");
    flip_a_byte(&archive(&release));
    ok(&xtask(&["manifest", "--dir", p(&release.latest())], None));
    fs::copy(&stale, release.latest().join("SHA256SUMS.sig")).expect("stale signature");
    refused(&release, "signature");
}

#[test]
fn a_tampered_signature_is_refused() {
    let release = release("tampered-signature");
    flip_a_byte(&release.latest().join("SHA256SUMS.sig"));
    refused(&release, "signature");
}

#[test]
fn a_release_signed_with_another_key_is_refused() {
    let release = release("other-key");
    let (other, _) = keys(&release.root, "attacker");
    ok(&xtask(
        &["sign", "--dir", p(&release.latest())],
        Some(&other),
    ));
    refused(&release, "signature");
}

#[test]
fn an_archive_missing_from_the_signed_list_is_refused() {
    let release = release("unlisted");
    let sums = release.latest().join("SHA256SUMS");
    let kept: String = fs::read_to_string(&sums)
        .expect("sums")
        .lines()
        .filter(|l| !l.contains("x86_64-unknown-linux-musl"))
        .map(|l| format!("{l}\n"))
        .collect();
    fs::write(&sums, kept).expect("write");
    ok(&xtask(
        &["sign", "--dir", p(&release.latest())],
        Some(&release.key),
    ));
    refused(&release, "not in the signed list");
}

#[test]
fn a_signed_archive_with_extra_files_is_refused() {
    let release = release("extra-member");
    let stage = release.root.join("stage");
    fs::create_dir_all(&stage).expect("stage");
    fs::write(stage.join("laris"), "#!/bin/sh\n").expect("write");
    fs::write(stage.join("extra"), "x").expect("write");
    let status = Command::new("tar")
        .args([
            "-czf",
            p(&archive(&release)),
            "-C",
            p(&stage),
            "laris",
            "extra",
        ])
        .status()
        .expect("tar");
    assert!(status.success());
    ok(&xtask(&["manifest", "--dir", p(&release.latest())], None));
    ok(&xtask(
        &["sign", "--dir", p(&release.latest())],
        Some(&release.key),
    ));
    refused(&release, "unexpected files");
}

#[test]
fn the_installer_needs_a_rendered_https_address() {
    let release = release("address");
    let output = Command::new("sh")
        .arg(release.rendered().join("install.sh"))
        .env("LARIS_RELEASE_URL", "http://plain.example.test")
        .env("LARIS_INSTALL_DIR", release.root.join("bin"))
        .env("HOME", &release.root)
        .output()
        .expect("sh runs");
    assert!(!output.status.success());
    assert!(stderr(&output).contains("https://"));
    let template = Command::new("sh")
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../distribution/install.sh"))
        .env_remove("LARIS_RELEASE_URL")
        .env("HOME", &release.root)
        .output()
        .expect("sh runs");
    assert!(stderr(&template).contains("not rendered"));
    let refused_url = xtask(
        &[
            "scripts",
            "--dir",
            p(&release.root.join("x")),
            "--url",
            "http://plain.example.test",
            "--pubkey",
            p(&release.public),
        ],
        None,
    );
    assert!(!refused_url.status.success());
}

#[test]
fn the_size_report_and_manifest_list_every_archive() {
    let release = release("report");
    let sums = fs::read_to_string(release.latest().join("SHA256SUMS")).expect("sums");
    assert_eq!(sums.lines().count(), 4);
    assert!(sums.lines().all(|l| l.len() > 66 && l.contains("  laris-")));
    let report = fs::read_to_string(release.latest().join("size-report.md")).expect("report");
    assert!(report.contains("| aarch64-apple-darwin |"));
    assert!(report.contains("MiB"));
    assert!(report.contains("All archives together"));
}

fn npm_install(release: &Release, version: &str) -> (Output, PathBuf) {
    let package = release.rendered().join("npm");
    let output = Command::new("node")
        .arg(package.join("install.js"))
        .env("LARIS_RELEASE_URL", release.mirror_url())
        .env("LARIS_VERSION", version)
        .output()
        .expect("node runs");
    (output, package)
}

#[test]
fn the_npm_wrapper_installs_a_good_release_and_launches_it() {
    let release = release("npm-good");
    let (output, package) = npm_install(&release, "latest");
    assert!(output.status.success(), "stderr: {}", stderr(&output));
    let run = Command::new("node")
        .arg(package.join("bin/laris.js"))
        .args(["--version"])
        .output()
        .expect("runs");
    assert!(
        String::from_utf8_lossy(&run.stdout).contains("laris 2.0.0-test"),
        "{run:?}"
    );
    assert!(run.status.success());
}

#[test]
fn the_npm_wrapper_refuses_tampered_releases() {
    for (name, tamper) in [("archive", 0), ("signature", 1)] {
        let release = release(&format!("npm-bad-{name}"));
        let file = if tamper == 0 {
            // The wrapper maps this machine to its own target; damage every archive.
            for entry in fs::read_dir(release.latest()).expect("dir").flatten() {
                if entry.path().to_string_lossy().ends_with(".tar.gz") {
                    flip_a_byte(&entry.path());
                }
            }
            None
        } else {
            Some(release.latest().join("SHA256SUMS.sig"))
        };
        if let Some(file) = file {
            flip_a_byte(&file);
        }
        let (output, package) = npm_install(&release, "latest");
        assert!(!output.status.success(), "{name}: installed a bad release");
        assert!(
            stderr(&output).contains("nothing was installed"),
            "{}",
            stderr(&output)
        );
        assert!(!package.join("vendor").exists());
    }
}

#[test]
fn rendered_files_carry_the_key_and_address_and_no_placeholder() {
    let release = release("rendered");
    let key = fs::read_to_string(&release.public).expect("key");
    let body = key.lines().nth(1).expect("key body");
    for file in [
        "install.sh",
        "install.ps1",
        "npm/config.json",
        "npm/package.json",
    ] {
        let text = fs::read_to_string(release.rendered().join(file)).expect("rendered");
        assert!(!text.contains("__LARIS_"), "{file} still has a placeholder");
    }
    let sh = fs::read_to_string(release.rendered().join("install.sh")).expect("sh");
    assert!(sh.contains(body) && sh.contains("https://releases.example.test/laris"));
    let config = fs::read_to_string(release.rendered().join("npm/config.json")).expect("json");
    let parsed: serde_json::Value = serde_json::from_str(&config).expect("valid JSON");
    assert_eq!(parsed["releaseUrl"], "https://releases.example.test/laris");
    assert!(
        parsed["publicKey"]
            .as_str()
            .expect("key")
            .contains("BEGIN PUBLIC KEY")
    );
}
