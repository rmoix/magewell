"""Client i parser de l'API HTTP de Magewell Pro Convert (/mwapi?method=...)."""

from app.magewell.api import (  # noqa: F401
    AuthFailed,
    DeviceUnreachable,
    MagewellSession,
    NotMagewell,
    STATUS_NAMES,
)
