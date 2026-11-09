"""Difusió d'esdeveniments a navegadors via Server-Sent Events."""

import asyncio
import json
import logging
from typing import Any, Set

logger = logging.getLogger(__name__)


class Broadcaster:
    def __init__(self) -> None:
        self._subs: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    @staticmethod
    def encode(event_type: str, data: Any) -> str:
        return f"data: {json.dumps({'type': event_type, 'data': data}, default=str, ensure_ascii=False)}\n\n"

    def publish(self, event_type: str, data: Any) -> None:
        if not self._subs:
            return
        msg = self.encode(event_type, data)
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Client massa lent: descartem el missatge més antic.
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    self._subs.discard(q)
