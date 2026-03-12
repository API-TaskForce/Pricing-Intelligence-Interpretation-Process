from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

try:
    from redis.asyncio import Redis  # type: ignore import-not-found
except Exception:  # pragma: no cover - fallback when redis not installed
    Redis = None  

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisType  # pragma: no cover


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class BaseCache:
    async def get(self, key: str) -> Optional[Any]:  # pragma: no cover - interface
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - default no-op
        await asyncio.sleep(0)


class MemoryCache(BaseCache):
    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry.expires_at < time.time():
                self._store.pop(key, None)
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._lock:
            expires_at = time.time() + ttl_seconds
            self._store[key] = CacheEntry(value=value, expires_at=expires_at)


class RedisCache(BaseCache):
    def __init__(self, redis: "RedisType") -> None:
        if Redis is None:  # pragma: no cover - runtime guard when redis not installed
            raise RuntimeError("redis extra not installed")
        self._redis = redis

    async def get(self, key: str) -> Optional[Any]:
        data = await self._redis.get(key)
        if data is None:
            return None
        return data

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def close(self) -> None:
        await self._redis.aclose()


def create_cache(backend: str, redis_url: Optional[str] = None) -> BaseCache:
    if backend == "redis":
        if Redis is None:
            raise RuntimeError("redis extra not available")
        if not redis_url:
            raise ValueError("redis backend requires redis_url")
        client = Redis.from_url(redis_url, decode_responses=True)
        return RedisCache(client)
    return MemoryCache()
