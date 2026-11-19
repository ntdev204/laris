//! The client starts with nothing to configure and signs in inside the interface (T155, SR-C3, SR-C4).
//! Every test uses its own `LARIS_HOME`; none touches the real `~/.laris`.

mod common;

use common::{KeyServer, Scripted, env, temp_dir};
use laris_cli::account;
use laris_cli::credentials::{self, Saved};
use laris_cli::login::{
    HttpVerifier, KeySource, KeyVerifier, LoginError, LoginForm, Reason, Startup, VerifyError,
    decide, sign_out,
};
use laris_cli::start::{Started, start};
use laris_config::Catalogue;
use laris_model_client::{ApiKey, ClientConfig};
use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;

const GOOD: &str = "laris-test-key-0001";
const PACKAGED_URL: &str = "https://packaged.example.org/v1";

struct Setup {
    base: PathBuf,
    env: Vec<(String, String)>,
}

impl Setup {
    /// A fresh folder with a packaged defaults file naming `PACKAGED_URL`.
    fn new(name: &str) -> Self {
        let base = temp_dir(name);
        let defaults = base.join("defaults.json");
        std::fs::write(
            &defaults,
            format!(r#"{{"server": {{"url": "{PACKAGED_URL}"}}}}"#),
        )
        .unwrap();
        let env = env(&[
            ("LARIS_HOME", &base.join(".laris").to_string_lossy()),
            ("LARIS_PACKAGED_DEFAULTS", &defaults.to_string_lossy()),
        ]);
        Self { base, env }
    }

    fn with(mut self, name: &str, value: &str) -> Self {
        self.env.push((name.to_owned(), value.to_owned()));
        self
    }

    fn start(&self) -> Started {
        let cwd = self.base.join("work");
        std::fs::create_dir_all(&cwd).unwrap();
        start(self.env.clone(), &cwd, None).unwrap()
    }
}

impl Drop for Setup {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.base).ok();
    }
}

fn credentials_of(started: &Started) -> PathBuf {
    started.home.credentials_path()
}

#[test]
fn a_fresh_home_reaches_a_ready_client_after_the_key_is_entered() {
    let setup = Setup::new("fresh");
    let started = setup.start();
    assert!(!started.created.is_empty(), "the layout was created");
    assert_eq!(
        started.settings.server.url, PACKAGED_URL,
        "the package supplied the server"
    );

    let Startup::NeedsLogin { server, reason } =
        decide(&started.home, &started.settings, &started.env)
    else {
        panic!("a fresh home has no key");
    };
    assert_eq!(server, PACKAGED_URL);
    assert_eq!(reason, Reason::FirstRun);

    let verifier = Scripted::accepting(GOOD);
    let mut form = LoginForm::new(started.settings.server.clone());
    let signed = form
        .submit(&started.home, GOOD, &verifier)
        .expect("accepted");
    assert_eq!(signed.account.role, "user");
    assert!(form.error().is_none());

    let Startup::Ready { key, source, .. } = decide(&started.home, &started.settings, &started.env)
    else {
        panic!("the saved key is used");
    };
    assert_eq!(source, KeySource::Saved);
    assert_eq!(key, ApiKey::new(GOOD).unwrap());
    // The ready key makes a client configuration without any other input.
    ClientConfig::from_server(&started.settings.server, Some(key)).unwrap();
}

#[test]
fn a_wrong_key_shows_the_form_again_and_saves_nothing() {
    let setup = Setup::new("wrong");
    let started = setup.start();
    let verifier = Scripted::accepting(GOOD);
    let mut form = LoginForm::new(started.settings.server.clone());

    assert!(
        form.submit(&started.home, "not-the-key", &verifier)
            .is_none()
    );
    assert_eq!(form.error(), Some(&LoginError::Rejected));
    assert_eq!(form.attempts(), 1);
    assert!(
        !credentials_of(&started).exists(),
        "nothing is written for a refused key"
    );
    assert!(matches!(
        decide(&started.home, &started.settings, &started.env),
        Startup::NeedsLogin { .. }
    ));

    assert!(
        form.submit(&started.home, "another-wrong", &verifier)
            .is_none()
    );
    assert_eq!(form.attempts(), 2);
    let again = form.submit(&started.home, GOOD, &verifier);
    assert!(again.is_some(), "the right key then works in the same form");
    assert_eq!(form.error(), None);
    assert_eq!(form.attempts(), 3);
    assert!(credentials_of(&started).is_file());
}

#[test]
fn an_unreachable_server_saves_nothing_and_the_message_names_the_server_not_the_key() {
    let setup = Setup::new("unreachable");
    let started = setup.start();
    let mut verifier = Scripted::accepting(GOOD);
    verifier.unreachable = true;
    let mut form = LoginForm::new(started.settings.server.clone());
    assert!(form.submit(&started.home, GOOD, &verifier).is_none());
    let error = form.error().cloned().unwrap();
    assert!(matches!(error, LoginError::Unreachable(_)));
    let text = error
        .message(&Catalogue::english(), &form.server())
        .unwrap();
    assert!(
        text.contains(PACKAGED_URL) && text.contains("not saved"),
        "{text}"
    );
    assert!(!text.contains(GOOD));
    assert!(!credentials_of(&started).exists());
}

#[test]
fn a_key_that_cannot_travel_in_a_header_never_reaches_the_server() {
    let setup = Setup::new("invalid");
    let started = setup.start();
    let verifier = Scripted::accepting(GOOD);
    let mut form = LoginForm::new(started.settings.server.clone());
    for bad in ["", "   ", "two words", "tab\tinside"] {
        assert!(
            form.submit(&started.home, bad, &verifier).is_none(),
            "{bad:?}"
        );
        assert!(
            matches!(form.error(), Some(LoginError::InvalidKey(_))),
            "{bad:?}"
        );
    }
    assert_eq!(verifier.calls.load(Ordering::SeqCst), 0);
    assert!(!credentials_of(&started).exists());
}

#[test]
fn the_saved_file_is_private_and_complete() {
    let setup = Setup::new("private");
    let started = setup.start();
    let verifier = Scripted::accepting(GOOD);
    LoginForm::new(started.settings.server.clone())
        .submit(&started.home, &format!("  {GOOD}\n"), &verifier)
        .expect("accepted");
    let path = credentials_of(&started);
    let saved = credentials::read(&path).unwrap().unwrap();
    assert_eq!(saved.api_key, GOOD, "surrounding space is dropped");
    assert_eq!(saved.server, PACKAGED_URL);
    assert!(!path.with_extension("json.tmp").exists(), "no leftover");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&path).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, 0o600);
        // A copy restored with loose permissions is made private when it is read.
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        credentials::read(&path).unwrap().unwrap();
        let mode = std::fs::metadata(&path).unwrap().permissions().mode();
        assert_eq!(mode & 0o077, 0);
    }
    // The key is in no setting and in no debug output.
    let settings_text = std::fs::read_to_string(started.home.settings_path()).unwrap();
    assert!(!settings_text.contains(GOOD));
    assert!(!format!("{saved:?}").contains(GOOD));
    let form = LoginForm::new(started.settings.server.clone());
    assert!(!format!("{form:?}").contains(GOOD));
}

#[test]
fn the_environment_key_wins_over_the_saved_one() {
    let setup = Setup::new("env-key").with("LARIS_API_KEY", "from-the-environment");
    let started = setup.start();
    credentials::write(
        &credentials_of(&started),
        &Saved {
            api_key: "saved-key".to_owned(),
            server: PACKAGED_URL.to_owned(),
        },
    )
    .unwrap();
    let Startup::Ready { key, source, .. } = decide(&started.home, &started.settings, &started.env)
    else {
        panic!("ready");
    };
    assert_eq!(source, KeySource::Environment);
    assert_eq!(key, ApiKey::new("from-the-environment").unwrap());
}

#[test]
fn a_key_accepted_by_one_server_is_not_used_for_another() {
    let setup = Setup::new("other-server");
    let started = setup.start();
    credentials::write(
        &credentials_of(&started),
        &Saved {
            api_key: GOOD.to_owned(),
            server: "https://old.example.org/v1".to_owned(),
        },
    )
    .unwrap();
    let Startup::NeedsLogin { reason, .. } = decide(&started.home, &started.settings, &started.env)
    else {
        panic!("the key must not travel to a server that never saw it");
    };
    assert_eq!(
        reason,
        Reason::OtherServer("https://old.example.org/v1".to_owned())
    );
    // The same server written differently still matches.
    credentials::write(
        &credentials_of(&started),
        &Saved {
            api_key: GOOD.to_owned(),
            server: "Packaged.Example.org".to_owned(),
        },
    )
    .unwrap();
    assert!(matches!(
        decide(&started.home, &started.settings, &started.env),
        Startup::Ready { .. }
    ));
}

#[test]
fn a_damaged_credentials_file_asks_again_and_login_replaces_it() {
    let setup = Setup::new("damaged");
    let started = setup.start();
    std::fs::write(credentials_of(&started), "{not json").unwrap();
    let Startup::NeedsLogin { reason, .. } = decide(&started.home, &started.settings, &started.env)
    else {
        panic!("form");
    };
    assert!(matches!(reason, Reason::Unreadable(_)));
    let verifier = Scripted::accepting(GOOD);
    let mut form = LoginForm::new(started.settings.server.clone());
    form.submit(&started.home, GOOD, &verifier)
        .expect("accepted");
    assert!(matches!(
        decide(&started.home, &started.settings, &started.env),
        Startup::Ready { .. }
    ));
}

#[test]
fn overrides_work_environment_over_file_over_package() {
    // The package alone.
    let setup = Setup::new("overrides");
    assert_eq!(setup.start().settings.server.url, PACKAGED_URL);
    // The settings file beats the package.
    std::fs::write(
        setup.base.join(".laris/settings.json"),
        r#"{"server": {"url": "https://file.example.org/v1"}, "ui": {"theme": "dark"}}"#,
    )
    .unwrap();
    let started = setup.start();
    assert_eq!(started.settings.server.url, "https://file.example.org/v1");
    // The environment beats the file.
    let setup = setup.with("LARIS_SERVER__URL", "https://env.example.org/v1");
    let started = setup.start();
    assert_eq!(started.settings.server.url, "https://env.example.org/v1");
    let Startup::NeedsLogin { server, .. } = decide(&started.home, &started.settings, &started.env)
    else {
        panic!("form");
    };
    assert_eq!(server, "https://env.example.org/v1");
    // A setting the environment does not name still comes from the file.
    assert_eq!(format!("{:?}", started.settings.ui.theme), "Dark");
    // A broken override is an error naming the variable.
    let broken = Setup::new("overrides-bad").with("LARIS_SERVER__MAX_RETRIES", "many");
    let error = start(broken.env.clone(), &broken.base, None).unwrap_err();
    assert!(error.contains("LARIS_SERVER__MAX_RETRIES"), "{error}");
}

#[test]
fn without_any_server_address_there_is_nothing_to_sign_in_to() {
    let base = temp_dir("no-server");
    let env = env(&[
        ("LARIS_HOME", &base.join(".laris").to_string_lossy()),
        (
            "LARIS_PACKAGED_DEFAULTS",
            &base.join("missing.json").to_string_lossy(),
        ),
    ]);
    let started = start(env, &base, None).unwrap();
    assert_eq!(
        decide(&started.home, &started.settings, &started.env),
        Startup::NoServer
    );
    let verifier = Scripted::accepting(GOOD);
    let mut form = LoginForm::new(started.settings.server.clone());
    assert!(form.submit(&started.home, GOOD, &verifier).is_none());
    assert_eq!(form.error(), Some(&LoginError::NoServer));
    assert_eq!(verifier.calls.load(Ordering::SeqCst), 0);
    let hint = LoginError::NoServer
        .message(&Catalogue::english(), "")
        .unwrap();
    assert!(hint.contains("LARIS_SERVER__URL"));
    std::fs::remove_dir_all(base).ok();
}

#[test]
fn messages_follow_the_interface_language_and_default_to_english() {
    let setup = Setup::new("language");
    assert_eq!(setup.start().settings.ui.language.code(), "en");
    std::fs::write(
        setup.base.join(".laris/settings.json"),
        r#"{"ui": {"language": "vi"}}"#,
    )
    .unwrap();
    let started = setup.start();
    let verifier = Scripted::accepting(GOOD);
    let refused = account::login(&started, "wrong", &verifier).unwrap_err();
    assert_eq!(
        refused,
        Catalogue::new(started.settings.ui.language)
            .get("login.rejected", &[])
            .unwrap()
    );
    assert!(refused.contains("khóa"), "{refused}");
    assert!(
        account::login(&started, GOOD, &verifier)
            .unwrap()
            .contains("Đã đăng nhập")
    );
}

#[test]
fn logout_removes_the_key_and_says_so_once() {
    let setup = Setup::new("logout");
    let started = setup.start();
    let verifier = Scripted::accepting(GOOD);
    account::login(&started, &format!("\n{GOOD}\n"), &verifier).unwrap();
    assert!(credentials_of(&started).is_file());
    assert!(account::logout(&started).unwrap().contains("Signed out"));
    assert!(!credentials_of(&started).exists());
    assert!(account::logout(&started).unwrap().contains("no saved key"));
    assert!(!sign_out(&started.home).unwrap());
}

#[test]
fn the_status_names_the_state_and_never_the_key() {
    let setup = Setup::new("status");
    let started = setup.start();
    let before = account::status(&started);
    assert!(before.contains("not signed in"), "{before}");
    account::login(&started, GOOD, &Scripted::accepting(GOOD)).unwrap();
    let after = account::status(&started);
    assert!(after.contains("\"signedIn\": \"saved\""), "{after}");
    assert!(!after.contains(GOOD));
    // Stray files in the project's `.laris` are listed, and nothing in them is read.
    std::fs::create_dir_all(started.project.join(".laris")).unwrap();
    std::fs::write(
        started.project.join(".laris/settings.json"),
        r#"{"server": {"url": "https://evil.example.org/v1"}}"#,
    )
    .unwrap();
    let again = start(setup.env.clone(), &started.project, None).unwrap();
    assert_eq!(
        again.settings.server.url, PACKAGED_URL,
        "a project's settings are ignored"
    );
    assert!(account::status(&again).contains("settings.json"));
}

#[test]
fn the_http_verifier_accepts_the_right_key_and_refuses_the_wrong_one() {
    let server = KeyServer::start(GOOD);
    let settings = laris_config::settings::Server {
        url: server.url.clone(),
        max_retries: 0,
        ..Default::default()
    };
    let verifier = HttpVerifier {
        use_env_proxy: false,
    };
    let account = verifier
        .verify(&settings, &ApiKey::new(GOOD).unwrap())
        .unwrap();
    assert_eq!(account.role, "user");
    assert_eq!(
        verifier.verify(&settings, &ApiKey::new("wrong-key").unwrap()),
        Err(VerifyError::Refused)
    );
    assert_eq!(
        server.authorizations(),
        vec![format!("Bearer {GOOD}"), "Bearer wrong-key".to_owned()]
    );
}

#[test]
fn the_http_verifier_reports_a_closed_port_as_unreachable() {
    let closed = {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        listener.local_addr().unwrap().port()
    };
    let settings = laris_config::settings::Server {
        url: format!("http://127.0.0.1:{closed}/v1"),
        max_retries: 0,
        ..Default::default()
    };
    let verifier = HttpVerifier {
        use_env_proxy: false,
    };
    let error = verifier
        .verify(&settings, &ApiKey::new(GOOD).unwrap())
        .unwrap_err();
    assert!(matches!(error, VerifyError::Other(_)), "{error:?}");
}

#[test]
fn the_command_line_signs_in_through_the_real_http_path() {
    let server = KeyServer::start(GOOD);
    let base = temp_dir("binary");
    let home = base.join(".laris");
    let run = |args: &[&str], stdin: &str| {
        use std::io::Write;
        let mut child = std::process::Command::new(env!("CARGO_BIN_EXE_laris"))
            .args(args)
            .env_clear()
            .env("LARIS_HOME", &home)
            .env("LARIS_SERVER__URL", &server.url)
            .env("LARIS_SERVER__MAX_RETRIES", "0")
            .current_dir(&base)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(stdin.as_bytes())
            .unwrap();
        child.wait_with_output().unwrap()
    };
    let text = |bytes: &[u8]| String::from_utf8_lossy(bytes).into_owned();

    // A fresh home: the first command creates the layout and says it is not signed in.
    assert!(!Path::new(&home).exists());
    let status = run(&["status"], "");
    assert!(status.status.success());
    assert!(text(&status.stdout).contains("not signed in"));
    assert!(home.join("settings.json").is_file() && home.join("projects").is_dir());

    // A wrong key: exit 2, the form's message, nothing saved.
    let wrong = run(&["login"], "wrong-key\n");
    assert_eq!(wrong.status.code(), Some(2));
    assert!(
        text(&wrong.stderr).contains("did not accept"),
        "{}",
        text(&wrong.stderr)
    );
    assert!(!home.join("credentials.json").exists());

    // The right key: saved, and status says so without printing it.
    let good = run(&["login"], &format!("{GOOD}\n"));
    assert!(good.status.success(), "{}", text(&good.stderr));
    assert!(text(&good.stdout).contains("Signed in as user"));
    assert!(home.join("credentials.json").is_file());
    let status = run(&["status"], "");
    assert!(text(&status.stdout).contains("\"signedIn\": \"saved\""));
    assert!(!text(&status.stdout).contains(GOOD) && !text(&status.stderr).contains(GOOD));

    assert!(run(&["logout"], "").status.success());
    assert!(!home.join("credentials.json").exists());
    std::fs::remove_dir_all(base).ok();
}
