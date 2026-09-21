"""Central configuration. Everything is env-driven (prefix ``SN_``).

Import :data:`settings` anywhere; it is a process-wide singleton built once at
import time. Tests override via ``strategy_navigator.config.get_settings.cache_clear()``
after patching the environment, or by constructing ``Settings(...)`` directly.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["dev", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- runtime ---
    env: Env = "dev"
    service_name: str = "strategy-navigator"
    log_level: str = "INFO"
    log_json: bool = False

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_root_path: str = ""

    # --- Postgres ---
    database_url: PostgresDsn = PostgresDsn(  # overridden by SN_DATABASE_URL everywhere real
        "postgresql://sn:sn_dev_pw@localhost:5432/strategy_navigator"
    )
    db_pool_min_size: int = 2
    db_pool_max_size: int = 20
    db_statement_timeout_ms: int = 120_000

    # --- LLM ---
    llm_base_url: str = "http://localhost:4010/v1"
    llm_api_key: str = "sk-litellm-CHANGE-ME"
    llm_default_model: str = "deepseek-v4-pro"
    llm_fast_model: str = "deepseek-v4-flash-0731"
    llm_request_timeout_s: int = 1800
    llm_max_retries: int = 3
    llm_concurrency: dict[str, int] = Field(
        default_factory=lambda: {"deepseek-v4-pro": 8, "deepseek-v4-flash-0731": 16}
    )

    # --- Jina ---
    jina_api_key: str = ""
    jina_search_url: str = "https://s.jina.ai/"
    jina_reader_url: str = "https://r.jina.ai/"
    jina_cache_ttl_s: int = 604_800
    jina_timeout_s: int = 45

    # --- backend callbacks ---
    backend_base_url: str = "http://localhost:3000"
    backend_callback_token: str = ""
    backend_callback_timeout_s: int = 30
    backend_callback_max_retries: int = 5

    # --- queue lanes ---
    lane_short_concurrency: int = 4
    lane_long_concurrency: int = 6
    lane_retry_concurrency: int = 4
    run_max_attempts: int = 4

    # --- object storage ---
    s3_bucket: str = ""
    s3_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # --- tracing ---
    otel_exporter_otlp_endpoint: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator("llm_concurrency", mode="before")
    @classmethod
    def _parse_concurrency(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def sqlalchemy_url(self) -> str:
        """asyncpg-free SQLAlchemy URL using psycopg3."""
        return str(self.database_url).replace("postgresql://", "postgresql+psycopg://", 1)

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL for procrastinate / langgraph checkpointer."""
        return str(self.database_url)

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.otel_exporter_otlp_endpoint)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings: Settings = get_settings()
