//! Binary laris.

use laris_cli::headless::{self, Console};
use laris_cli::login::HttpVerifier;
use laris_cli::start::{Started, start};
use laris_cli::{account, learn};
use laris_config::Catalogue;
use std::io::{IsTerminal, Read};
use std::process::ExitCode;

const USAGE: &str = "usage: laris <-p [REQUEST] | login | logout | status | learn <stats | collect [--session ID] | export --kind sft|retrieval|preference --out FILE [--min-rating none|up] | rate ID up|down | purge --yes>>\nlogin reads the key from standard input: printf '%s' \"$KEY\" | laris login";

fn started() -> Result<Started, String> {
    let env: Vec<(String, String)> = std::env::vars().collect();
    let cwd =
        std::env::current_dir().map_err(|e| format!("cannot find the working folder: {e}"))?;
    start(env, &cwd, std::env::current_exe().ok().as_deref())
}

fn report(result: Result<String, String>, name: &str) -> ExitCode {
    match result {
        Ok(out) => {
            println!("{out}");
            ExitCode::SUCCESS
        }
        Err(message) => {
            eprintln!("laris {name}: {message}");
            ExitCode::from(2)
        }
    }
}

fn headless(options: &headless::Options) -> ExitCode {
    let started = match started() {
        Ok(started) => started,
        Err(message) => {
            eprintln!("laris: {message}");
            return ExitCode::from(headless::exit::USAGE);
        }
    };
    let mut stdin = std::io::stdin();
    let piped = !stdin.is_terminal();
    let console = Console {
        out: Box::new(std::io::stdout()),
        err: Box::new(std::io::stderr()),
    };
    let input: Option<&mut dyn Read> = if piped { Some(&mut stdin) } else { None };
    ExitCode::from(headless::real::run(&started, options, input, console))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match headless::parse(&args) {
        Ok(Some(options)) => return headless(&options),
        Ok(None) => {}
        Err(message) => {
            eprintln!("laris: {message}\n{}", headless::USAGE);
            return ExitCode::from(headless::exit::USAGE);
        }
    }
    let name = args.first().map(String::as_str);
    if !matches!(name, Some("login" | "logout" | "status" | "learn")) {
        eprintln!("{USAGE}");
        return ExitCode::from(2);
    }
    let started = match started() {
        Ok(started) => started,
        Err(message) => {
            eprintln!("laris: {message}");
            return ExitCode::from(2);
        }
    };
    match name {
        Some("login") => {
            if std::io::stdin().is_terminal() {
                let words = Catalogue::new(started.settings.ui.language);
                let hint = words.get("login.needs_pipe", &[]).unwrap_or_default();
                eprintln!("laris login: {hint}");
                return ExitCode::from(2);
            }
            let mut typed = String::new();
            if let Err(e) = std::io::stdin().take(16 * 1024).read_to_string(&mut typed) {
                eprintln!("laris login: cannot read the key: {e}");
                return ExitCode::from(2);
            }
            report(
                account::login(
                    &started,
                    &typed,
                    &HttpVerifier {
                        use_env_proxy: true,
                    },
                ),
                "login",
            )
        }
        Some("logout") => report(account::logout(&started), "logout"),
        Some("status") => report(Ok(account::status(&started)), "status"),
        _ => {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0.0, |d| d.as_secs_f64());
            let cx = learn::Context {
                home: started.home.root().to_path_buf(),
                project: started.project.clone(),
                env: started.env.clone(),
                now,
            };
            report(learn::run(&args[1..], &cx), "learn")
        }
    }
}
