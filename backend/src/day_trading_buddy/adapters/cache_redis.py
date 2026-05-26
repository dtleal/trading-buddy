"""Redis-backed `CacheStore` implementation."""

from __future__ import annotations

import logging
from typing import Any, cast

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisCacheStore:
    """Async Redis client implementing `core.interfaces.CacheStore`."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any = None

    async def _conn(self) -> Any:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> str | None:
        client = await self._conn()
        value = await client.get(key)
        return cast(str | None, value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        client = await self._conn()
        await client.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        client = await self._conn()
        await client.delete(key)

    async def close(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "aclose", None) or self._client.close
            await close()
            self._client = None
