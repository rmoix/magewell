"""Aplicació FastAPI."""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__, paths
from app.routes.api import router as api_router
from app.service import Monitor


def create_app(monitor: Monitor, background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await monitor.start(background=background)
        try:
            yield
        finally:
            await monitor.stop()

    app = FastAPI(title="Magewell Mini-NMS", version=__version__, lifespan=lifespan)
    app.state.monitor = monitor
    app.mount("/static", StaticFiles(directory=str(paths.STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(paths.TEMPLATES_DIR))
    app.include_router(api_router)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(request=request, name="index.html", context={"version": __version__})

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    return app


def default_app(config_path: Optional[str] = None) -> FastAPI:
    """Per a `uvicorn app.main:app` en desenvolupament."""
    from pathlib import Path

    from app.config import ConfigManager

    path = Path(config_path) if config_path else paths.DEFAULT_CONFIG
    paths.ensure_user_files(path)
    return create_app(Monitor(ConfigManager(path)))


def __getattr__(name: str):
    # Creació mandrosa: importar app.main no engega res fins que algú demana `app`.
    if name == "app":
        import os

        return default_app(os.environ.get("NMS_CONFIG"))
    raise AttributeError(name)
