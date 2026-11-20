"""Canonical typed configuration schemas for LARIS: the runtime sections (agent, context, model
service, vault, brain, learning, prompts, security). Strict Pydantic V2 validation.
"""

from pydantic import BaseModel, ConfigDict, Field

from laris.shared.config.runtime_schemas import (
    AgentConfig,
    AppConfig,
    BrainConfig,
    ContextConfig,
    LearningConfig,
    ModelApiConfig,
    ModelServiceConfig,
    PromptConfig,
    SecurityConfig,
    ServingConfig,
    VaultConfig,
)


class LarisConfig(BaseModel):
    """Root configuration object uniting all system subsystems."""

    model_config = ConfigDict(protected_namespaces=())

    config_version: str = Field(default="1.0.0")
    environment: str = Field(default="development")
    agent: AgentConfig = Field(default_factory=AgentConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    model_api: ModelApiConfig = Field(default_factory=ModelApiConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    serving: ServingConfig = Field(default_factory=ServingConfig)
    model_service: ModelServiceConfig = Field(default_factory=ModelServiceConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    prompts: PromptConfig = Field(default_factory=PromptConfig)
    vault: VaultConfig = Field(default_factory=VaultConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
