"""Per-key ``asyncio`` locks that exist only while a task holds or waits for them."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@dataclass
class _Slot:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class KeyedLocks:
    """One ``asyncio.Lock`` per key, created on first use and dropped when its last user leaves.

    A user is a task that holds the lock or waits for it. The lock is dropped
    only when no user is left, never when it is merely unlocked:
    ``asyncio.Lock.locked()`` is ``False`` between a ``release()`` and the
    woken waiter resuming, and dropping the lock then would give a new task
    for the same key a second lock. A lock nobody holds or waits for carries
    no state, so dropping it loses nothing, and the map holds only the keys
    in use. Keys are often caller input (branch names, session keys), so
    keeping unused locks would grow the map without bound.

    No guard lock is needed: there is no ``await`` between the lookup and the
    user count increment, nor between the release and the decrement, and
    asyncio runs one task at a time on the loop.
    """

    __slots__ = ("_slots",)

    def __init__(self) -> None:
        self._slots: dict[str, _Slot] = {}

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncGenerator[None]:
        """Hold *key*'s lock for the block."""
        slot = self._slots.get(key)
        if slot is None:
            slot = _Slot()
            self._slots[key] = slot
        slot.users += 1
        try:
            async with slot.lock:
                yield
        finally:
            slot.users -= 1
            if not slot.users:
                del self._slots[key]

    def in_use(self, key: str) -> bool:
        """Return True while a task holds or waits for *key*'s lock."""
        return key in self._slots

    def users(self, key: str) -> int:
        """Return how many tasks hold or wait for *key*'s lock."""
        slot = self._slots.get(key)
        return slot.users if slot is not None else 0

    def get(self, key: str) -> asyncio.Lock | None:
        """Return *key*'s lock while it is in use, else ``None``."""
        slot = self._slots.get(key)
        return slot.lock if slot is not None else None

    def __contains__(self, key: object) -> bool:
        return key in self._slots

    def __len__(self) -> int:
        return len(self._slots)
