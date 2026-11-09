"""API REST i canal SSE."""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import ConfigError
from app.routing import RouteError, same_source
from app.service import Monitor

router = APIRouter(prefix="/api", tags=["api"])


def monitor(request: Request) -> Monitor:
    return request.app.state.monitor


@router.get("/devices")
async def list_devices(request: Request):
    return [d.model_dump() for d in monitor(request).state.all()]


@router.get("/devices/{device_id}")
async def get_device(device_id: str, request: Request):
    d = monitor(request).state.get(device_id)
    if not d:
        raise HTTPException(404, f"Equip '{device_id}' no trobat")
    return d.model_dump()


@router.get("/devices/{device_id}/raw")
async def get_device_raw(device_id: str, request: Request):
    """Últimes respostes JSON crues de l'equip (útil per depurar el parser in situ)."""
    m = monitor(request)
    d = m.state.get(device_id)
    if not d:
        raise HTTPException(404, f"Equip '{device_id}' no trobat")
    return m.state.raw(d.id) or {}


@router.delete("/devices/{device_id}")
async def forget_device(device_id: str, request: Request):
    if not monitor(request).forget(device_id):
        raise HTTPException(400, "Només es poden oblidar equips descoberts (els de config.yaml s'han de treure del fitxer).")
    return {"status": "ok"}


@router.get("/summary")
async def summary(request: Request):
    return monitor(request).state.summary().model_dump()


@router.get("/alerts")
async def alerts(request: Request, limit: int = 100):
    return [a.model_dump() for a in monitor(request).state.alerts(limit)]


@router.post("/alerts/clear")
async def clear_alerts(request: Request):
    m = monitor(request)
    m.state.clear_alerts()
    m.broadcaster.publish("alerts_cleared", {})
    return {"status": "ok"}


@router.post("/poll-now")
async def poll_now(request: Request):
    monitor(request).request_poll()
    return {"status": "ok"}


class ScanRequest(BaseModel):
    subnets: Optional[List[str]] = None


@router.post("/discovery/scan")
async def start_scan(request: Request, body: Optional[ScanRequest] = None):
    m = monitor(request)
    if m.scan_report.running:
        return {"status": "running"}
    asyncio.create_task(m.scan(body.subnets if body else None))
    return {"status": "started"}


@router.get("/discovery")
async def scan_report(request: Request):
    return monitor(request).scan_report.model_dump()


@router.get("/routing")
async def routing_state(request: Request):
    """Fonts NDI (Tx). Els receptors (Rx) són els equips amb role=Decoder de /api/devices."""
    return monitor(request).router.snapshot()


@router.post("/routing/refresh")
async def routing_refresh(request: Request):
    await monitor(request).router.refresh()
    return monitor(request).router.snapshot()


class RouteRequest(BaseModel):
    rx: str  # id del decoder
    tx: str  # nom NDI complet de la font


@router.post("/routing/route")
async def routing_route(body: RouteRequest, request: Request):
    try:
        status = await monitor(request).router.route(body.rx, body.tx)
    except RouteError as e:
        raise HTTPException(409, str(e))
    return {"status": "ok", "device": status.model_dump(), "confirmed": same_source(status.ndi.name, body.tx)}


@router.post("/reload-config")
async def reload_config(request: Request):
    try:
        cfg = await monitor(request).reload_config()
    except ConfigError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "devices": len(cfg.devices)}


@router.get("/events")
async def events(request: Request):
    m = monitor(request)

    async def gen():
        q = m.broadcaster.subscribe()
        try:
            yield m.broadcaster.encode("snapshot", m.snapshot())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            m.broadcaster.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
