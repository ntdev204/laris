//! The registry: local and remote tools behind one interface, and what every result goes through.
//!
//! A call is checked against the tool's schema, run, and its result is finished the same way whether the tool is
//! local or remote: a typed error instead of a failure, the output limit, and the untrusted marking. The loop
//! cannot tell them apart (SR-H4; threat TM-25).

use crate::args::validate;
use crate::checkpoints::Rewound;
use crate::context::Context;
use crate::error::ToolError;
use laris_core::ToolRunner;
use laris_protocol::ToolSchema;
use laris_protocol::chat::ToolFunctionSchema;
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::sync::Arc;

type Args = Map<String, Value>;
type Handler = Box<dyn Fn(&Args) -> Result<Value, ToolError> + Send + Sync>;

/// A tool that runs in this process.
pub struct LocalTool {
    schema: ToolSchema,
    writes: bool,
    untrusted: bool,
    handler: Handler,
}

impl LocalTool {
    /// A tool. `writes` marks a tool that changes files or state (the permission rules of T133 ask for it);
    /// `untrusted` marks one whose output carries third-party content.
    pub fn new(
        name: &str,
        description: &str,
        parameters: Value,
        writes: bool,
        untrusted: bool,
        handler: impl Fn(&Args) -> Result<Value, ToolError> + Send + Sync + 'static,
    ) -> Self {
        Self {
            schema: function_schema(name, description, parameters),
            writes,
            untrusted,
            handler: Box::new(handler),
        }
    }
}

/// A `function` tool schema.
pub fn function_schema(name: &str, description: &str, parameters: Value) -> ToolSchema {
    ToolSchema {
        kind: Default::default(),
        function: ToolFunctionSchema {
            name: name.to_owned(),
            description: Some(description.to_owned()),
            parameters: Some(parameters),
            extra: Map::new(),
        },
        extra: Map::new(),
    }
}

/// The tools of another process, such as the model service's remote tools (`POST /v1/laris/tools/{name}`, T149).
pub trait RemoteTools: Send {
    /// The tools offered, with their schemas.
    fn schemas(&self) -> Vec<ToolSchema>;
    /// Runs `name`. A failure is returned as a [`ToolError`] (a transport failure as `remote_unavailable`).
    fn call(&mut self, name: &str, arguments: &Args) -> Result<Value, ToolError>;
}

/// What the registry knows about a tool.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ToolInfo {
    /// Changes files or state: asked about by default.
    pub writes: bool,
    /// Its output carries third-party content.
    pub untrusted: bool,
    /// Runs in another process.
    pub remote: bool,
}

enum Origin {
    Local(usize),
    Remote(usize),
}

/// All tools, offered to the model and run for the loop.
pub struct Registry {
    ctx: Arc<Context>,
    locals: Vec<LocalTool>,
    remotes: Vec<Box<dyn RemoteTools>>,
    schemas: Vec<ToolSchema>,
    index: BTreeMap<String, (Origin, ToolInfo)>,
}

impl Registry {
    /// The six coding tools, `save_memory` and `use_skill` over `ctx`.
    pub fn with_local_tools(ctx: Context) -> Self {
        let ctx = Arc::new(ctx);
        let mut registry = Self {
            ctx: Arc::clone(&ctx),
            locals: Vec::new(),
            remotes: Vec::new(),
            schemas: Vec::new(),
            index: BTreeMap::new(),
        };
        let mut all = crate::files::tools(&ctx);
        all.extend(crate::search::tools(&ctx));
        all.push(crate::bash::tool(&ctx));
        all.extend(crate::memory::tools(&ctx));
        for tool in all {
            registry
                .register(tool)
                .expect("the built-in tool names are distinct");
        }
        registry
    }

    /// Adds a local tool; its name must be new.
    pub fn register(&mut self, tool: LocalTool) -> Result<(), ToolError> {
        let name = tool.schema.function.name.clone();
        self.check_new(&name)?;
        let info = ToolInfo {
            writes: tool.writes,
            untrusted: tool.untrusted,
            remote: false,
        };
        self.schemas.push(tool.schema.clone());
        self.index
            .insert(name, (Origin::Local(self.locals.len()), info));
        self.locals.push(tool);
        Ok(())
    }

    /// Adds the tools of a remote source. Their output is always untrusted, and they are taken to change state
    /// (so they are asked about) until the permission rules say otherwise.
    pub fn add_remote(&mut self, remote: Box<dyn RemoteTools>) -> Result<(), ToolError> {
        let schemas = remote.schemas();
        for schema in &schemas {
            self.check_new(&schema.function.name)?;
        }
        let slot = self.remotes.len();
        for schema in schemas {
            let info = ToolInfo {
                writes: true,
                untrusted: true,
                remote: true,
            };
            self.index
                .insert(schema.function.name.clone(), (Origin::Remote(slot), info));
            self.schemas.push(schema);
        }
        self.remotes.push(remote);
        Ok(())
    }

    fn check_new(&self, name: &str) -> Result<(), ToolError> {
        if self.index.contains_key(name) {
            Err(ToolError::new(
                "duplicate_tool",
                format!("duplicate tool: {name}"),
            ))
        } else {
            Ok(())
        }
    }

    /// The schemas of every tool, local first, in registration order.
    pub fn schemas(&self) -> Vec<ToolSchema> {
        self.schemas.clone()
    }

    /// What is known about `name`.
    pub fn info(&self, name: &str) -> Option<&ToolInfo> {
        self.index.get(name).map(|(_, info)| info)
    }

    /// The context of the local tools.
    pub fn context(&self) -> &Context {
        &self.ctx
    }

    /// Runs a tool and returns its finished result.
    pub fn call(&mut self, name: &str, arguments: &Args) -> Value {
        let Some((origin, info)) = self.index.get(name) else {
            return ToolError::new("unknown_tool", format!("unknown tool: {name}")).to_value();
        };
        let (untrusted, remote) = (info.untrusted, info.remote);
        let schema = self
            .schemas
            .iter()
            .find(|s| s.function.name == name)
            .and_then(|s| s.function.parameters.as_ref());
        if let Some(schema) = schema
            && let Err(error) = validate(schema, arguments)
        {
            return error.to_value();
        }
        let result = match origin {
            Origin::Local(at) => (self.locals[*at].handler)(arguments),
            Origin::Remote(at) => self.remotes[*at].call(name, arguments),
        };
        self.finish(result, untrusted, remote)
    }

    /// The one place a result is finished, for local and remote tools alike.
    fn finish(&self, result: Result<Value, ToolError>, untrusted: bool, remote: bool) -> Value {
        let limit = usize::try_from(self.ctx.limits.result_max_chars).unwrap_or(usize::MAX);
        let (mut value, failed) = match result {
            Ok(value) => (value, false),
            Err(error) => (error.to_value(), true),
        };
        // an error of ours is not third-party text; the error of a remote tool is
        let mark = untrusted && (!failed || remote);
        let text = value.to_string();
        let chars = text.chars().count();
        if chars > limit {
            value = serde_json::json!({
                "truncated": true,
                "chars": chars,
                "preview": text.chars().take(limit).collect::<String>(),
            });
        }
        if mark {
            value = match value {
                Value::Object(mut map) => {
                    map.insert("untrusted".to_owned(), Value::Bool(true));
                    Value::Object(map)
                }
                other => serde_json::json!({"value": other, "untrusted": true}),
            };
        }
        value
    }

    /// Undoes the last `steps` edits (all when `None`): what `/rewind` does. Nothing is written where a tool could
    /// not write.
    pub fn rewind(&self, steps: Option<usize>) -> Result<Vec<Value>, ToolError> {
        let Some(checkpoints) = &self.ctx.checkpoints else {
            return Err(ToolError::new(
                "no_checkpoints",
                "no checkpoints are kept in this session",
            ));
        };
        let memory = self.ctx.memory_dir.as_ref();
        let done: Vec<Rewound> = checkpoints.rewind(steps, |path| {
            self.ctx.scope.writable(path) || memory.is_some_and(|m| path.starts_with(m))
        })?;
        Ok(done
            .iter()
            .map(|r| {
                r.to_value(|p| match memory {
                    Some(m) if p.starts_with(m) => format!(
                        "memory/{}",
                        p.file_name()
                            .map(|n| n.to_string_lossy())
                            .unwrap_or_default()
                    ),
                    _ => self.ctx.scope.display(p),
                })
            })
            .collect())
    }
}

impl ToolRunner for Registry {
    fn run(&mut self, name: &str, arguments: &Args) -> Value {
        self.call(name, arguments)
    }
}
