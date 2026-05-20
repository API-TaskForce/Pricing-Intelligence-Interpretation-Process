from __future__ import annotations

from contextlib import asynccontextmanager

from .clients import MCPWorkflowClient
from .config import get_settings
from .logging import configure_logging, get_logger
from .agent import HarveyAgent

from fastapi import FastAPI

logger = get_logger(__name__)


class ServiceContainer:
    def __init__(self) -> None:
        self._settings = get_settings()
        configure_logging(self._settings.log_level)
        self.mcp_client = MCPWorkflowClient()
        self.agent = HarveyAgent(self.mcp_client)

    @property
    def settings(self):
        return self._settings

    async def shutdown(self) -> None:
        await self.mcp_client.aclose()


container = ServiceContainer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if hasattr(app, "state"):
        app.state.container = container
    yield
    await container.shutdown()
