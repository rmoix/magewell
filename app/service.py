"""Orquestrador: bucle de sondeig, escaneig de xarxa i publicació d'esdeveniments."""

import asyncio
import logging
import time
from typing import List, Optional

from app import discovery
from app.config import ConfigManager
from app.events import Broadcaster
from app.models import AppConfig, ScanReport
from app.poller import Poller, TransportFactory, seed_status
from app.registry import Registry, now_iso
from app.routing import Router
from app.state import StateStore
from app import paths

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(
        self,
        config_manager: ConfigManager,
        data_dir=None,
        transport_factory: Optional[TransportFactory] = None,
    ):
        data_dir = data_dir or paths.DATA_DIR
        self.cfg = config_manager
        self.config: AppConfig = AppConfig()
        self.registry = Registry(data_dir / "inventory.json")
        self.state = StateStore(events_log=data_dir / "events.log")
        self.poller = Poller(self.registry, transport_factory)
        self.broadcaster = Broadcaster()
        self.scan_report = ScanReport()
        self.router = Router(self)
        self._poll_now = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self._poll_lock = asyncio.Lock()
        self._scan_lock = asyncio.Lock()
        self.cycle_ms: Optional[float] = None

    # ------------------------------------------------------------------ cicle de vida
    async def start(self, background: bool = True) -> None:
        self.config = self.cfg.load()
        self.registry.load_inventory()
        self.registry.apply_config(self.config)
        self._sync_state()
        if background:
            self._tasks.append(asyncio.create_task(self._poll_loop(), name="poll-loop"))
            self._tasks.append(asyncio.create_task(self._sources_loop(), name="sources-loop"))
            if self.config.discovery.enabled:
                self._tasks.append(asyncio.create_task(self._discovery_loop(), name="discovery-loop"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        self.registry.save_inventory()
        await self.poller.close()

    def _sync_state(self) -> None:
        """Assegura que hi ha un DeviceStatus per a cada target i elimina els que ja no hi són."""
        ids = set()
        for t in self.registry.targets():
            ids.add(t.id)
            if self.state.get(t.id) is None or self.state.get(t.id).id != t.id:
                self.state.upsert(seed_status(t, self.config))
        for d in self.state.all():
            if d.id not in ids:
                self.state.remove(d.id)
                self.poller.forget(d.id)

    # ------------------------------------------------------------------ sondeig
    async def poll_all(self) -> None:
        async with self._poll_lock:
            t0 = time.perf_counter()
            sem = asyncio.Semaphore(self.config.polling.concurrency_limit)
            targets = self.registry.targets()

            async def one(t):
                async with sem:
                    status, raw = await self.poller.poll(t, self.state.get(t.id), self.config)
                alert = self.state.upsert(status, raw)
                if alert:
                    self.broadcaster.publish("alert", alert.model_dump())

            await asyncio.gather(*(one(t) for t in targets))
            self._sync_state()  # canvis d'IP detectats durant el cicle
            self.cycle_ms = round((time.perf_counter() - t0) * 1000)
            self.publish_snapshot("cycle")

    async def _poll_loop(self) -> None:
        while True:
            start = time.monotonic()
            try:
                await self.poll_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error al cicle de sondeig")
            wait = max(0.2, self.config.polling.interval_seconds - (time.monotonic() - start))
            try:
                await asyncio.wait_for(self._poll_now.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            self._poll_now.clear()

    def request_poll(self) -> None:
        self._poll_now.set()

    async def _sources_loop(self) -> None:
        """Refresca la llista de fonts NDI (més espaiat que el sondeig: és una crida més pesada per als equips)."""
        await asyncio.sleep(2)  # deixem que el primer sondeig identifiqui els decoders
        while True:
            try:
                await self.router.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error refrescant les fonts NDI")
            await asyncio.sleep(self.config.routing.refresh_seconds)

    # ------------------------------------------------------------------ descobriment
    async def _discovery_loop(self) -> None:
        if self.config.discovery.on_startup:
            await self.scan()
        while True:
            minutes = self.config.discovery.rescan_minutes
            await asyncio.sleep(max(60.0, minutes * 60) if minutes > 0 else 3600)
            if self.config.discovery.enabled and self.config.discovery.rescan_minutes > 0:
                await self.scan()

    async def scan(self, subnets: Optional[List[str]] = None) -> ScanReport:
        if self._scan_lock.locked():
            return self.scan_report
        async with self._scan_lock:
            cfg = self.config.discovery.model_copy()
            if subnets:
                cfg.subnets = subnets
            self.scan_report = ScanReport(running=True, started=now_iso())
            self.broadcaster.publish("scan", self.scan_report.model_dump())

            async def progress(done: int, total: int) -> None:
                self.scan_report.progress = round(done / total, 3) if total else 1.0
                self.broadcaster.publish("scan", self.scan_report.model_dump())

            try:
                targets, n_hosts, found = await discovery.scan(cfg, progress)
                self.scan_report.targets = targets
                self.scan_report.hosts_scanned = n_hosts
                self.scan_report.found = found
                new = 0
                for h in found:
                    if h.kind == "mwapi" and self.registry.add_discovered(h.ip, h.port):
                        new += 1
                self.scan_report.new_devices = new
                if new:
                    self._sync_state()
                    self.publish_snapshot("devices")
                    self.request_poll()
            except Exception as e:
                logger.exception("Error escanejant la xarxa")
                self.scan_report.error = str(e)
            finally:
                self.scan_report.running = False
                self.scan_report.progress = 1.0
                self.scan_report.finished = now_iso()
                self.broadcaster.publish("scan", self.scan_report.model_dump())
            return self.scan_report

    # ------------------------------------------------------------------ altres
    async def reload_config(self) -> AppConfig:
        self.config = self.cfg.load()  # llança ConfigError si no és vàlida
        self.registry.apply_config(self.config)
        self._sync_state()
        for d in self.state.all():
            t = self.registry.get(d.id)
            if t:
                d.location = t.location
                if t.name:
                    d.name = t.name
        self.publish_snapshot("devices")
        self.request_poll()
        return self.config

    def forget(self, device_id: str) -> bool:
        ok = self.registry.forget(device_id)
        if ok:
            self._sync_state()
            self.publish_snapshot("devices")
        return ok

    def snapshot(self) -> dict:
        return {
            "devices": [d.model_dump() for d in self.state.all()],
            "summary": self.state.summary().model_dump(),
            "alerts": [a.model_dump() for a in self.state.alerts(100)],
            "scan": self.scan_report.model_dump(),
            "routing": self.router.snapshot(),
            "polling_interval": self.config.polling.interval_seconds,
            "cycle_ms": self.cycle_ms,
        }

    def publish_snapshot(self, kind: str = "cycle") -> None:
        data = {
            "devices": [d.model_dump() for d in self.state.all()],
            "summary": self.state.summary().model_dump(),
            "cycle_ms": self.cycle_ms,
        }
        self.broadcaster.publish(kind, data)
