"""
Thin repository in front of Redis. Agents/orchestrator never touch a redis
client directly — this is the swappable data-access layer from the plan.
Falls back to an in-process dict if REDIS_URL isn't set, so the app runs
without any infra for local dev.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

try:
    import redis.asyncio as redis
except ImportError:  # redis package optional for local dev without infra
    redis = None

_REDIS_URL = os.environ.get("REDIS_URL")
_memory_store: dict[str, Any] = {}


class SearchCacheRepository:
    def __init__(self) -> None:
        self._client = redis.from_url(_REDIS_URL) if (redis and _REDIS_URL) else None

    async def get(self, key: str) -> Optional[Any]:
        if self._client:
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        return _memory_store.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        if self._client:
            await self._client.set(key, json.dumps(value), ex=ttl_seconds)
        else:
            _memory_store[key] = value  # no TTL in the in-memory fallback


cache = SearchCacheRepository()


def cache_key(prefix: str, **params: Any) -> str:
    parts = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{prefix}:{parts}"
