"""REST API endpoints for Magewell Mini-NMS."""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException

from app.config import get_config, reload_config
from app.models import AlertEvent, DeviceLiveStatus, NmsSummary
from app.routes.events import broadcaster
from app.state import state_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])

# Reference to the poller instance (injected in app lifespan)
_poller_instance = None


def set_poller(poller) -> None:
    global _poller_instance
    _poller_instance = poller


@router.get("/devices", response_model=List[DeviceLiveStatus])
async def list_devices() -> List[DeviceLiveStatus]:
    """Get live status for all configured Magewell devices."""
    return state_manager.get_all_devices()


@router.get("/devices/{device_id}", response_model=DeviceLiveStatus)
async def get_device(device_id: str) -> DeviceLiveStatus:
    """Get live status for a specific Magewell device by ID or IP."""
    dev = state_manager.get_device(device_id)
    if not dev:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found.")
    return dev


@router.get("/summary", response_model=NmsSummary)
async def get_summary() -> NmsSummary:
    """Get overall fleet summary metrics."""
    return state_manager.get_summary()


@router.get("/alerts", response_model=List[AlertEvent])
async def get_alerts(limit: int = 50) -> List[AlertEvent]:
    """Get list of recent system alert events."""
    return state_manager.get_recent_alerts(limit=limit)


@router.post("/alerts/clear")
async def clear_alerts() -> Dict[str, str]:
    """Clear alert history."""
    state_manager.clear_alerts()
    await broadcaster.broadcast("alerts_cleared", {})
    return {"status": "ok", "message": "Alert history cleared."}


@router.post("/reload-config")
async def reload_configuration() -> Dict[str, Any]:
    """Reload devices.yaml from disk and apply to state manager and poller."""
    try:
        new_config = reload_config()
        state_manager.initialize_from_config(new_config)

        if _poller_instance is not None:
            _poller_instance.update_config(new_config)

        # Broadcast updated snapshot to connected SSE clients
        devices = [d.model_dump() for d in state_manager.get_all_devices()]
        summary = state_manager.get_summary().model_dump()
        await broadcaster.broadcast(
            "snapshot",
            {
                "devices": devices,
                "summary": summary,
                "alerts": [a.model_dump() for a in state_manager.get_recent_alerts(20)],
            },
        )

        return {
            "status": "ok",
            "message": f"Successfully reloaded configuration with {len(new_config.devices)} devices.",
            "device_count": len(new_config.devices),
            "interval_seconds": new_config.polling.interval_seconds,
        }
    except Exception as e:
        logger.error(f"Failed to reload configuration: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/poll-now")
async def trigger_poll_now() -> Dict[str, Any]:
    """Trigger an immediate poll cycle of all devices."""
    if _poller_instance is None:
        raise HTTPException(status_code=503, detail="Poller engine is not initialized.")

    statuses = await _poller_instance.poll_all_devices()
    alerts = state_manager.update_batch(statuses)

    devices = [d.model_dump() for d in state_manager.get_all_devices()]
    summary = state_manager.get_summary().model_dump()

    await broadcaster.broadcast(
        "cycle_complete",
        {
            "devices": devices,
            "summary": summary,
        },
    )

    for a in alerts:
        await broadcaster.broadcast("alert", a.model_dump())

    return {
        "status": "ok",
        "polled_count": len(statuses),
        "summary": summary,
    }
