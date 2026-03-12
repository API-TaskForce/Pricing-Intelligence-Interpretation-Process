from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

import httpx

from ..config import get_settings
from ..logging import get_logger

logger = get_logger(__name__)

_PERIOD_ALIASES = {
    "millisecond": "ms",
    "milliseconds": "ms",
    "ms": "ms",
    "second": "s",
    "seconds": "s",
    "sec": "s",
    "secs": "s",
    "s": "s",
    "minute": "min",
    "minutes": "min",
    "min": "min",
    "mins": "min",
    "hour": "h",
    "hours": "h",
    "hr": "h",
    "hrs": "h",
    "h": "h",
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "year": "year",
    "years": "year",
}


def _normalise_period_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    normalised = value.strip().lower()
    if not normalised:
        return value

    compact = re.sub(r"\s+", "", normalised)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]+)", compact)
    if not match:
        return compact

    magnitude, unit = match.groups()
    canonical_unit = _PERIOD_ALIASES.get(unit, unit)
    return f"{magnitude}{canonical_unit}"


def _normalise_limit_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_normalise_limit_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    normalised = dict(payload)
    if "period" in normalised:
        normalised["period"] = _normalise_period_value(normalised["period"])
    return normalised


class Prime4APIError(Exception):
    """Raised when Prime4API returns an error response."""


class Prime4APIClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = str(settings.prime4api_base_url).rstrip("/")
        self._client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def min_time(
        self,
        capacity_goal: int,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/min-time?capacity_goal=<n>

        Body: {"rate": Rate|Rate[]|null, "quota": Quota|Quota[]|null}
        Response: {"capacity_goal": int, "min_time": str}
        """
        url = f"{self._base_url}/api/v1/bounded-rate/min-time"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)

        logger.info("prime4api.min_time.request", capacity_goal=capacity_goal)
        try:
            response = await self._client.post(
                url, json=body, params={"capacity_goal": capacity_goal}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            logger.error("prime4api.min_time.http_error", status=exc.response.status_code, detail=detail)
            raise Prime4APIError(f"Prime4API returned {exc.response.status_code}: {detail}") from exc
        except httpx.RequestError as exc:
            logger.error("prime4api.min_time.connection_error", error=str(exc))
            raise Prime4APIError(f"Could not reach Prime4API: {exc}") from exc

        data: Dict[str, Any] = response.json()
        logger.info("prime4api.min_time.success", min_time=data.get("min_time"))
        return data

    async def capacity_at(
        self,
        time: str,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/capacity-at?time=<t>"""
        url = f"{self._base_url}/api/v1/bounded-rate/capacity-at"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(url, body, params={"time": time}, log_name="capacity_at")

    async def capacity_during(
        self,
        end_instant: str,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        start_instant: str = "0ms",
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/capacity-during?end_instant=<e>&start_instant=<s>"""
        url = f"{self._base_url}/api/v1/bounded-rate/capacity-during"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(
            url, body, params={"end_instant": end_instant, "start_instant": start_instant},
            log_name="capacity_during",
        )

    async def quota_exhaustion_threshold(
        self,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/quota-exhaustion-threshold"""
        url = f"{self._base_url}/api/v1/bounded-rate/quota-exhaustion-threshold"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(url, body, log_name="quota_exhaustion_threshold")

    async def rates(
        self,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/rates"""
        url = f"{self._base_url}/api/v1/bounded-rate/rates"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(url, body, log_name="rates")

    async def quotas(
        self,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/quotas"""
        url = f"{self._base_url}/api/v1/bounded-rate/quotas"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(url, body, log_name="quotas")

    async def limits(
        self,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/limits"""
        url = f"{self._base_url}/api/v1/bounded-rate/limits"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(url, body, log_name="limits")

    async def idle_time_period(
        self,
        rate: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        quota: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/bounded-rate/idle-time-period"""
        url = f"{self._base_url}/api/v1/bounded-rate/idle-time-period"
        body: Dict[str, Any] = {}
        if rate is not None:
            body["rate"] = _normalise_limit_payload(rate)
        if quota is not None:
            body["quota"] = _normalise_limit_payload(quota)
        return await self._post(url, body, log_name="idle_time_period")

    async def _post(
        self,
        url: str,
        body: Dict[str, Any],
        log_name: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Shared POST helper with logging and error handling."""
        logger.info(f"prime4api.{log_name}.request", url=url, params=params)
        try:
            response = await self._client.post(url, json=body, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            logger.error(f"prime4api.{log_name}.http_error", status=exc.response.status_code, detail=detail)
            raise Prime4APIError(f"Prime4API returned {exc.response.status_code}: {detail}") from exc
        except httpx.RequestError as exc:
            logger.error(f"prime4api.{log_name}.connection_error", error=str(exc))
            raise Prime4APIError(f"Could not reach Prime4API: {exc}") from exc

        data: Dict[str, Any] = response.json()
        logger.info(f"prime4api.{log_name}.success")
        return data
