//! The deployment files hold the promises of the threat model that can be checked without Docker: SEC-DEP-01 (no policy
//! and no weights in an image, both mounted read-only at run time) and the static half of SEC-NET-01 (TLS ends at the
//! gateway and the gateway keeps keys out of its log). `docker/verify-images.sh` checks the same on built images; this
//! file keeps a change to a Dockerfile, the compose file or the Caddyfile from undoing it in CI.

use std::path::{Path, PathBuf};

fn docker(name: &str) -> String {
    let path: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../docker")
        .join(name);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn ignore_file() -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.dockerignore");
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// Active lines: comments and blanks removed.
fn lines(text: &str) -> Vec<String> {
    text.lines()
        .map(|l| l.split('#').next().unwrap_or("").trim().to_owned())
        .filter(|l| !l.is_empty())
        .collect()
}

#[test]
fn images_copy_no_policy_no_weights_and_no_secrets() {
    let forbidden = [
        ".laris",
        "artifacts",
        "weights",
        "secrets",
        "data",
        "LARIS.md",
        "integrity",
        ".env",
    ];
    for file in ["server.Dockerfile", "model.Dockerfile"] {
        for line in lines(&docker(file)) {
            let words: Vec<&str> = line.split_whitespace().collect();
            if !matches!(words.first(), Some(&"COPY") | Some(&"ADD")) {
                continue;
            }
            // `COPY --from=build /src /dst` copies from a build stage, not from the context.
            if words.iter().any(|w| w.starts_with("--from=")) {
                continue;
            }
            for source in words
                .iter()
                .skip(1)
                .filter(|w| !w.starts_with("--"))
                .rev()
                .skip(1)
            {
                let root = source.trim_start_matches("./").split('/').next().unwrap();
                assert!(
                    !forbidden.contains(&root),
                    "{file}: `{line}` copies {source} into an image"
                );
            }
        }
    }
    // The build context itself leaves them out too.
    let ignored = lines(&ignore_file());
    for must in [
        ".laris",
        "artifacts",
        "data",
        "docker/secrets",
        "LARIS.md",
        ".env",
        "**/*.safetensors",
        "**/*.pt",
        "**/*.pth",
        "**/*.ckpt",
    ] {
        assert!(
            ignored.iter().any(|l| l == must),
            ".dockerignore does not list {must}"
        );
    }
}

#[test]
fn policy_and_weights_are_mounted_read_only_and_never_published() {
    let compose = docker("compose.yaml");
    let active = lines(&compose);
    for line in &active {
        if line.contains(".laris") || line.contains("/weights") {
            assert!(
                line.trim_end_matches('"').ends_with(":ro"),
                "not read-only: {line}"
            );
        }
    }
    assert!(
        active
            .iter()
            .any(|l| l.contains(".laris:/policy/.laris:ro")),
        "the policy is not mounted"
    );
    assert!(
        active.iter().any(|l| l.contains(":/weights:ro")),
        "the weights are not mounted"
    );
    // Only the gateway publishes ports; the internal network has no route out.
    assert_eq!(
        active.iter().filter(|l| *l == "ports:").count(),
        1,
        "more than one service publishes ports"
    );
    assert!(active.iter().any(|l| l == "internal: true"));
    // Every service drops its capabilities.
    let services = compose
        .lines()
        .filter(|l| l.starts_with("    image:") || l.starts_with("    build:"))
        .count();
    let dropped = active.iter().filter(|l| *l == "cap_drop: [ALL]").count();
    assert!(
        dropped >= 4 && dropped >= services.min(4),
        "{dropped} services drop their capabilities"
    );
}

#[test]
fn secrets_are_files_and_not_environment_values() {
    for line in lines(&docker("compose.yaml")) {
        let upper = line.to_uppercase();
        let name_part = upper.split(':').next().unwrap_or("");
        let names_a_secret = ["PASSWORD", "SECRET", "TOKEN", "KEY", "DATABASE_URL"]
            .iter()
            .any(|w| name_part.ends_with(w));
        let is_setting = line.contains(": ") && !line.starts_with('-');
        if names_a_secret && is_setting {
            let name = line.split(':').next().unwrap_or("");
            // `secrets: [a, b]` lists Docker secrets by name: that is the right way to pass one.
            if name == "secrets" {
                continue;
            }
            assert!(
                name.ends_with("_FILE") || line.contains("/run/secrets/"),
                "a secret value in the compose file: {name}"
            );
        }
    }
}

#[test]
fn both_images_run_as_a_non_root_user() {
    let server = lines(&docker("server.Dockerfile"));
    assert!(server.iter().any(|l| l == "USER 65532:65532"));
    assert!(
        server
            .iter()
            .any(|l| l.contains("distroless/static") && l.contains("nonroot"))
    );
    let model = lines(&docker("model.Dockerfile"));
    assert!(model.iter().any(|l| l == "USER 10001:10001"));
    for file in ["server.Dockerfile", "model.Dockerfile"] {
        assert!(
            !lines(&docker(file))
                .iter()
                .any(|l| l == "USER root" || l == "USER 0"),
            "{file} switches back to root"
        );
    }
}

#[test]
fn the_gateway_ends_tls_and_keeps_keys_out_of_its_log() {
    let caddy = lines(&docker("Caddyfile")).join("\n");
    assert!(
        !caddy.contains("auto_https off") && !caddy.contains("http://"),
        "the gateway serves plain HTTP or switches TLS off"
    );
    assert!(caddy.contains("Strict-Transport-Security"));
    assert!(
        caddy.contains("request>headers>Authorization delete"),
        "keys would reach the gateway log"
    );
    // Only the public half of the authority is served, and by a rewrite to one file.
    assert!(caddy.contains("rewrite * /root.crt"));
    assert!(!caddy.contains("root.key") && !caddy.contains("intermediate.key"));
    // The server is reached over the internal network by name; nothing public points at it.
    assert!(caddy.contains("reverse_proxy server:8080"));
}
