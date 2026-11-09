"""Registre d'equips a supervisar: combina els declarats a config.yaml amb els descoberts a la xarxa.

Els equips descoberts es desen a data/inventory.json perquè, després d'un reinici o si un equip s'apaga,
continuï apareixent a la graella (com a OFFLINE) en lloc de desaparèixer.
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.models import AppConfig, Credential, ExpectedState, ManualDevice

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def make_id(ip: str, port: int) -> str:
    return ip if port == 80 else f"{ip}:{port}"


class Target(BaseModel):
    id: str
    ip: str
    port: int = 80
    source: str = "discovered"  # discovered | manual
    serial: Optional[str] = None
    name: Optional[str] = None  # nom forçat des de config.yaml
    location: Optional[str] = None
    credentials: List[Credential] = Field(default_factory=list)
    expected: Optional[ExpectedState] = None
    # Dades recordades (inventari)
    last_name: Optional[str] = None
    last_model: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class Registry:
    def __init__(self, inventory_path: Path):
        self.inventory_path = inventory_path
        self._targets: Dict[str, Target] = {}
        self._config = AppConfig()

    # ------------------------------------------------------------------ persistència
    def load_inventory(self) -> None:
        if not self.inventory_path.exists():
            return
        try:
            items = json.loads(self.inventory_path.read_text(encoding="utf-8"))
            for it in items:
                t = Target.model_validate(it)
                t.source = "discovered"
                self._targets.setdefault(t.id, t)
            logger.info("Inventari carregat: %d equips coneguts.", len(items))
        except Exception as e:
            logger.error("No s'ha pogut llegir %s: %s", self.inventory_path, e)

    def save_inventory(self) -> None:
        items = [
            t.model_dump(include={"id", "ip", "port", "serial", "last_name", "last_model", "first_seen", "last_seen"})
            for t in self._targets.values()
            if t.source == "discovered"
        ]
        try:
            self.inventory_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.inventory_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.inventory_path)
        except Exception as e:
            logger.error("No s'ha pogut desar l'inventari: %s", e)

    # ------------------------------------------------------------------ configuració
    def apply_config(self, config: AppConfig) -> None:
        """Aplica config.yaml: afegeix equips manuals i les sobreescriptures (nom, ubicació, expected...)."""
        self._config = config
        # Els manuals antics que ja no són a la config passen a ser 'discovered' (si es van veure) o s'eliminen.
        for t in list(self._targets.values()):
            if t.source == "manual":
                t.source = "discovered"
                if not t.last_seen:
                    del self._targets[t.id]
            t.name = t.location = t.expected = None
            t.credentials = []

        for md in config.devices:
            if md.ip:
                tid = make_id(md.ip, md.port)
                t = self._targets.get(tid) or Target(id=tid, ip=md.ip, port=md.port)
                t.source = "manual"
                self._targets[tid] = t
        for t in self._targets.values():
            self._apply_overrides(t)
        for md in config.devices:
            if md.ignore and md.ip:
                self._targets.pop(make_id(md.ip, md.port), None)

        days = config.discovery.forget_after_days
        if days > 0:
            limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
            for t in list(self._targets.values()):
                if t.source == "discovered" and t.last_seen and datetime.datetime.fromisoformat(t.last_seen) < limit:
                    del self._targets[t.id]

    def _matches(self, t: Target) -> List[ManualDevice]:
        """Entrades de config.yaml que corresponen a l'equip: primer per IP, després per número de sèrie."""
        by_ip = [md for md in self._config.devices if md.ip and make_id(md.ip, md.port) == t.id]
        by_serial = [
            md for md in self._config.devices
            if md.serial and t.serial and md.serial.strip().upper() == t.serial.strip().upper() and md not in by_ip
        ]
        return by_ip + by_serial

    def _apply_overrides(self, t: Target) -> None:
        matches = self._matches(t)
        if not matches:
            return

        def first(attr):
            return next((getattr(md, attr) for md in matches if getattr(md, attr) is not None), None)

        t.name = first("name")
        t.location = first("location")
        t.expected = first("expected")
        cred = first("credentials")
        t.credentials = [cred] if cred else []

    def is_ignored(self, ip: str, port: int = 80, serial: Optional[str] = None) -> bool:
        for md in self._config.devices:
            if not md.ignore:
                continue
            if md.ip and make_id(md.ip, md.port) == make_id(ip, port):
                return True
            if md.serial and serial and md.serial.strip().upper() == serial.strip().upper():
                return True
        return False

    # ------------------------------------------------------------------ operacions
    def targets(self) -> List[Target]:
        return sorted(self._targets.values(), key=lambda t: (tuple(int(x) for x in t.ip.split(".") if x.isdigit()), t.port))

    def get(self, tid: str) -> Optional[Target]:
        return self._targets.get(tid)

    def credentials_for(self, t: Target) -> List[Credential]:
        return t.credentials + [c for c in self._config.credentials if c not in t.credentials]

    def add_discovered(self, ip: str, port: int) -> bool:
        """Retorna True si l'equip és nou."""
        if self.is_ignored(ip, port):
            return False
        tid = make_id(ip, port)
        if tid in self._targets:
            return False
        t = Target(id=tid, ip=ip, port=port, first_seen=now_iso())
        self._apply_overrides(t)
        self._targets[tid] = t
        self.save_inventory()
        logger.info("Nou equip Magewell descobert: %s", tid)
        return True

    def update_identity(self, tid: str, serial: Optional[str], name: Optional[str], model: Optional[str]) -> List[str]:
        """Actualitza dades conegudes després d'un sondeig correcte.

        Si el mateix número de sèrie apareix amb una altra IP (canvi de DHCP), s'elimina l'entrada antiga.
        Retorna la llista d'IDs eliminats.
        """
        t = self._targets.get(tid)
        if not t:
            return []
        removed: List[str] = []
        changed = (t.serial, t.last_name, t.last_model) != (serial, name, model)
        t.serial, t.last_name, t.last_model = serial or t.serial, name or t.last_name, model or t.last_model
        stamp = now_iso()
        first_contact = t.last_seen is None
        t.last_seen = stamp
        t.first_seen = t.first_seen or stamp
        if serial:
            for other in list(self._targets.values()):
                if other.id != tid and other.serial == serial and other.source == "discovered":
                    logger.info("L'equip %s ha canviat d'IP: %s -> %s", serial, other.id, tid)
                    del self._targets[other.id]
                    removed.append(other.id)
            if changed:
                self._apply_overrides(t)  # pot coincidir per número de sèrie
        if changed or removed or first_contact:
            self.save_inventory()
        return removed

    def forget(self, tid: str) -> bool:
        t = self._targets.get(tid)
        if not t or t.source == "manual":
            return False
        del self._targets[tid]
        self.save_inventory()
        return True
