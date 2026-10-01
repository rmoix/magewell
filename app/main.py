"""FastAPI application for Magewell Mini-NMS."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_config
from app.models import DeviceLiveStatus
from app.poller import DevicePoller
from app.routes.api import router as api_router, set_poller
from app.routes.events import broadcaster, router as events_router
from app.state import state_manager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("magewell-nms")

poller: DevicePoller = None


def handle_device_update(status: DeviceLiveStatus) -> None:
    """Callback triggered whenever a device poll finishes."""
    alert = state_manager.update_device(status)
    # Broadcast single device update to SSE clients in background
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            broadcaster.broadcast("device_update", status.model_dump())
        )
        if alert:
            loop.create_task(
                broadcaster.broadcast("alert", alert.model_dump())
            )
    except RuntimeError:
        pass


def handle_cycle_complete(statuses: List[DeviceLiveStatus]) -> None:
    """Callback triggered when an entire 20-device polling cycle finishes."""
    try:
        loop = asyncio.get_running_loop()
        summary = state_manager.get_summary().model_dump()
        devices = [d.model_dump() for d in state_manager.get_all_devices()]
        loop.create_task(
            broadcaster.broadcast(
                "cycle_complete",
                {
                    "devices": devices,
                    "summary": summary,
                },
            )
        )
    except RuntimeError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager handling startup and shutdown."""
    global poller
    logger.info("Initializing Magewell Mini-NMS...")

    # Load initial config
    config = get_config()
    state_manager.initialize_from_config(config)

    # Initialize poller
    poller = DevicePoller(
        config=config,
        on_device_updated=handle_device_update,
        on_cycle_completed=handle_cycle_complete,
    )
    set_poller(poller)

    # Start poller loop
    poller.start()
    logger.info(f"Poller background task started for {len(config.devices)} units.")

    yield

    # Shutdown
    logger.info("Stopping Magewell Mini-NMS background poller...")
    if poller:
        await poller.stop()
    logger.info("Shutdown complete.")


# Pre-populate state from configuration on startup
initial_config = get_config()
state_manager.initialize_from_config(initial_config)

app = FastAPI(
    title="Magewell Mini-NMS",
    description="Broadcast-oriented mini NMS for Magewell Pro Convert devices",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware for LAN access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Templates
BASE_DIR = Path(__file__).resolve().parent.parent
static_dir = BASE_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir = BASE_DIR / "templates"
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# Include API and Events routers
app.include_router(api_router)
app.include_router(events_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    """Serve the real-time Broadcast NMS Multiviewer dashboard."""
    devices = state_manager.get_all_devices()
    summary = state_manager.get_summary()
    alerts = state_manager.get_recent_alerts(20)
    config = get_config()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "devices": devices,
            "summary": summary,
            "alerts": alerts,
            "polling_interval": config.polling.interval_seconds,
            "total_devices": len(config.devices),
        },
    )
