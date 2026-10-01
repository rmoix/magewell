"""Async HTTP client for querying Magewell Pro Convert devices."""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple
import httpx

from app.models import DeviceAuth, DeviceConfig, SignalInfo

logger = logging.getLogger(__name__)


def _extract_data(response_json: Any) -> Dict[str, Any]:
    """Helper to extract payload whether nested under 'result' or top-level."""
    if isinstance(response_json, dict):
        if "result" in response_json and isinstance(response_json["result"], dict):
            return response_json["result"]
        return response_json
    return {}


def _parse_frame_rate(raw_fps: Any) -> Optional[float]:
    """Normalize Magewell frame rate which can be 50, 50.0, 5000 (x100), or 50000 (x1000)."""
    if raw_fps is None:
        return None
    try:
        val = float(raw_fps)
        if val <= 0:
            return 0.0
        if val > 10000:
            return round(val / 1000.0, 2)
        if val > 500:
            return round(val / 100.0, 2)
        return round(val, 2)
    except (ValueError, TypeError):
        return None


def parse_signal_data(data: Dict[str, Any]) -> SignalInfo:
    """Parse raw JSON dict into SignalInfo model."""
    locked = bool(
        data.get("signal-locked")
        or data.get("signal_locked")
        or data.get("locked")
        or data.get("valid")
        or False
    )
    width = data.get("width") or data.get("in-width")
    height = data.get("height") or data.get("in-height")
    raw_fps = data.get("frame-rate") or data.get("framerate") or data.get("in-frame-rate")
    frame_rate = _parse_frame_rate(raw_fps)
    color_format = data.get("color-format") or data.get("color_format") or data.get("color-space")
    interlaced = bool(data.get("interlaced") or data.get("is-interlaced") or False)
    aspect_ratio = data.get("aspect-ratio") or data.get("aspect_ratio")

    return SignalInfo(
        locked=locked,
        width=int(width) if width is not None else None,
        height=int(height) if height is not None else None,
        frame_rate=frame_rate,
        color_format=str(color_format) if color_format is not None else None,
        interlaced=interlaced,
        aspect_ratio=str(aspect_ratio) if aspect_ratio is not None else None,
    )


class MagewellClient:
    """Async client to communicate with Magewell Pro Convert devices."""

    def __init__(self, timeout: float = 2.0, verify_ssl: bool = False):
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def _get_auth(self, auth_config: Optional[DeviceAuth]) -> Optional[httpx.Auth]:
        if auth_config and auth_config.username:
            return httpx.BasicAuth(username=auth_config.username, password=auth_config.password)
        return None

    async def fetch_endpoint(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        endpoint: str,
        auth: Optional[httpx.Auth],
    ) -> Optional[Dict[str, Any]]:
        """Fetch a specific API endpoint from a device."""
        url = f"{base_url.rstrip('/')}/apis/{endpoint.lstrip('/')}"
        try:
            resp = await client.get(url, auth=auth, timeout=self.timeout)
            if resp.status_code == 200:
                try:
                    return _extract_data(resp.json())
                except Exception:
                    logger.debug(f"Failed to decode JSON from {url}")
                    return None
            elif resp.status_code == 401:
                logger.warning(f"Authentication failed for {url}")
                return {"_auth_error": True}
            else:
                logger.debug(f"HTTP {resp.status_code} for {url}")
                return None
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RequestError) as e:
            logger.debug(f"Request error for {url}: {e}")
            return None

    async def query_device(
        self,
        device: DeviceConfig,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Tuple[bool, float, Dict[str, Any], Optional[str]]:
        """
        Query all key endpoints of a Magewell device.

        Returns:
            (is_online, response_time_ms, combined_telemetry_dict, error_message)
        """
        base_url = f"http://{device.ip}:{device.port}"
        auth = self._get_auth(device.auth)

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl)
            should_close = True

        start_time = time.perf_counter()
        is_online = False
        error_msg = None
        telemetry: Dict[str, Any] = {}

        try:
            # Query the 3 key Magewell endpoints concurrently
            summary_task = self.fetch_endpoint(client, base_url, "get-summary-info", auth)
            signal_task = self.fetch_endpoint(client, base_url, "get-signal-info", auth)
            device_task = self.fetch_endpoint(client, base_url, "get-device-info", auth)

            summary_res, signal_res, device_res = await asyncio.gather(
                summary_task, signal_task, device_task, return_exceptions=True
            )

            # Check if any succeeded or had auth error
            has_success = False
            for res in (summary_res, signal_res, device_res):
                if isinstance(res, dict):
                    if res.get("_auth_error"):
                        error_msg = "HTTP 401 Unauthorized"
                        is_online = True
                        has_success = True
                    else:
                        has_success = True

            if has_success:
                is_online = True
                if isinstance(summary_res, dict):
                    telemetry["summary"] = summary_res
                if isinstance(signal_res, dict):
                    telemetry["signal"] = signal_res
                if isinstance(device_res, dict):
                    telemetry["device"] = device_res
            else:
                error_msg = "Device unreachable or timeout"

        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            is_online = False
        finally:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            if should_close:
                await client.aclose()

        return is_online, elapsed_ms, telemetry, error_msg
