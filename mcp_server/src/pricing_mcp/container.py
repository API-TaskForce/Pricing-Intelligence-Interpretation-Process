from __future__ import annotations

from .clients.prime4api import Prime4APIClient
from .config import get_settings
from .logging import configure_logging, get_logger

logger = get_logger(__name__)


class ServiceContainer:
    def __init__(self) -> None:
        self._settings = get_settings()
        configure_logging(self._settings.log_level)
        self.prime4api_client = Prime4APIClient()

    @property
    def settings(self):
        return self._settings

    async def shutdown(self) -> None:
        await self.prime4api_client.aclose()


container = ServiceContainer()
