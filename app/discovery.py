"""Descobriment d'equips Magewell a la xarxa local.

Procés:
  1. Determinar les subxarxes a escanejar (config.discovery.subnets o autodetecció de les interfícies del PC).
  2. Escombrat TCP ràpid al port 80 (o els configurats) amb concurrència alta i timeout curt.
  3. Per a cada host amb el port obert: GET /mwapi?method=ping. Si retorna JSON amb "status" -> és un Magewell Pro Convert.
     Si no, es mira si la pàgina principal menciona "Magewell" (models amb una altra API, p. ex. Ultra Encode / Pro Convert IP).

No cal ser administrador ni instal·lar Npcap: només s'obren connexions TCP normals.
"""

import asyncio
import ipaddress
import logging
from typing import Awaitable, Callable, Iterable, List, Optional, Set, Tuple

import httpx

from app.models import DiscoveryConfig, ScanHost

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int], Awaitable[None] | None]


def local_subnets(max_prefix_widen: int = 22) -> List[str]:
    """Subxarxes IPv4 de les interfícies locals (excloent loopback, APIPA i /32).

    Les xarxes més grans que /22 es redueixen a la /24 del PC per no escanejar milers d'IPs.
    """
    try:
        import ifaddr  # dependència petita i pura Python, funciona a Windows/macOS/Linux
    except ImportError:  # pragma: no cover
        logger.warning("ifaddr no instal·lat; no es poden autodetectar subxarxes.")
        return []

    nets: List[str] = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):
                continue  # IPv6
            try:
                addr = ipaddress.IPv4Address(ip.ip)
            except ValueError:
                continue
            if addr.is_loopback or addr.is_link_local or ip.network_prefix >= 31:
                continue
            prefix = ip.network_prefix if ip.network_prefix >= max_prefix_widen else 24
            net = ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False)
            label = f"{net} ({adapter.nice_name})"
            if str(net) not in [n.split(" ")[0] for n in nets]:
                nets.append(label)
    return nets


def expand_targets(specs: Iterable[str], exclude: Iterable[str] = (), max_hosts: int = 4096) -> List[str]:
    """Accepta '192.168.1.0/24', '192.168.1.10-192.168.1.50', '192.168.1.10-50' o una IP sola."""
    excluded: Set[str] = set()
    for e in exclude:
        excluded.update(_expand_one(e))
    out: List[str] = []
    seen: Set[str] = set()
    for spec in specs:
        for ip in _expand_one(spec.split(" ")[0]):
            if ip not in seen and ip not in excluded:
                seen.add(ip)
                out.append(ip)
                if len(out) >= max_hosts:
                    logger.warning("S'ha arribat al límit de %d hosts; la resta no s'escaneja.", max_hosts)
                    return out
    return out


def _expand_one(spec: str) -> List[str]:
    spec = spec.strip()
    if not spec:
        return []
    if "-" in spec:
        start_s, end_s = spec.split("-", 1)
        start = ipaddress.IPv4Address(start_s.strip())
        end_s = end_s.strip()
        if "." not in end_s:
            end_s = ".".join(start_s.strip().split(".")[:3] + [end_s])
        end = ipaddress.IPv4Address(end_s)
        return [str(ipaddress.IPv4Address(i)) for i in range(int(start), int(end) + 1)]
    net = ipaddress.IPv4Network(spec, strict=False)
    if net.num_addresses == 1:
        return [str(net.network_address)]
    return [str(h) for h in net.hosts()]


async def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return True


async def identify(ip: str, port: int, timeout: float = 2.0, transport: Optional[httpx.AsyncBaseTransport] = None) -> ScanHost:
    base = f"http://{ip}" if port == 80 else f"http://{ip}:{port}"
    async with httpx.AsyncClient(base_url=base, timeout=timeout, transport=transport, follow_redirects=True) as c:
        try:
            r = await c.get("/mwapi", params={"method": "ping"})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and isinstance(data.get("status"), int):
                    return ScanHost(ip=ip, port=port, kind="mwapi", detail=f"ping status={data['status']}")
        except Exception:
            pass
        try:
            r = await c.get("/")
            body = r.text[:20000].lower()
            if "magewell" in body:
                return ScanHost(ip=ip, port=port, kind="magewell-other", detail="Magewell amb API no compatible (no /mwapi)")
            title = ""
            if "<title>" in body:
                title = body.split("<title>", 1)[1].split("</title>", 1)[0].strip()[:60]
            return ScanHost(ip=ip, port=port, kind="http", detail=title or f"HTTP {r.status_code}")
        except Exception as e:
            return ScanHost(ip=ip, port=port, kind="http", detail=type(e).__name__)


async def scan(
    cfg: DiscoveryConfig,
    on_progress: Optional[ProgressCb] = None,
) -> Tuple[List[str], int, List[ScanHost]]:
    """Retorna (descripció de subxarxes, nombre de hosts escanejats, hosts trobats)."""
    specs = cfg.subnets or local_subnets()
    if not specs:
        raise RuntimeError("No s'ha pogut determinar cap subxarxa. Defineix discovery.subnets a config.yaml.")
    hosts = expand_targets(specs, cfg.exclude, cfg.max_hosts)
    pairs = [(ip, p) for ip in hosts for p in cfg.ports]
    total = len(pairs)
    logger.info("Escanejant %d hosts (%s) als ports %s...", len(hosts), ", ".join(specs), cfg.ports)

    sem = asyncio.Semaphore(cfg.concurrency)
    done = 0
    open_ports: List[Tuple[str, int]] = []

    async def probe(ip: str, port: int) -> None:
        nonlocal done
        async with sem:
            if await _tcp_open(ip, port, cfg.connect_timeout):
                open_ports.append((ip, port))
        done += 1
        if on_progress and (done % 32 == 0 or done == total):
            res = on_progress(done, total)
            if asyncio.iscoroutine(res):
                await res

    await asyncio.gather(*(probe(ip, p) for ip, p in pairs))

    id_sem = asyncio.Semaphore(16)

    async def ident(ip: str, port: int) -> ScanHost:
        async with id_sem:
            return await identify(ip, port)

    found = await asyncio.gather(*(ident(ip, p) for ip, p in open_ports))
    found = sorted(found, key=lambda h: (h.kind != "mwapi", tuple(int(x) for x in h.ip.split(".")), h.port))
    n_mw = sum(1 for h in found if h.kind == "mwapi")
    logger.info("Escaneig acabat: %d ports oberts, %d equips Magewell compatibles.", len(open_ports), n_mw)
    return specs, len(hosts), found
