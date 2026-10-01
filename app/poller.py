"""Concurrent async polling engine for Magewell devices."""

import asyncio
import datetime
import logging
from typing import Callable, List, Optional
import httpx

from app.config import get_config
from app.magewell_client import MagewellClient, parse_signal_data
from app.models import (
    AppConfig,
    DeviceConfig,
    DeviceLiveStatus,
    HealthStatus,
    SignalInfo,
)

logger = logging.getLogger(__name__)


class DevicePoller:
    """Orchestrates concurrent polling of Magewell devices across the network."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        on_device_updated: Optional[Callable[[DeviceLiveStatus], None]] = None,
        on_cycle_completed: Optional[Callable[[List[DeviceLiveStatus]], None]] = None,
    ):
        self.config = config or get_config()
        self.on_device_updated = on_device_updated
        self.on_cycle_completed = on_cycle_completed
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._magewell_client = MagewellClient(
            timeout=self.config.polling.timeout_seconds
        )

    def update_config(self, new_config: AppConfig) -> None:
        """Update polling configuration and reload limits."""
        self.config = new_config
        self._magewell_client = MagewellClient(
            timeout=new_config.polling.timeout_seconds
        )
        if self._semaphore is not None:
            self._semaphore = asyncio.Semaphore(new_config.polling.concurrency_limit)
        logger.info(
            f"Poller config updated: interval={new_config.polling.interval_seconds}s, "
            f"concurrency={new_config.polling.concurrency_limit}"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or initialize persistent HTTP async client with connection pooling."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=25,
                max_connections=50,
                keepalive_expiry=15.0,
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=self.config.polling.timeout_seconds,
                verify=False,
            )
        return self._client

    async def poll_device(self, device: DeviceConfig) -> DeviceLiveStatus:
        """Poll a single device with concurrency bounding and error isolation."""
        semaphore = self._semaphore or asyncio.Semaphore(
            self.config.polling.concurrency_limit
        )

        async with semaphore:
            client = await self._get_client()
            is_online, response_time_ms, telemetry, error_msg = (
                await self._magewell_client.query_device(device, client=client)
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if not is_online:
            status = DeviceLiveStatus(
                id=device.id,
                name=device.name,
                ip=device.ip,
                port=device.port,
                model=device.model,
                role=device.role,
                location=device.location,
                status=HealthStatus.OFFLINE,
                is_online=False,
                response_time_ms=response_time_ms,
                signal=SignalInfo(locked=False),
                expected=device.expected,
                drifts=["Dispositiu desconnectat o no respon (OFFLINE)"],
                last_seen=None,
                last_checked=now_iso,
                error_message=error_msg or "Host unreachable",
            )
        else:
            signal_data = telemetry.get("signal", {})
            device_data = telemetry.get("device", {})
            summary_data = telemetry.get("summary", {})

            signal_info = parse_signal_data(signal_data)

            # Extract hardware metrics
            temp = (
                device_data.get("board-temperature")
                or device_data.get("temperature")
                or device_data.get("temp")
            )
            cpu = device_data.get("cpu-usage") or device_data.get("cpu")
            mem = device_data.get("memory-usage") or device_data.get("memory")
            fw = (
                device_data.get("firmware-version")
                or device_data.get("firmware")
                or device_data.get("version")
            )
            serial = device_data.get("serial-no") or device_data.get("serial")
            ndi_name = (
                summary_data.get("ndi-name")
                or summary_data.get("name")
                or summary_data.get("ndi_name")
            )
            streaming = summary_data.get("streaming") or summary_data.get("is-streaming")

            status = DeviceLiveStatus(
                id=device.id,
                name=device.name,
                ip=device.ip,
                port=device.port,
                model=device.model,
                role=device.role,
                location=device.location,
                status=HealthStatus.OK,  # Will be refined by drift engine
                is_online=True,
                response_time_ms=response_time_ms,
                temperature_c=float(temp) if temp is not None else None,
                cpu_usage=float(cpu) if cpu is not None else None,
                memory_usage=float(mem) if mem is not None else None,
                firmware_version=str(fw) if fw is not None else None,
                serial_no=str(serial) if serial is not None else None,
                ndi_name=str(ndi_name) if ndi_name is not None else None,
                streaming_active=bool(streaming) if streaming is not None else None,
                signal=signal_info,
                expected=device.expected,
                drifts=[],
                last_seen=now_iso,
                last_checked=now_iso,
                error_message=error_msg,
            )

        if self.on_device_updated:
            try:
                self.on_device_updated(status)
            except Exception as e:
                logger.error(f"Error in on_device_updated callback: {e}")

        return status

    async def poll_all_devices(self) -> List[DeviceLiveStatus]:
        """Poll all configured devices concurrently."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.polling.concurrency_limit)

        devices = self.config.devices
        if not devices:
            return []

        tasks = [self.poll_device(dev) for dev in devices]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_statuses: List[DeviceLiveStatus] = []
        for i, res in enumerate(results):
            if isinstance(res, DeviceLiveStatus):
                final_statuses.append(res)
            else:
                dev = devices[i]
                logger.error(f"Unhandled exception polling device {dev.id} ({dev.ip}): {res}")
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                final_statuses.append(
                    DeviceLiveStatus(
                        id=dev.id,
                        name=dev.name,
                        ip=dev.ip,
                        port=dev.port,
                        model=dev.model,
                        role=dev.role,
                        location=dev.location,
                        status=HealthStatus.OFFLINE,
                        is_online=False,
                        signal=SignalInfo(locked=False),
                        expected=dev.expected,
                        drifts=[f"Internal poll error: {res}"],
                        last_seen=None,
                        last_checked=now_iso,
                        error_message=str(res),
                    )
                )

        if self.on_cycle_completed:
            try:
                self.on_cycle_completed(final_statuses)
            except Exception as e:
                logger.error(f"Error in on_cycle_completed callback: {e}")

        return final_statuses

    async def _run_loop(self) -> None:
        """Main continuous polling loop."""
        logger.info(
            f"Starting polling loop for {len(self.config.devices)} devices "
            f"every {self.config.polling.interval_seconds}s"
        )
        while self._running:
            start_time = asyncio.get_running_loop().time()
            try:
                await self.poll_all_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in polling cycle: {e}")

            elapsed = asyncio.get_running_loop().time() - start_time
            sleep_time = max(0.1, self.config.polling.interval_seconds - elapsed)
            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

        logger.info("Polling loop stopped.")

    def start(self) -> None:
        """Start polling loop in background."""
        if not self._running:
            self._running = True
            self._semaphore = asyncio.Semaphore(self.config.polling.concurrency_limit)
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Gracefully stop polling loop and close HTTP connections."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
