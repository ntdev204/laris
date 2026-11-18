//! Redaction: the shapes of credentials, literal secrets, JSON, tool output, what tools persist and what leaves
//! for the model (SEC-INJ-02).

mod common;

use common::{args, rig};
use laris_config::Settings;
use laris_core::{Model, ModelAnswer, ModelRequest, ScriptedModel, ToolRunner, digest_of};
use laris_policy::{MASK, RedactingModel, Redactor, Shield, ShieldedRunner};
use laris_protocol::{ChatMessage, Content, Role, ToolCall, ToolCallFunction};
use laris_tools::{Context, Registry};
use serde_json::json;
use std::sync::Arc;

const AWS: &str = "AKIAIOSFODNN7EXAMPLE";
const GITHUB: &str = "ghp_abcdefghijklmnopqrstuvwxyz0123456789";
const OPENAI: &str = "sk-proj-abcdefghijklmnopqrstuvwxyz012345";
const JWT: &str =
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U";

fn redact(text: &str) -> String {
    Redactor::standard().redact(text).into_owned()
}

#[test]
fn known_shapes_are_hidden() {
    for secret in [
        AWS,
        GITHUB,
        OPENAI,
        JWT,
        "xoxb-123456789012-abcdefghij",
        "glpat-abcdefghij0123456789",
    ] {
        let out = redact(&format!("value is {secret} here"));
        assert_eq!(out, format!("value is {MASK} here"), "{secret}");
    }
    let key =
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----";
    assert_eq!(
        redact(&format!("before\n{key}\nafter")),
        format!("before\n{MASK}\nafter")
    );
    // a key block that was cut short still goes
    let cut = redact("x\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk");
    assert_eq!(cut, format!("x\n{MASK}"));
}

#[test]
fn assignments_headers_and_urls_keep_their_names() {
    assert_eq!(redact("API_KEY=hunter2hunter2"), format!("API_KEY={MASK}"));
    assert_eq!(
        redact(r#"{"db_password": "correct-horse-battery"}"#),
        format!(r#"{{"db_password": "{MASK}"}}"#)
    );
    assert_eq!(
        redact("Authorization: Bearer abcdef0123456789abcdef"),
        format!("Authorization: Bearer {MASK}")
    );
    assert_eq!(
        redact("clone https://user:s3cretpass@example.com/repo.git"),
        format!("clone https://user:{MASK}@example.com/repo.git")
    );
    assert_eq!(
        redact("export GITHUB_TOKEN='tok_1234567890'"),
        format!("export GITHUB_TOKEN='{MASK}'")
    );
}

#[test]
fn ordinary_text_is_left_alone() {
    for text in [
        "the token count is 42",
        "fn main() { println!(\"hello\"); }",
        "see https://example.com/docs and user@example.com",
        "sk-short",
        "",
    ] {
        assert_eq!(redact(text), text, "{text}");
    }
    assert!(!Redactor::standard().finds("nothing to hide"));
    assert!(Redactor::standard().finds(AWS));
}

#[test]
fn redaction_is_idempotent() {
    let once = redact(&format!("{GITHUB} and API_KEY=abcdef123456 and {AWS}"));
    assert_eq!(redact(&once), once);
}

#[test]
fn literal_secrets_are_replaced_by_value() {
    let r =
        Redactor::standard().with_secrets(["my-very-odd-secret".to_owned(), "short".to_owned()]);
    assert_eq!(
        r.redact("a my-very-odd-secret b short c").as_ref(),
        format!("a {MASK} b short c")
    );
    let env = Redactor::standard().with_env_secrets([
        ("LARIS_API_KEY".to_owned(), "plainvalue123".to_owned()),
        ("EDITOR".to_owned(), "vimvimvimvim".to_owned()),
    ]);
    assert_eq!(
        env.redact("k=plainvalue123 e=vimvimvimvim").as_ref(),
        format!("k={MASK} e=vimvimvimvim")
    );
}

#[test]
fn json_is_redacted_inside_and_keeps_its_shape() {
    let value =
        json!({"a": [GITHUB, 1, null, true], "b": {"c": format!("x {AWS}")}, GITHUB: "key"});
    let out = Redactor::standard().redact_value(&value);
    assert_eq!(out["a"][0], MASK);
    assert_eq!(out["a"][1], 1);
    assert_eq!(out["b"]["c"], format!("x {MASK}"));
    assert!(
        out.as_object().expect("object").contains_key(GITHUB),
        "keys are kept"
    );
}

#[test]
fn a_secret_in_tool_output_never_reaches_the_loop() {
    let rig = rig("redact-output");
    rig.write_file("notes.txt", &format!("deploy with {GITHUB}\nplain line\n"));
    let ctx = Context::new(&rig.project, &Settings::default()).expect("context");
    let shield = Arc::new(Shield::new(Arc::new(Redactor::standard())));
    let mut runner = ShieldedRunner::new(Registry::with_local_tools(ctx), shield);

    let read = runner.run("Read", &args(json!({"path": "notes.txt"})));
    let text = read.to_string();
    assert!(!text.contains(GITHUB), "{text}");
    assert!(text.contains(MASK) && text.contains("plain line"));

    let bash = runner.run(
        "Bash",
        &args(json!({"command": format!("echo {AWS} && echo API_KEY=zzzzzz999999")})),
    );
    let text = bash.to_string();
    assert!(
        !text.contains(AWS) && !text.contains("zzzzzz999999"),
        "{text}"
    );
    // a typed error is finished too
    let error = runner.run(
        "Read",
        &args(json!({"path": format!("missing-{GITHUB}.txt")})),
    );
    assert!(!error.to_string().contains(GITHUB));
}

#[test]
fn what_tools_persist_is_redacted() {
    let rig = rig("redact-persist");
    let redactor = Arc::new(Redactor::standard());
    let ctx = Context::new(&rig.project, &Settings::default())
        .expect("context")
        .with_redactor(redactor.for_tools());
    let mut registry = Registry::with_local_tools(ctx);
    let wrote = registry.call(
        "Write",
        &args(json!({"path": "out.txt", "content": format!("key {AWS}\n")})),
    );
    assert!(wrote.get("error").is_none(), "{wrote}");
    let saved = rig.read("out.txt");
    assert!(!saved.contains(AWS) && saved.contains(MASK), "{saved}");
}

fn text_message(role: Role, text: &str) -> ChatMessage {
    ChatMessage {
        role,
        content: Some(Content::Text(text.to_owned())),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Default::default(),
    }
}

#[test]
fn the_conversation_is_redacted_before_it_leaves() {
    let mut call = text_message(Role::Assistant, "calling");
    call.tool_calls.push(ToolCall {
        index: None,
        id: Some("c1".to_owned()),
        kind: Default::default(),
        function: ToolCallFunction {
            name: "Bash".to_owned(),
            arguments: format!(r#"{{"command":"curl -H 'Authorization: Bearer {OPENAI}x' host"}}"#),
            extra: Default::default(),
        },
        extra: Default::default(),
    });
    let messages = vec![
        text_message(Role::User, &format!("my key is {GITHUB}")),
        call,
        text_message(Role::Tool, &format!("output {AWS}")),
    ];
    let before = digest_of(&messages);
    let answer = ModelAnswer::default();
    let mut model =
        RedactingModel::new(ScriptedModel::new([answer]), Arc::new(Redactor::standard()));
    model
        .answer(&ModelRequest {
            messages: &messages,
            note: Some(&format!("plan note {AWS}")),
            tools: &[],
        })
        .expect("answered");
    let seen = &model.inner().seen()[0];
    let sent = serde_json::to_string(&seen.messages).expect("json");
    for secret in [GITHUB, AWS, OPENAI] {
        assert!(!sent.contains(secret), "{secret} left in {sent}");
    }
    assert!(sent.contains("calling") && sent.contains("\"c1\""));
    assert!(!seen.note.as_deref().unwrap_or("").contains(AWS));
    // the loop's own conversation and its digest are untouched
    assert_eq!(digest_of(&messages), before);
    assert!(matches!(&messages[0].content, Some(Content::Text(t)) if t.contains(GITHUB)));
}
