"""Server-Sent Events (SSE) router and broadcaster for live UI updates."""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Set
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.state import state_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


class EventBroadcaster:
    """Manages active SSE subscriber queues and broadcasts events to all connected clients."""

    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Register a new SSE client queue."""
        q = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        logger.debug(f"New SSE client subscribed. Total active: {len(self._subscribers)}")
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unregister an SSE client queue."""
        self._subscribers.discard(q)
        logger.debug(f"SSE client disconnected. Total active: {len(self._subscribers)}")

    async def broadcast(self, event_type: str, data: Any) -> None:
        """Push an event to all connected subscriber queues non-blockingly."""
        if not self._subscribers:
            return

        payload = {
            "type": event_type,
            "data": data,
        }
        msg = f"data: {json.dumps(payload, default=str)}\n\n"

        dead_queues = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Client is too slow or unresponsive; drop or clear oldest
                try:
                    _ = q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    dead_queues.append(q)

        for dq in dead_queues:
            self._subscribers.discard(dq)


broadcaster = EventBroadcaster()


async def event_generator(request: Request) -> AsyncGenerator[str, None]:
    """Yield SSE messages to the connected client."""
    q = broadcaster.subscribe()
    try:
        # 1. Immediately send initial full snapshot to the newly connected browser
        devices = [d.model_dump() for d in state_manager.get_all_devices()]
        summary = state_manager.get_summary().model_dump()
        alerts = [a.model_dump() for a in state_manager.get_recent_alerts(20)]

        initial_snapshot = {
            "type": "snapshot",
            "data": {
                "devices": devices,
                "summary": summary,
                "alerts": alerts,
            },
        }
        yield f"data: {json.dumps(initial_snapshot, default=str)}\n\n"

        # 2. Stream subsequent updates and periodic heartbeat
        heartbeat_counter = 0
        while True:
            if await request.is_disconnected():
                break

            try:
                msg = await asyncio.wait_for(q.get(), timeout=1.0)
                yield msg
                heartbeat_counter = 0
            except asyncio.TimeoutError:
                heartbeat_counter += 1
                if heartbeat_counter >= 15:
                    # SSE Heartbeat comment to keep HTTP connection alive
                    yield ": keepalive\n\n"
                    heartbeat_counter = 0
    except asyncio.CancelledError:
        pass
    finally:
        broadcaster.unsubscribe(q)


@router.get("/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint streaming real-time NMS telemetry and alarms."""
    return StreamingResponse(
        event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
