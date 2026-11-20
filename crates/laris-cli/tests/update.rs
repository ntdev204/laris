//! Automatic updates (T251, SR-C6): the release list is trusted only when its signature is valid, only a newer
//! version is installed, and the program is replaced by the archive that matches the signed checksum.

#![allow(missing_docs)]

use laris_cli::update::{Fetch, Found, archive_name, check, install, parse_version, run_once};
use laris_config::settings::Update;
use ring::rand::SystemRandom;
use ring::signature::{ECDSA_P256_SHA256_ASN1_SIGNING, EcdsaKeyPair, KeyPair};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

const TARGET: &str = "x86_64-unknown-linux-musl";

fn base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let n = chunk.iter().fold(0u32, |n, b| (n << 8) | u32::from(*b)) << (8 * (3 - chunk.len()));
        for i in 0..=chunk.len() {
            out.push(TABLE[((n >> (18 - 6 * i)) & 63) as usize] as char);
        }
    }
    while !out.len().is_multiple_of(4) {
        out.push('=');
    }
    out
}

fn hex(bytes: &[u8]) -> String {
    ring::digest::digest(&ring::digest::SHA256, bytes)
        .as_ref()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

struct Release {
    pair: EcdsaKeyPair,
    verifier: String,
}

impl Release {
    fn new() -> Self {
        let rng = SystemRandom::new();
        let pkcs8 =
            EcdsaKeyPair::generate_pkcs8(&ECDSA_P256_SHA256_ASN1_SIGNING, &rng).expect("key");
        let pair = EcdsaKeyPair::from_pkcs8(&ECDSA_P256_SHA256_ASN1_SIGNING, pkcs8.as_ref(), &rng)
            .expect("pair");
        // the SubjectPublicKeyInfo of a P-256 key: a fixed header, then the point
        let mut spki = vec![
            0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01, 0x06,
            0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00,
        ];
        spki.extend_from_slice(pair.public_key().as_ref());
        let verifier = format!(
            "-----BEGIN PUBLIC KEY-----\n{}\n-----END PUBLIC KEY-----\n",
            base64(&spki)
        );
        Self { pair, verifier }
    }

    fn sign(&self, data: &[u8]) -> Vec<u8> {
        self.pair
            .sign(&SystemRandom::new(), data)
            .expect("signature")
            .as_ref()
            .to_vec()
    }

    fn source(&self) -> Update {
        Update {
            url: "https://releases.example.test/laris".to_owned(),
            signature_verifier: self.verifier.clone(),
            interval_minutes: 1,
        }
    }

    /// The files of a release: `latest/` (list, signature, version) and `<version>/<archive>`.
    fn publish(&self, version: &str, archive: &[u8]) -> Files {
        let sums = format!(
            "{}  VERSION\n{}  {}\n",
            hex(format!("{version}\n").as_bytes()),
            hex(archive),
            archive_name(TARGET)
        );
        let mut files = Files::default();
        let base = "https://releases.example.test/laris";
        files.put(&format!("{base}/latest/SHA256SUMS"), sums.as_bytes());
        files.put(
            &format!("{base}/latest/SHA256SUMS.sig"),
            &self.sign(sums.as_bytes()),
        );
        files.put(
            &format!("{base}/latest/VERSION"),
            format!("{version}\n").as_bytes(),
        );
        files.put(
            &format!("{base}/{version}/{}", archive_name(TARGET)),
            archive,
        );
        files
    }
}

#[derive(Default)]
struct Files {
    map: Mutex<HashMap<String, Vec<u8>>>,
}

impl Files {
    fn put(&mut self, url: &str, bytes: &[u8]) {
        self.map
            .lock()
            .expect("lock")
            .insert(url.to_owned(), bytes.to_vec());
    }
}

impl Fetch for Files {
    fn get(&self, url: &str, limit: usize) -> Result<Vec<u8>, String> {
        let bytes = self
            .map
            .lock()
            .expect("lock")
            .get(url)
            .cloned()
            .ok_or_else(|| format!("status 404: {url}"))?;
        (bytes.len() <= limit)
            .then_some(bytes)
            .ok_or_else(|| "too large".to_owned())
    }
}

fn temp(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-update-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

/// A `.tar.gz` holding one file `laris`.
fn archive_of(content: &str, dir: &std::path::Path) -> Vec<u8> {
    let src = dir.join("src");
    std::fs::create_dir_all(&src).expect("src");
    std::fs::write(src.join("laris"), content).expect("program");
    let out = dir.join("a.tar.gz");
    let status = std::process::Command::new("tar")
        .args(["-czf"])
        .arg(&out)
        .arg("-C")
        .arg(&src)
        .arg("laris")
        .status()
        .expect("tar");
    assert!(status.success());
    std::fs::read(out).expect("archive")
}

#[test]
fn versions_compare_by_number_not_by_text() {
    assert_eq!(parse_version("1.10.2"), Some((1, 10, 2)));
    assert_eq!(parse_version("1.2.3-rc1\n"), Some((1, 2, 3)));
    assert_eq!(parse_version("1.2"), None);
    assert_eq!(parse_version("1.2.3.4"), None);
    assert!(parse_version("1.10.0") > parse_version("1.9.9"));
}

#[test]
fn a_newer_signed_release_is_found_and_the_same_or_an_older_one_is_not() {
    let release = Release::new();
    let files = release.publish("1.2.0", b"archive");
    match check(&files, &release.source(), "1.1.0", TARGET).expect("check") {
        Found::Newer {
            version,
            archive_sha256,
        } => {
            assert_eq!(version, "1.2.0");
            assert_eq!(archive_sha256, hex(b"archive"));
        }
        Found::Current => panic!("1.2.0 is newer than 1.1.0"),
    }
    assert_eq!(
        check(&files, &release.source(), "1.2.0", TARGET),
        Ok(Found::Current)
    );
    assert_eq!(
        check(&files, &release.source(), "1.3.0", TARGET),
        Ok(Found::Current)
    );
}

#[test]
fn a_list_with_a_bad_signature_or_another_key_or_a_changed_version_is_refused() {
    let release = Release::new();
    let mut files = release.publish("9.0.0", b"archive");
    // signed by someone else
    let other = Release::new();
    let mut foreign = other.publish("9.0.0", b"archive");
    let base = "https://releases.example.test/laris/latest";
    assert!(check(&foreign, &release.source(), "1.0.0", TARGET).is_err());
    foreign.put(&format!("{base}/SHA256SUMS.sig"), b"not a signature");
    assert!(check(&foreign, &other.source(), "1.0.0", TARGET).is_err());
    // the version file does not match the signed list
    files.put(&format!("{base}/VERSION"), b"9.9.9\n");
    let err = check(&files, &release.source(), "1.0.0", TARGET).expect_err("changed version");
    assert!(err.contains("signed list"), "{err}");
    // a key that is not a key
    let mut source = release.source();
    source.signature_verifier = "not a key".to_owned();
    assert!(check(&release.publish("9.0.0", b"a"), &source, "1.0.0", TARGET).is_err());
}

#[test]
fn an_archive_that_does_not_match_the_signed_checksum_is_not_installed() {
    let release = Release::new();
    let dir = temp("tamper");
    let good = archive_of("new program", &dir);
    let mut files = release.publish("1.2.0", &good);
    let exe = dir.join("laris");
    std::fs::write(&exe, "old program").expect("exe");
    files.put(
        &format!(
            "https://releases.example.test/laris/1.2.0/{}",
            archive_name(TARGET)
        ),
        b"something else",
    );
    let found = check(&files, &release.source(), "1.1.0", TARGET).expect("check");
    let err = install(&files, &release.source(), &found, TARGET, &exe, &dir).expect_err("refused");
    assert!(err.contains("signed list"), "{err}");
    assert_eq!(std::fs::read_to_string(&exe).expect("exe"), "old program");
    std::fs::remove_dir_all(dir).ok();
}

#[cfg(target_os = "linux")]
#[test]
fn a_round_installs_the_new_program_in_place_and_a_second_round_has_nothing_to_do() {
    let release = Release::new();
    let dir = temp("round");
    let archive = archive_of("new program", &dir);
    let files = release.publish("1.2.0", &archive);
    let exe = dir.join("laris");
    std::fs::write(&exe, "old program").expect("exe");
    let done = run_once(&files, &release.source(), "1.1.0", &exe, &dir).expect("round");
    assert_eq!(done.as_deref(), Some("1.2.0"));
    assert_eq!(std::fs::read_to_string(&exe).expect("exe"), "new program");
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&exe).expect("meta").permissions().mode();
        assert_eq!(mode & 0o111, 0o111, "the program stays executable");
    }
    assert!(!dir.join(".laris.new").exists(), "no staging file is left");
    assert!(
        std::fs::read_dir(&dir).expect("dir").all(|e| !e
            .expect("e")
            .file_name()
            .to_string_lossy()
            .starts_with("update-")),
        "the work folder is removed"
    );
    // the same program now runs 1.2.0: nothing newer
    assert_eq!(
        run_once(&files, &release.source(), "1.2.0", &exe, &dir),
        Ok(None)
    );
    std::fs::remove_dir_all(dir).ok();
}
