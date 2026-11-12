"""Typed configuration for the agent harness, context, security, serving and application.

Every tunable of the runtime lives here and in `configs/default.yaml`; code never embeds these
values. Precedence is defaults, user and project YAML, `LARIS_*` environment, then CLI overrides
(see `laris.shared.config.loader`). Secrets are never stored in YAML: only the *names* of
environment variables.
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApprovalConfig(BaseModel):
    mode: Literal["ask", "auto", "deny"] = Field(default="ask")
    allow_bypass: bool = Field(default=False)  # policy gate for the `bypass` permission mode
    always_ask: List[str] = Field(
        default_factory=lambda: ["write_file", "ingest_path", "save_memory", "save_skill"]
    )


class VerifyConfig(BaseModel):
    require_citations: bool = Field(default=True)
    max_retries: int = Field(default=1, ge=0, le=2)
    citation_tools: List[str] = Field(
        default_factory=lambda: ["search_corpus", "answer_question", "read_file"]
    )


class PlanConfig(BaseModel):
    """Agentic planning: a visible, tracked plan for goals that take several steps."""

    mode: Literal["off", "auto", "always"] = Field(default="auto")
    min_request_words: int = Field(default=12, ge=1)  # `auto`: longer requests count as multi-step
    max_steps: int = Field(default=12, ge=1, le=30)
    step_chars: int = Field(default=240, ge=20)


class ReflectConfig(BaseModel):
    """After each tool result the loop checks progress; a failed or empty step triggers a bounded
    replan, and a goal closes only when its plan is done."""

    enabled: bool = Field(default=True)
    max_replans: int = Field(default=2, ge=0, le=5)
    completion_retries: int = Field(default=2, ge=0, le=3)
    empty_keys: List[str] = Field(
        default_factory=lambda: ["hits", "passages", "results", "matches", "items"]
    )


class AgentConfig(BaseModel):
    """Loop limits. `max_steps` is capped at the orchestration specification ceiling of 10."""

    max_steps: int = Field(default=10, ge=1, le=10)
    time_budget_s: float = Field(default=180.0, gt=0.0)
    max_tool_calls_per_step: int = Field(default=4, ge=1, le=16)
    default_tool_timeout_s: float = Field(default=30.0, gt=0.0)
    tool_timeouts_s: Dict[str, float] = Field(
        default_factory=lambda: {
            "read_file": 120.0,
            "ingest_path": 300.0,
            "answer_question": 120.0,
            "extract_discourse": 60.0,
        }
    )
    read_max_chars: int = Field(default=20000, ge=1000)
    search_hit_chars: int = Field(default=900, ge=100)
    search_max_top_k: int = Field(default=20, ge=1, le=100)
    list_max_entries: int = Field(default=500, ge=1)
    skill_max_chars: int = Field(default=24000, ge=1000)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    plan: PlanConfig = Field(default_factory=PlanConfig)
    reflect: ReflectConfig = Field(default_factory=ReflectConfig)


class ContextConfig(BaseModel):
    """Autocompact is on by default so long sessions never stop at the context limit."""

    enabled: bool = Field(default=True)
    window_tokens: int = Field(default=32768, ge=2048)
    threshold: float = Field(default=0.8, ge=0.3, le=0.95)
    keep_fraction: float = Field(default=0.3, gt=0.0, lt=0.9)
    chars_per_token: float = Field(default=3.5, gt=0.5)
    message_overhead_tokens: int = Field(default=6, ge=0)
    trim_keep_chars: int = Field(default=600, ge=50)
    overflow_hints: List[str] = Field(
        default_factory=lambda: [
            "context length",
            "context window",
            "maximum context",
            "too many tokens",
            "context_length",
        ]
    )


class ModelApiConfig(BaseModel):
    """Where the agent sends model calls. Empty `base_url` selects the built-in offline planner."""

    base_url: str = Field(default="")
    model: str = Field(default="laris-core")
    api_key_env: str = Field(default="")  # name of the environment variable, never the key itself
    ca_file: str = Field(default="")  # PEM of a private server certificate trusted by `laris login`
    timeout_s: float = Field(default=120.0, gt=0.0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    allow_remote: bool = Field(default=False)  # internal prompts may only go to loopback hosts
    internal_url: str = Field(default="")  # server side: the model block (P2), e.g. http://model:8001/v1


class SecurityConfig(BaseModel):
    """Confidentiality and injection defences; none of this is user-editable at runtime."""

    deny_read_globs: List[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.*",
            "**/.env",
            "**/.env.*",
            "**/*.pem",
            "**/*.key",
            "**/id_rsa*",
            "LARIS.md",
            "LARIS.local.md",
            ".laris/LARIS.md",
            ".laris/config*.yaml",
            ".laris/prompts/**",
            ".laris/rules/**",
            ".laris/workflows/**",
            ".laris/brain/**",
            ".laris/integrity.lock",
            "configs/default.yaml",
            ".git/**",
            "**/settings.json",
        ]
    )
    secret_env_markers: List[str] = Field(
        default_factory=lambda: ["KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH"]
    )
    extra_secret_env: List[str] = Field(default_factory=list)
    secret_patterns: List[str] = Field(
        default_factory=lambda: [
            r"sk-[A-Za-z0-9_-]{16,}",
            r"hf_[A-Za-z0-9]{20,}",
            r"gh[pousr]_[A-Za-z0-9]{20,}",
            r"AKIA[0-9A-Z]{16}",
            r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}",
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        ]
    )
    canary_enabled: bool = Field(default=True)
    leak_detection: bool = Field(default=True)
    leak_shingle_words: int = Field(default=7, ge=4, le=20)
    leak_min_shingles: int = Field(default=2, ge=1, le=50)
    leak_max_shingles: int = Field(default=200000, ge=1000)  # memory budget of the detector
    stream_holdback_chars: int = Field(default=160, ge=0, le=2000)
    redact_paths: bool = Field(default=True)
    injection_scan: bool = Field(default=True)
    injection_patterns: List[str] = Field(
        default_factory=lambda: [
            r"ignore (all |any |the )?(previous|prior|above) (instructions|rules|prompts?)",
            r"disregard (all |any |the )?(previous|prior|above)",
            r"(reveal|print|show|repeat|output|leak) (your |the )?"
            r"(system|hidden|internal|developer) (prompt|instructions?|message|rules)",
            r"you are now (in )?(developer|dan|jailbreak|unrestricted)",
            r"bỏ qua (mọi |tất cả )?(chỉ dẫn|hướng dẫn|quy tắc) (trước|ở trên)",
            r"(tiết lộ|in ra|cho tôi xem) (system prompt|chỉ dẫn hệ thống|prompt hệ thống)",
        ]
    )
    expose_internal_info: bool = Field(default=False)

    @field_validator("secret_patterns", "injection_patterns")
    @classmethod
    def _compile(cls, patterns: List[str]) -> List[str]:
        import re

        for pattern in patterns:
            re.compile(pattern)
        return patterns


class ModelServiceConfig(BaseModel):
    """The model block (`laris-model serve`, protocol P2): internal network only, no keys."""

    model_config = ConfigDict(protected_namespaces=())

    host: str = Field(default="127.0.0.1")  # in the compose network the model binds 0.0.0.0
    port: int = Field(default=8001, ge=1, le=65535)
    max_body_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    model_name: str = Field(default="laris-core")  # reported when a backend is configured
    placeholder_name: str = Field(default="laris-placeholder")  # reported by the placeholder
    backend: str = Field(default="")  # package.module:ClassName; empty selects the placeholder
    checkpoint: str = Field(default="")  # encoder checkpoint for /v1/embeddings
    tokenizer_model: str = Field(default="")  # SentencePiece model for that checkpoint
    device: str = Field(default="")  # cuda or cpu; empty selects automatically
    vram_budget_bytes: int = Field(default=15_569_256_448, ge=1)  # 14.5 GiB: the hard ceiling
    vram_margin_bytes: int = Field(default=1_610_612_736, ge=0)  # kept free below the ceiling
    chat_vram_bytes: int = Field(default=1_048_576, ge=1)  # declared size of the chat model
    embed_vram_bytes: int = Field(default=1_048_576, ge=1)  # declared size of the encoder
    gpu_workers: int = Field(default=1, ge=1)  # jobs running on the GPU at the same time
    queue_max_waiting: int = Field(default=64, ge=1)  # beyond this, requests get 503
    queue_wait_timeout_s: float = Field(default=60.0, gt=0.0)  # waiting longer gives 504


class ServingConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    max_body_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    model_name: str = Field(default="laris-core")
    placeholder_name: str = Field(default="laris-placeholder")
    model_concurrency: int = Field(default=4, ge=1)  # calls to the model block at the same time
    trusted_proxies: List[str] = Field(default_factory=list)  # CIDRs allowed to set X-Forwarded-For
    api_key_env: str = Field(default="LARIS_SERVER_KEYS")  # env var with the accepted keys
    allowed_file: str = Field(default="")  # optional file, one key per line
    require_auth: bool = Field(default=True)  # the server refuses to start without keys
    tls_cert_file: str = Field(default="")  # PEM certificate chain; with the identity file: HTTPS
    tls_identity_file: str = Field(default="")  # PEM private key for that certificate
    tls_dir: str = Field(default="~/.laris-server/tls")  # cert.pem + key.pem here turn HTTPS on
    allow_plain_http: bool = Field(default=False)  # plain HTTP is only accepted on loopback
    data_dir: str = Field(default="artifacts/server")  # SQLite file with keys, usage, traces
    database_engine: str = Field(default="sqlite", pattern="^(sqlite|postgres)$")
    database_url_env: str = Field(default="LARIS_DATABASE_URL")  # env var with the PostgreSQL DSN
    database_url_file: str = Field(default="")  # or a file (a Docker secret) holding the DSN
    database_pool_min: int = Field(default=1, ge=1)
    database_pool_max: int = Field(default=10, ge=1)
    database_timeout_s: float = Field(default=10.0, gt=0.0)
    master_env: str = Field(default="LARIS_SERVER_MASTER")  # env var holding the master secret
    master_file: str = Field(default="~/.laris-server/master.secret")  # used when the env is unset
    server_ips: List[str] = Field(default_factory=list)  # extra addresses counted as "the server"
    default_key_label: str = Field(default="default (server only)")
    first_admin_file: str = Field(default="~/.laris-server/default.key")  # 0600; empty: no file
    cache_ttl_s: float = Field(default=5.0, ge=0.0)  # key lookups; a revocation applies within it
    cache_max_entries: int = Field(default=1024, ge=1)
    chars_per_token: float = Field(
        default=4.0, gt=0.0
    )  # token estimate when the backend gives none
    reasoning_tags: List[List[str]] = Field(default_factory=lambda: [["<think>", "</think>"]])
    reasoning_http: bool = Field(default=False)  # serve traces over HTTP (off: local CLI only)
    trace_retention_days: float = Field(default=30.0, gt=0.0)
    usage_retention_days: float = Field(default=90.0, gt=0.0)  # raw usage rows; days stay summed
    retention_interval_s: float = Field(default=3600.0, ge=1.0)  # how often retention runs
    roles: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "user": ["chat", "embed", "models", "workflows", "help", "account"],
            "readonly": ["models", "workflows", "help", "account"],
            "auditor": ["account", "usage.read", "reasoning.read"],
            "admin": [
                "chat", "embed", "models", "workflows", "help", "account",
                "usage.read", "reasoning.read", "keys.manage",
            ],
        }
    )  # fmt: skip
    privileged_roles: List[str] = Field(default_factory=lambda: ["admin", "auditor"])
    privileged_permissions: List[str] = Field(
        default_factory=lambda: ["usage.read", "reasoning.read", "keys.manage"]
    )
    extra_known: List[str] = Field(default_factory=list)  # permissions beyond those in roles


class AppConfig(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8765, ge=1, le=65535)
    workspace: str = Field(default="artifacts/app/workspace")
    chat_dir: str = Field(default="artifacts/chat")
    max_body_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    chunk_words: int = Field(default=140, ge=20)
    min_chunk_words: int = Field(default=20, ge=1)
    search_default_top_k: int = Field(default=5, ge=1)
    search_max_top_k: int = Field(default=50, ge=1)
    rrf_k: int = Field(default=60, ge=1)
    ocr_lang: str = Field(default="eng+vie")
    ocr_max_pages: int = Field(default=50, ge=1)
    allow_write_default: bool = Field(default=False)
    key_env: str = Field(default="LARIS_API_KEY")  # environment variable holding the user API key
    account_file: str = Field(default="~/.laris/.credentials.json")  # key from `laris login`
    users_dir: str = Field(default="users")  # per-key state below app.chat_dir
    # Where the system policy (prompts, rules, workflows, brain) lives: `server` = the model server
    # holds it and the client never has it; `local` = this folder (development and the server
    # itself); `auto` = server when the folder has no `.laris/prompts`.
    settings_file: str = Field(default="")  # global preferences file; empty = per-key space
    policy_source: Literal["auto", "local", "server"] = Field(default="auto")


class VaultConfig(BaseModel):
    """The project vault: an Obsidian-format folder the system keeps in the user's codebase."""

    enabled: bool = Field(default=True)
    dir: str = Field(default="vault")
    index_note: str = Field(default="00 Index")
    auto_record: bool = Field(default=True)  # sources, sessions and answers are written as notes
    inbox_dir: str = Field(default="_inbox")  # proposals wait here and are not retrieved
    max_note_chars: int = Field(default=12000, ge=500)
    index_recent: int = Field(default=20, ge=1, le=200)
    snippet_chars: int = Field(default=240, ge=40)
    cache_dir: str = Field(default="artifacts/vault_cache")  # disposable index cache
    knowledge_dir: str = Field(default="Knowledge")  # user knowledge by domain, inside the vault
    entities: bool = Field(default=True)  # method/dataset/metric/claim notes with spans
    entity_max_chars: int = Field(default=60000, ge=1000)  # text given to the extractor
    entity_max_statements: int = Field(default=20, ge=0, le=200)
    allow_nested: bool = Field(default=False)  # allow a vault inside another Obsidian vault
    backup: bool = Field(default=True)  # copy a note aside before a managed block is rewritten
    max_writes_per_minute: int = Field(default=120, ge=0)  # 0 = unlimited
    max_property_chars: int = Field(default=2000, ge=100)  # lint: longest property value
    max_note_lint_chars: int = Field(default=60000, ge=1000)  # lint: oversize note


class BrainConfig(BaseModel):
    """The system brain: a protected hub tree read by dedicated tools only, never as a whole."""

    enabled: bool = Field(default=True)
    root_note: str = Field(default="Brain Index")
    consult: Literal["auto", "always", "off"] = Field(default="auto")
    max_depth: int = Field(default=3, ge=1, le=6)
    max_children: int = Field(default=10, ge=2, le=30)
    summary_max_chars: int = Field(default=260, ge=40)
    root_budget_chars: int = Field(default=2500, ge=500)
    open_budget_chars: int = Field(default=3500, ge=500)  # one note opened in full
    turn_budget_chars: int = Field(default=6000, ge=1000)  # all brain text returned in a turn
    consult_budget_chars: int = Field(default=2200, ge=500)  # the automatic consult brief
    search_limit: int = Field(default=5, ge=1, le=20)
    knowledge: bool = Field(default=True)  # user knowledge notes join the domain hubs
    knowledge_per_hub: int = Field(default=5, ge=1, le=30)
    knowledge_extract_chars: int = Field(default=20000, ge=1000)
    knowledge_max_claims: int = Field(default=5, ge=0, le=20)
    general_hub: str = Field(default="General")  # folder for knowledge no domain hub matches
    required_properties: List[str] = Field(
        default_factory=lambda: ["type", "domain", "level", "summary"]
    )


class PromptConfig(BaseModel):
    dir: str = Field(default=".laris/prompts")
    rules_dir: str = Field(default=".laris/rules")
    workflows_dir: str = Field(default=".laris/workflows")
    brain_dir: str = Field(default=".laris/brain")  # protected, read by brain tools only
    vault_dir: str = Field(default=".laris/vault")  # note schema registry, under the lock
    integrity_lock: str = Field(default=".laris/integrity.lock")
    integrity: Literal["enforce", "warn", "off"] = Field(default="enforce")
    help_file: str = Field(default=".laris/help/how-to-use.md")  # printed as-is, no model call
    help_commands: List[str] = Field(default_factory=lambda: ["/how-to-use"])
    workflow_max_chars: int = Field(default=6000, ge=500)
    manifest: str = Field(default="manifest.yaml")
    assistant_name: str = Field(default="LARIS")
    reply_language: str = Field(default="Vietnamese")
    instruction_files: List[str] = Field(
        default_factory=lambda: ["LARIS.md", ".laris/LARIS.md", "LARIS.local.md"]
    )
    user_instruction_file: str = Field(default="~/.laris/LARIS.md")
    max_instruction_chars: int = Field(default=14000, ge=1000)
    max_memory_chars: int = Field(default=4000, ge=0)
    skill_roots: List[str] = Field(default_factory=lambda: [".laris/skills", "~/.laris/skills"])
    skills_index_chars: int = Field(default=8000, ge=500)
    memory_dir: str = Field(default=".laris/memory")
    user_preferences_max_chars: int = Field(default=1200, ge=0)


_STOPWORDS = [
    "the", "and", "for", "that", "with", "this", "from", "are", "was", "were", "have", "has",
    "not", "but", "can", "which", "their", "also", "such", "than", "these", "those", "into",
    "một", "những", "của", "và", "là", "có", "được", "trong", "cho", "các", "này", "khi", "với",
]  # fmt: skip


class LearningConfig(BaseModel):
    """What the system learns from use: fine-tune data (local only) and RAG skills."""

    enabled: bool = Field(default=True)  # collect useful interactions for later fine-tuning
    dir: str = Field(default="artifacts/finetune")  # local, git-ignored, never read by tools
    min_answer_chars: int = Field(default=40, ge=1)
    store_tool_results: bool = Field(default=True)
    max_tool_result_chars: int = Field(default=3000, ge=200)
    store_passage_text: bool = Field(default=True)  # false keeps only chunk ids and hashes
    export_min_rating: Literal["none", "up"] = Field(default="none")
    skill_on_ingest: bool = Field(default=False)  # skills only on request
    skill_dir: str = Field(default=".laris/skills")
    knowledge_template: str = Field(default="templates/knowledge_skill.md")  # under prompts.dir
    max_generated_skills: int = Field(default=40, ge=1)
    skill_top_terms: int = Field(default=12, ge=3, le=40)
    skill_max_sources: int = Field(default=15, ge=1, le=100)
    skill_min_term_chars: int = Field(default=4, ge=2)
    skill_min_df: int = Field(default=2, ge=1)
    skill_max_df_ratio: float = Field(default=0.6, gt=0.0, le=1.0)
    skill_stopwords: List[str] = Field(default_factory=lambda: list(_STOPWORDS))
    skill_required_sections: List[str] = Field(
        default_factory=lambda: ["When to use", "Steps", "Output", "Limits"]
    )
    skill_min_body_chars: int = Field(default=200, ge=1)
    skill_protected_patterns: List[str] = Field(
        default_factory=lambda: [
            r"LARIS\.md",
            r"\.laris/(rules|prompts|workflows)",
            r"integrity\.lock",
            r"(^|[\s`/])\.env\b",
        ]
    )
