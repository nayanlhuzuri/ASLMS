"""A dict-backed stand-in for the few Redis commands the NAPIX token cache uses (design `system-health-inspector`,
"Tests": the `redis_client` seam). Keys expire by a clock the test may move; `fail` makes every command raise."""

from __future__ import annotations

import time
from typing import Any


class RedisStub:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.expires: dict[str, float] = {}
        self.fail = False
        self.offset = 0.0  # seconds added to the clock

    def _now(self) -> float:
        return time.time() + self.offset

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis stub: down")

    def _alive(self, key: str) -> bool:
        at = self.expires.get(key)
        if at is not None and at <= self._now():
            self.data.pop(key, None)
            self.expires.pop(key, None)
        return key in self.data

    def get(self, key: str) -> Any:
        self._check()
        return self.data[key] if self._alive(key) else None

    def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self._check()
        self.data[key] = value if isinstance(value, bytes) else str(value).encode()
        if ex:
            self.expires[key] = self._now() + ex
        else:
            self.expires.pop(key, None)
        return True

    def ttl(self, key: str) -> int:
        self._check()
        if not self._alive(key):
            return -2
        at = self.expires.get(key)
        return -1 if at is None else max(0, int(at - self._now()))

    def delete(self, key: str) -> int:
        self._check()
        self.expires.pop(key, None)
        return 1 if self.data.pop(key, None) is not None else 0

    def hset(self, key: str, mapping: dict[str, Any]) -> int:
        self._check()
        self._alive(key)  # drops an expired hash first
        h = self.data.setdefault(key, {})
        for k, v in mapping.items():
            h[k.encode()] = str(v).encode()
        return len(mapping)

    def hgetall(self, key: str) -> dict[bytes, bytes]:
        self._check()
        return dict(self.data[key]) if self._alive(key) else {}

    def expire(self, key: str, seconds: int) -> bool:
        self._check()
        if not self._alive(key):
            return False
        self.expires[key] = self._now() + seconds
        return True

    def incr(self, key: str) -> int:
        self._check()
        n = int(self.data[key]) + 1 if self._alive(key) else 1
        self.data[key] = str(n).encode()
        return n

    def dump(self) -> str:
        """Everything held, as text (for the no-secret checks)."""
        return repr(self.data)
