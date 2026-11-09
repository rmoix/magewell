"""Avaluació de l'estat de salut d'un equip a partir de la telemetria i l'estat esperat."""

from typing import List, Tuple

from app.models import DeviceStatus, ExpectedState, HealthStatus, Role


def merge_expected(defaults: ExpectedState, override: ExpectedState | None) -> ExpectedState:
    """Aplica els camps definits explícitament a l'equip sobre els valors per defecte."""
    if override is None:
        return defaults.model_copy()
    data = defaults.model_dump()
    data.update(override.model_dump(exclude_unset=True))
    return ExpectedState(**data)


def _rate_matches(actual: float, expected: float) -> bool:
    # 59.94 ~ 60 i 29.97 ~ 30 es consideren diferents (és un error típic de configuració), per això tolerància 0.01.
    return abs(actual - expected) < 0.01


def evaluate(dev: DeviceStatus) -> Tuple[HealthStatus, List[str]]:
    """Retorna (estat, llista de problemes en català). No modifica `dev`."""
    exp = dev.expected
    sig = dev.signal
    issues: List[str] = []

    if not dev.is_online:
        return HealthStatus.OFFLINE, [dev.error_message or "No respon a la xarxa"]
    if dev.status == HealthStatus.AUTH_ERROR:
        return HealthStatus.AUTH_ERROR, [dev.error_message or "Error d'autenticació"]

    no_signal = False
    if exp.signal_locked and not sig.locked:
        no_signal = True
        if dev.role == Role.DECODER:
            src = f" ({dev.ndi.name})" if dev.ndi.name else ""
            issues.append(f"No rep vídeo de la font NDI{src}")
        else:
            state = (sig.state or "").lower()
            if state == "locking":
                issues.append("Entrada intentant enganxar senyal (locking)")
            elif state == "unsupported":
                issues.append("Format d'entrada no suportat")
            else:
                issues.append("Sense senyal a l'entrada")

    if sig.locked:
        if exp.width and exp.height and (sig.width, sig.height) != (exp.width, exp.height):
            issues.append(f"Resolució {sig.width}x{sig.height} (esperat {exp.width}x{exp.height})")
        if exp.frame_rate and sig.frame_rate and not _rate_matches(sig.frame_rate, exp.frame_rate):
            issues.append(f"Freqüència {sig.frame_rate:g} (esperat {exp.frame_rate:g})")
        if exp.interlaced is not None and sig.interlaced is not None and exp.interlaced != sig.interlaced:
            issues.append(f"Escaneig {'entrellaçat' if sig.interlaced else 'progressiu'} (no l'esperat)")

    ndi = dev.ndi
    if dev.role == Role.ENCODER:
        if ndi.enabled is False:
            issues.append("Sortida NDI desactivada")
        if exp.ndi_name and ndi.name and exp.ndi_name.strip() != ndi.name.strip():
            issues.append(f"Nom NDI '{ndi.name}' (esperat '{exp.ndi_name}')")
        if exp.min_ndi_clients is not None and ndi.num_clients is not None and ndi.num_clients < exp.min_ndi_clients:
            issues.append(f"Només {ndi.num_clients} receptors NDI (mínim {exp.min_ndi_clients})")
    elif dev.role == Role.DECODER:
        if exp.ndi_source and ndi.name and exp.ndi_source.strip().lower() not in ndi.name.strip().lower():
            issues.append(f"Font NDI '{ndi.name}' (esperat '{exp.ndi_source}')")
        if exp.output_connected and (dev.output_state or "").lower() in ("unconnected", "disconnected"):
            issues.append("Sortida sense pantalla connectada")

    drops = (ndi.video_drop_frames or 0) + (ndi.audio_drop_frames or 0)
    if drops > 0:
        issues.append(f"Frames NDI perduts (últim segon): vídeo {ndi.video_drop_frames or 0}, àudio {ndi.audio_drop_frames or 0}")

    if exp.max_temperature_c is not None and dev.temperature_c is not None and dev.temperature_c > exp.max_temperature_c:
        issues.append(f"Temperatura {dev.temperature_c:.0f}°C (límit {exp.max_temperature_c:.0f}°C)")

    if no_signal:
        return HealthStatus.NO_SIGNAL, issues
    if issues:
        return HealthStatus.WARNING, issues
    return HealthStatus.OK, []
