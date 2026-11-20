//! The loop's way to the server: the model (`POST /v1/laris/chat`) and the server's remote tools
//! (`GET /v1/laris/tools`, `POST /v1/laris/tools/{name}`), both through the P1 client.
//!
//! The loop is synchronous and the client is not, so each call runs on a small runtime owned here.

use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use laris_model_client::{ClientError, Interrupt, ModelClient, ReqwestTransport};
use laris_protocol::{
    ChatRequest, Event, Kind, LarisRequest, P1Event, ToolCall, ToolList, ToolRequest, ToolResponse,
    ToolSchema,
};
use laris_tools::{RemoteTools, ToolError};
use serde_json::{Map, Value};
use std::rc::Rc;
use std::sync::Arc;
use tokio::runtime::Runtime;

/// The client both halves share.
pub type Client = Arc<ModelClient<ReqwestTransport>>;

/// A runtime for the blocking calls.
pub fn runtime() -> Result<Arc<Runtime>, String> {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map(Arc::new)
        .map_err(|e| format!("cannot start the network runtime: {e}"))
}

/// The model of the loop: every call is a P1 chat request, answered by a stream that is gathered into one
/// [`ModelAnswer`].
pub struct ServerModel {
    client: Client,
    runtime: Arc<Runtime>,
    session: String,
    progress: Option<Rc<dyn Fn(Event)>>,
}

impl ServerModel {
    /// Reports each stage the server's pipeline ends, and the sources an answer cites, as they arrive.
    pub fn with_progress(mut self, progress: Rc<dyn Fn(Event)>) -> Self {
        self.progress = Some(progress);
        self
    }

    /// A model over `client`; `session` is the id the server groups the requests of this conversation under
    /// (4 to 64 of `A-Za-z0-9_-`).
    pub fn new(client: Client, runtime: Arc<Runtime>, session: &str) -> Self {
        Self {
            client,
            runtime,
            session: session.to_owned(),
            progress: None,
        }
    }
}

impl Model for ServerModel {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let chat = ChatRequest {
            messages: request.messages.to_vec(),
            tools: request.tools.to_vec(),
            stream: true,
            laris: LarisRequest {
                kind: Kind::Turn,
                session_id: Some(self.session.clone()),
                ..LarisRequest::default()
            },
            extra: Map::new(),
        };
        let failed = |e: ClientError| ModelError::Failed(e.to_string());
        self.runtime.block_on(async {
            let mut stream = self
                .client
                .chat(&chat, &Interrupt::new())
                .await
                .map_err(failed)?;
            let mut out = ModelAnswer::default();
            while let Some(event) = stream.next().await.map_err(failed)? {
                match event {
                    P1Event::Chunk(chunk) => {
                        if let (Some(progress), Some(meta)) = (&self.progress, &chunk.laris) {
                            report(progress, meta);
                        }
                        for choice in chunk.choices {
                            if let Some(text) = choice.delta.content {
                                out.text.push_str(&text);
                            }
                            out.tool_calls
                                .extend::<Vec<ToolCall>>(choice.delta.tool_calls);
                        }
                        if chunk.usage.is_some() {
                            out.usage = chunk.usage;
                        }
                    }
                    P1Event::Error(e) => return Err(ModelError::Failed(e.error.message)),
                    P1Event::Done => break,
                }
            }
            Ok(out)
        })
    }
}

/// The server's scientific tools as the registry sees a remote source.
pub struct HttpRemote {
    client: Client,
    runtime: Arc<Runtime>,
    list: Vec<ToolSchema>,
}

impl HttpRemote {
    /// Asks the server which tools it offers.
    pub fn connect(client: Client, runtime: Arc<Runtime>) -> Result<Self, ClientError> {
        let list: ToolList =
            runtime.block_on(client.get_json("/laris/tools", &Interrupt::new()))?;
        Ok(Self {
            client,
            runtime,
            list: list.tools,
        })
    }
}

impl RemoteTools for HttpRemote {
    fn schemas(&self) -> Vec<ToolSchema> {
        self.list.clone()
    }

    fn call(&mut self, name: &str, arguments: &Map<String, Value>) -> Result<Value, ToolError> {
        let body = ToolRequest {
            arguments: arguments.clone(),
            extra: Map::new(),
        };
        let response: ToolResponse = self
            .runtime
            .block_on(self.client.post_json(
                &format!("/laris/tools/{name}"),
                &body,
                &Interrupt::new(),
            ))
            .map_err(|e| ToolError::new("remote_unavailable", e.to_string()))?;
        match (response.result, response.error) {
            (Some(result), None) => Ok(result),
            (None, Some(error)) => Err(ToolError::new(
                error.kind.as_deref().unwrap_or("remote_error"),
                error.message,
            )),
            _ => Err(ToolError::new("remote_unavailable", "an empty answer")),
        }
    }
}

/// The step events and the cited sources of a chunk, as `status` events for the interface.
fn report(progress: &Rc<dyn Fn(Event)>, meta: &laris_protocol::LarisMeta) {
    let status = |kind: &str, value: Value| {
        progress(Event::Status {
            kind: kind.to_owned(),
            data: value.as_object().cloned().unwrap_or_default(),
        });
    };
    for step in &meta.steps {
        status(
            "pipeline",
            serde_json::json!({"stage": step.stage, "outcome": step.outcome, "ms": step.ms, "code": step.code}),
        );
    }
    if !meta.evidence.is_empty() {
        let items: Vec<&str> = meta.evidence.iter().map(|e| e.title.as_str()).collect();
        status("sources", serde_json::json!({ "items": items }));
    }
}
