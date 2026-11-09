"""Punt d'entrada: `python -m app [serve|scan|capture]` o `MagewellNMS.exe [serve|scan|capture]`."""

import argparse
import asyncio
import datetime
import json
import logging
import logging.handlers
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

from app import __version__, paths

logger = logging.getLogger("magewell-nms")


def setup_logging(verbose: bool = False) -> None:
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    fh = logging.handlers.RotatingFileHandler(paths.DATA_DIR / "nms.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _config_path(args) -> Path:
    p = Path(args.config) if args.config else paths.DEFAULT_CONFIG
    paths.ensure_user_files(p)
    return p


# --------------------------------------------------------------------------- serve
def cmd_serve(args) -> int:
    import uvicorn

    from app.config import ConfigError, ConfigManager
    from app.main import create_app
    from app.service import Monitor

    cfg_path = _config_path(args)
    cm = ConfigManager(cfg_path)
    try:
        cfg = cm.load()
    except ConfigError as e:
        logger.error("%s", e)
        return 2
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"

    print(f"\n  Magewell Mini-NMS v{__version__}")
    print(f"  Configuració: {cfg_path}")
    print(f"  Dades i logs: {paths.DATA_DIR}")
    print(f"  Dashboard:    {url}")
    print("  (Tanca aquesta finestra o prem Ctrl+C per aturar)\n")

    if cfg.server.open_browser and not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # Una config alternativa (p. ex. la del simulador) fa servir una carpeta de dades pròpia.
    data_dir = paths.DATA_DIR if cfg_path.resolve() == paths.DEFAULT_CONFIG.resolve() else paths.DATA_DIR / cfg_path.stem
    app = create_app(Monitor(cm, data_dir=data_dir))
    try:
        uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
    except OSError as e:
        logger.error("No s'ha pogut obrir el port %s: %s. Potser el programa ja s'està executant?", port, e)
        return 3
    return 0


# --------------------------------------------------------------------------- scan
def cmd_scan(args) -> int:
    from app import discovery
    from app.config import ConfigManager

    cfg = ConfigManager(_config_path(args)).load()
    dcfg = cfg.discovery.model_copy()
    if args.subnet:
        dcfg.subnets = args.subnet

    async def run():
        def progress(done, total):
            print(f"\r  Escanejant... {done}/{total}", end="", flush=True)

        targets, n, found = await discovery.scan(dcfg, progress)
        print()
        print(f"\n  Subxarxes: {', '.join(targets)}  ({n} hosts)")
        if not found:
            print("  No s'ha trobat cap host amb el port HTTP obert.")
        for h in found:
            mark = {"mwapi": "MAGEWELL", "magewell-other": "magewell?", "http": "  http   "}[h.kind]
            print(f"  [{mark}] {h.ip}:{h.port}  {h.detail or ''}")
        return 0

    return asyncio.run(run())


# --------------------------------------------------------------------------- capture
def cmd_capture(args) -> int:
    """Desa les respostes JSON de tots els mètodes de lectura de cada equip, per analitzar-les fora de la sala."""
    from app import discovery
    from app.config import ConfigManager
    from app.magewell.api import READ_ONLY_METHODS, MagewellSession
    from app.registry import Registry

    cfg = ConfigManager(_config_path(args)).load()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else paths.DATA_DIR / "captures" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    async def run():
        hosts = []
        if args.ip:
            hosts = [(ip, args.port) for ip in args.ip]
        else:
            reg = Registry(paths.DATA_DIR / "inventory.json")
            reg.load_inventory()
            hosts = [(t.ip, t.port) for t in reg.targets()]
            hosts += [(d.ip, d.port) for d in cfg.devices if d.ip and (d.ip, d.port) not in hosts]
            if not hosts:
                print("  No hi ha equips coneguts: escanejant la xarxa primer...")
                _, _, found = await discovery.scan(cfg.discovery)
                hosts = [(h.ip, h.port) for h in found if h.kind == "mwapi"]
        if not hosts:
            print("  Cap equip per capturar. Usa --ip 192.168.x.y")
            return 1

        for ip, port in hosts:
            print(f"  {ip}:{port} ...", end=" ", flush=True)
            s = MagewellSession(ip, port, cfg.credentials, timeout=5)
            result = {"_host": f"{ip}:{port}", "_captured": stamp, "_tool_version": __version__}
            try:
                try:
                    await s.login()
                    result["_login"] = f"OK ({s.active_credential.username})"
                except Exception as e:
                    result["_login"] = f"ERROR: {e}"
                for method in READ_ONLY_METHODS:
                    try:
                        result[method] = await s.raw(method)
                    except Exception as e:
                        result[method] = {"_error": f"{type(e).__name__}: {e}"}
                await s.logout()
            finally:
                await s.close()
            fname = out_dir / f"{ip.replace('.', '_')}_{port}.json"
            fname.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(result["_login"])

        archive = shutil.make_archive(str(out_dir), "zip", out_dir)
        print(f"\n  Captures desades a: {out_dir}\n  Fitxer comprimit:   {archive}")
        print("  Envia aquest .zip per ajustar el programa als equips reals.")
        return 0

    return asyncio.run(run())


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="MagewellNMS", description="Supervisió d'equips Magewell Pro Convert")
    p.add_argument("--config", help="Camí a config.yaml (per defecte, al costat del programa)")
    p.add_argument("-v", "--verbose", action="store_true", help="Log detallat")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="Engega el dashboard (per defecte)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--no-browser", action="store_true")

    sc = sub.add_parser("scan", help="Escaneja la xarxa i llista els equips trobats")
    sc.add_argument("--subnet", action="append", help="p. ex. 192.168.1.0/24 (es pot repetir)")

    cp = sub.add_parser("capture", help="Desa respostes JSON crues dels equips per diagnosi")
    cp.add_argument("--ip", action="append", help="IP de l'equip (es pot repetir). Sense --ip: tots els coneguts")
    cp.add_argument("--port", type=int, default=80)
    cp.add_argument("--out", help="Carpeta de sortida")

    # Consoles de Windows amb codificació antiga (cp850/cp1252): mai petar per un accent.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(argv)
    if args.cmd is None:
        args = p.parse_args([*argv, "serve"])
    setup_logging(args.verbose)
    handler = {"serve": cmd_serve, "scan": cmd_scan, "capture": cmd_capture}[args.cmd]
    try:
        rc = handler(args)
    except KeyboardInterrupt:
        rc = 0
    except Exception:
        logger.exception("Error fatal")
        rc = 1
    if rc and paths.FROZEN:
        # Amb doble clic a l'.exe, la finestra es tancaria abans de poder llegir l'error.
        input("\nPrem Enter per tancar...")
    return rc


if __name__ == "__main__":
    sys.exit(main())
