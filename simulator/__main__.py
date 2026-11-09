"""Engega una flota d'equips Magewell simulats a 127.0.0.1, un per port.

Ús:
    python -m simulator                 # 10 equips als ports 9001-9010, amb incidències aleatòries
    python -m simulator --calm          # sense incidències
Després, en una altra terminal:
    python -m app --config config.simulator.yaml
"""

import argparse
import asyncio
import logging
import random

import uvicorn

from simulator.device import SimDevice, make_app

log = logging.getLogger("simulator")


EXTRA_SOURCES = ["REGIA (PGM)", "REGIA (PVW)", "REGIA (MULTIVIEW)", "PC-PRESENTACIONS (PowerPoint)"]


def fleet() -> list[SimDevice]:
    devs = _devices()
    for d in devs:
        d.network = devs  # xarxa NDI compartida
        d.extra_sources = list(EXTRA_SOURCES)
    return devs


def _devices() -> list[SimDevice]:
    return [
        SimDevice("encoder", "HDMI Plus", "B312220101001", 1, "SALA-CAM1"),
        SimDevice("encoder", "HDMI Plus", "B312220101002", 2, "SALA-CAM2"),
        SimDevice("encoder", "SDI Plus", "B313220101003", 3, "SALA-CAM3", fmt="1080i50"),
        SimDevice("encoder", "HDMI 4K Plus", "B314220101004", 4, "SALA-PC-PONENT", fmt="1080p59.94"),
        SimDevice("encoder", "HDMI Plus", "B312220101005", 5, "SALA-PC-REGIA", signal=False),
        SimDevice("decoder", "NDI to HDMI", "B401220101006", 6, source="REGIA (PGM)"),
        SimDevice("decoder", "NDI to HDMI", "B401220101007", 7, source="REGIA (PVW)", output_connected=False),
        SimDevice("decoder", "NDI to HDMI 4K", "B402220101008", 8, source="SALA-PC-PONENT", fmt="1080p59.94"),
        SimDevice("decoder", "NDI to SDI", "B403220101009", 9, source="REGIA (PGM)", temp=82.0),
        SimDevice("encoder", "HDMI Plus", "B312220101010", 10, "SALA-AUX", password="secret"),
    ]


async def chaos(devs: list[SimDevice]) -> None:
    """Provoca incidències aleatòries per veure com reacciona el dashboard."""
    while True:
        await asyncio.sleep(random.uniform(6, 14))
        d = random.choice(devs[:9])
        event = random.choice(["signal", "signal", "format", "drops", "hang"])
        if event == "signal":
            d.signal = not d.signal
            log.info("%s: senyal %s", d.serial, "recuperat" if d.signal else "perdut")
        elif event == "format":
            old = d.fmt
            d.fmt = random.choice(["1080p50", "1080p59.94", "720p50"])
            log.info("%s: format %s -> %s", d.serial, old, d.fmt)
        elif event == "drops":
            d.drop_frames = random.randint(1, 5)
            log.info("%s: frames perduts", d.serial)
            await asyncio.sleep(5)
            d.drop_frames = 0
        elif event == "hang":
            d.hang = True
            log.info("%s: no respon durant 15 s", d.serial)
            await asyncio.sleep(15)
            d.hang = False


async def main(base_port: int, calm: bool) -> None:
    devs = fleet()
    servers = []
    for i, d in enumerate(devs):
        port = base_port + i
        cfg = uvicorn.Config(make_app(d), host="127.0.0.1", port=port, log_level="warning", access_log=False)
        servers.append(uvicorn.Server(cfg))
        log.info("Simulant %-8s %-14s %-16s a http://127.0.0.1:%d", d.role, d.model, d.serial, port)
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    if not calm:
        tasks.append(asyncio.create_task(chaos(devs)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-port", type=int, default=9001)
    ap.add_argument("--calm", action="store_true", help="sense incidències aleatòries")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(main(a.base_port, a.calm))
    except KeyboardInterrupt:
        pass
