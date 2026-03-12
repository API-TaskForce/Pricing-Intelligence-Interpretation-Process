from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import AnyHttpUrl, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core service
    app_name: str = Field(default="pricing-intelligence-mcp")
    environment: Literal["local", "development", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # External services
    amint_base_url: AnyHttpUrl = Field(..., description="A-MINT API base URL")
    amint_api_key: Optional[str] = Field(default=None, description="API key for A-MINT if required")

    analysis_base_url: AnyHttpUrl = Field(..., description="Analysis API base URL")
    analysis_api_key: Optional[str] = Field(
        default=None, description="API key for Analysis API if enforced"
    )

    prime4api_base_url: AnyHttpUrl = Field(..., description="Prime4API base URL")

    # Async behaviour
    http_timeout_seconds: float = 60.0
    max_retry_attempts: int = 3
    retry_backoff_seconds: float = 1.5

    # Caching
    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: Optional[str] = Field(default=None, description="Redis connection string")
    cache_ttl_seconds: int = 3600

    # MCP interface
    mcp_server_name: str = "pricing-intelligence"
    mcp_transport: Literal["stdio", "websocket", "sse"] = "stdio"
    http_host: str = "0.0.0.0"
    http_port: int = 8085


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()  # type: ignore[arg-type]
