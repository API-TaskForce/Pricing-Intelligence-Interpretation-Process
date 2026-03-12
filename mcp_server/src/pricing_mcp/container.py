from __future__ import annotations

from .cache import BaseCache, create_cache
from .clients.amint import AMintClient
from .clients.analysis import AnalysisClient
from .clients.prime4api import Prime4APIClient
from .config import get_settings
from .logging import configure_logging, get_logger
from .workflows.pricing import PricingWorkflow

logger = get_logger(__name__)


class ServiceContainer:
    def __init__(self) -> None:
        self._settings = get_settings()
        configure_logging(self._settings.log_level)
        self.cache: BaseCache = create_cache(
            backend=self._settings.cache_backend,
            redis_url=self._settings.redis_url,
        )
        self.amint_client = AMintClient()
        self.analysis_client = AnalysisClient()
        self.prime4api_client = Prime4APIClient()
        self.workflow = PricingWorkflow(
            amint_client=self.amint_client,
            analysis_client=self.analysis_client,
            cache=self.cache,
        )

    @property
    def settings(self):
        return self._settings

    async def shutdown(self) -> None:
        await self.amint_client.aclose()
        await self.analysis_client.aclose()
        await self.prime4api_client.aclose()
        await self.cache.close()


container = ServiceContainer()
