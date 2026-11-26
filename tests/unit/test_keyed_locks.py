"""Tests for ``KeyedLocks``: one lock per key, kept only while a task holds or waits for it."""

import asyncio
from contextlib import AsyncExitStack

import pytest

from infrahub_mcp.keyed_locks import KeyedLocks

pytestmark = pytest.mark.anyio


async def test_one_key_serializes_its_holders() -> None:
    locks = KeyedLocks()
    order: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def first() -> None:
        async with locks.hold("a"):
            entered.set()
            await release.wait()
            order.append("first")

    async def second() -> None:
        async with locks.hold("a"):
            order.append("second")

    first_task = asyncio.create_task(first())
    await entered.wait()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0)

    assert locks.users("a") == 2
    assert order == []

    release.set()
    await asyncio.gather(first_task, second_task)

    assert order == ["first", "second"]
    assert len(locks) == 0


async def test_different_keys_do_not_block_each_other() -> None:
    locks = KeyedLocks()
    async with locks.hold("a"):
        async with locks.hold("b"):
            assert locks.in_use("a")
            assert locks.in_use("b")
    assert len(locks) == 0


async def test_a_released_lock_with_a_waiter_is_kept_for_that_waiter() -> None:
    """Between ``release()`` and the waiter resuming, a new task for the key must get the same lock."""
    locks = KeyedLocks()
    holder = AsyncExitStack()
    await holder.enter_async_context(locks.hold("a"))
    lock = locks.get("a")
    assert lock is not None

    async def waiter() -> None:
        async with locks.hold("a"):
            pass

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # the waiter parks on the lock

    await holder.aclose()  # releases without letting the waiter resume
    assert not lock.locked()
    assert not waiter_task.done()
    assert locks.get("a") is lock

    await waiter_task
    assert locks.get("a") is None


async def test_an_exception_in_the_block_still_releases_and_drops_the_lock() -> None:
    locks = KeyedLocks()
    with pytest.raises(RuntimeError):
        async with locks.hold("a"):
            raise RuntimeError
    assert len(locks) == 0
