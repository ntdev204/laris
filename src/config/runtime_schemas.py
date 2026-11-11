"""Typed configuration for the agent harness, context, security, serving and application.

Every tunable of the runtime lives here and in `configs/default.yaml`; code never embeds these
values. Precedence is defaults, user and project YAML, `LARIS_*` environment, then CLI overrides
(see `config.loader`). Secrets are never stored in YAML: only the *names* of environment variables.
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApprovalConfig(BaseModel):
    mode: Literal["ask", "auto", "deny"] = Field(default="ask")
    always_ask: List[str] = Field(
        default_factory=lambda: ["write_file", "ingest_path", "save_memory", "save_skill"]
    )


class VerifyConfig(BaseModel):
    require_citations: bool = Field(default=True)
    max_retries: int = Field(default=1, ge=0, le=2)
    citation_tools: List[str] = Field(
        default_factory=lambda: ["search_corpus", "answer_question", "read_file"]
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
    timeout_s: float = Field(default=120.0, gt=0.0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    allow_remote: bool = Field(default=False)  # internal prompts may only go to loopback hosts


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


class ServingConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    max_body_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    model_name: str = Field(default="laris-core")
    placeholder_name: str = Field(default="laris-placeholder")
    api_key_env: str = Field(default="")


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
