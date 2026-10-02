"""Tests for the workbench SSE event bus."""

import asyncio
import json
import threading

from gmnspy.workbench.events import MAX_QUEUED_EVENTS, EventBus, sse_format


def test_publish_from_another_thread_reaches_subscriber():
    bus = EventBus()

    async def main():
        q = bus.subscribe()
        t = threading.Thread(target=bus.publish, args=({"type": "ping", "n": 1},))
        t.start()
        t.join()
        return await asyncio.wait_for(q.get(), 1)

    assert asyncio.run(main()) == {"type": "ping", "n": 1}


def test_unsubscribe_stops_delivery():
    bus = EventBus()

    async def main():
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.publish({"type": "ping"})
        await asyncio.sleep(0)
        return q.empty(), bus.subscriber_count

    assert asyncio.run(main()) == (True, 0)


def test_publish_with_no_subscribers_is_a_noop():
    EventBus().publish({"type": "ping"})


def test_queue_drops_oldest_when_full():
    bus = EventBus()

    async def main():
        q = bus.subscribe()
        for i in range(MAX_QUEUED_EVENTS + 5):
            bus.publish({"type": "n", "i": i})
        await asyncio.sleep(0)
        return q.qsize(), await q.get()

    qsize, first = asyncio.run(main())
    assert qsize == MAX_QUEUED_EVENTS
    assert first["i"] == 5


def test_sse_format():
    text = sse_format({"type": "state", "x": 1})
    assert text.startswith("event: state\ndata: ") and text.endswith("\n\n")
    assert json.loads(text.split("data: ", 1)[1]) == {"type": "state", "x": 1}
