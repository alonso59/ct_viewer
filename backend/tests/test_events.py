"""API-40 event bus: ids, replay / Last-Event-ID, overflow, close."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Coroutine
from typing import Any

from app.events.bus import QUEUE_MAX, EventBus
from app.events.types import Event

TIMEOUT = 5.0


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(coro, TIMEOUT))


async def take(it: AsyncIterator[Event], n: int) -> list[Event]:
    return [await asyncio.wait_for(anext(it), 1.0) for _ in range(n)]


async def drain(it: AsyncIterator[Event]) -> list[Event]:
    return [e async for e in it]


def test_ids_monotonic_and_seeded_from_clock() -> None:
    before = time.time_ns() // 1000
    bus = EventBus()
    a = bus.publish("p", "project.updated", {"fields": []})
    b = bus.publish("q", "project.updated", {"fields": []})
    assert before <= a.id < b.id == a.id + 1
    assert EventBus().publish("p", "project.updated", {}).id > b.id - 1


def test_no_last_event_id_replays_nothing_then_live() -> None:
    async def body() -> None:
        bus = EventBus()
        bus.publish("p", "project.updated", {"n": 0})
        sub = bus.subscribe("p")
        live = bus.publish("p", "project.updated", {"n": 1})
        bus.publish("other", "project.updated", {"n": 2})
        assert [e.id for e in await take(sub, 1)] == [live.id]
        bus.close()
        assert await drain(sub) == []

    run(body())


def test_replay_after_last_event_id_without_duplicates() -> None:
    async def body() -> None:
        bus = EventBus()
        evs = [bus.publish("p", "job.progress", {"n": i}) for i in range(5)]
        sub = bus.subscribe("p", evs[1].id)
        new = bus.publish("p", "job.progress", {"n": 5})
        got = await take(sub, 4)
        assert [e.id for e in got] == [evs[2].id, evs[3].id, evs[4].id, new.id]
        bus.close()
        assert await drain(sub) == []

    run(body())


def test_unknown_last_event_id_replays_whole_buffer() -> None:
    async def body() -> None:
        bus = EventBus(replay_max=3)
        evs = [bus.publish("p", "job.progress", {"n": i}) for i in range(6)]
        buffered = [e.id for e in evs[3:]]
        for last in (0, evs[0].id, evs[-1].id + 100):  # too old / from a previous process
            sub = bus.subscribe("p", last)
            assert [e.id for e in await take(sub, 3)] == buffered
        # the id just before the oldest buffered one is contiguous: exact replay
        sub = bus.subscribe("p", evs[2].id)
        assert [e.id for e in await take(sub, 3)] == buffered
        # up to date: nothing to replay
        sub = bus.subscribe("p", evs[-1].id)
        bus.close()
        assert await drain(sub) == []

    run(body())


def test_slow_subscriber_is_dropped() -> None:
    async def body() -> None:
        bus = EventBus()
        slow = bus.subscribe("p")
        fast = bus.subscribe("p")
        for i in range(QUEUE_MAX):
            bus.publish("p", "job.progress", {"n": i})
        assert len(await take(fast, QUEUE_MAX)) == QUEUE_MAX
        bus.publish("p", "job.progress", {"n": "overflow"})
        assert bus.subscriber_count("p") == 1
        assert await drain(slow) == []  # ended
        assert (await take(fast, 1))[0].data == {"n": "overflow"}
        bus.close()

    run(body())


def test_close_ends_subscriptions_and_ignores_publishes() -> None:
    async def body() -> None:
        bus = EventBus()
        sub = bus.subscribe("p")
        waiter = asyncio.create_task(drain(sub))
        await asyncio.sleep(0)
        bus.close()
        assert await asyncio.wait_for(waiter, 1.0) == []
        bus.publish("p", "project.updated", {})
        late = bus.subscribe("p", 0)
        assert await drain(late) == []

    run(body())


def test_aclose_unsubscribes() -> None:
    async def body() -> None:
        bus = EventBus()
        sub = bus.subscribe("p")
        assert bus.subscriber_count("p") == 1
        await sub.aclose()  # type: ignore[attr-defined]
        assert bus.subscriber_count("p") == 0
        assert await drain(sub) == []

    run(body())
