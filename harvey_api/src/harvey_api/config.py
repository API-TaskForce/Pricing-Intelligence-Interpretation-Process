from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore[import]


class Settings(BaseSettings):
    """Configuration for the H.A.R.V.E.Y. API service."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core service
    app_name: str = Field(default="harvey-pricing-assistant")
    environment: Literal["local", "development", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    harvey_static_dir: Path = Field(description="Directory that will contain yaml file assets")

    # MCP gateway
    mcp_server_module: str = Field(
        default="pricing_mcp.mcp_server",
        description="Python module path for the Pricing MCP server entrypoint",
    )
    mcp_python_executable: Optional[str] = Field(
        default=None,
        description="Optional override for the Python executable used to launch the MCP server",
    )
    mcp_extra_python_paths: Optional[str] = Field(
        default=None,
        description="Additional os.pathsep-separated paths appended to PYTHONPATH for the MCP server",
    )
    mcp_transport: Literal["stdio", "sse"] = Field(
        default="stdio",
        description="Transport mechanism for connecting to the MCP server",
    )
    mcp_server_url: Optional[str] = Field(
        default=None,
        description="URL for the MCP server when using SSE transport",
    )

    # Async behaviour
    http_timeout_seconds: float = 60.0
    max_retry_attempts: int = 3
    retry_backoff_seconds: float = 1.5

    # LLM
    harvey_llm_key: Optional[str] = Field(
        default=None,
        description="Admin LLM API key loaded from HARVEY_LLM_KEY.",
    )
    openai_model: str = Field(
        default="gpt-5-mini",
        description="OpenAI model to use for H.A.R.V.E.Y. assistant",
    )
    gemini_model: str = Field(
        default="gemini-3.1-flash-lite-preview",
        description="Gemini model used for student requests",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()  # type: ignore[arg-type]
