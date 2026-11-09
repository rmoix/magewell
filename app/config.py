"""Càrrega i validació de config.yaml."""

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from app import paths
from app.models import AppConfig

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


class ConfigManager:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else paths.DEFAULT_CONFIG
        self.config: AppConfig = AppConfig()

    def load(self) -> AppConfig:
        if not self.path.exists():
            logger.warning("No s'ha trobat %s; s'utilitza la configuració per defecte.", self.path)
            self.config = AppConfig()
            return self.config
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            self.config = AppConfig.model_validate(raw)
        except yaml.YAMLError as e:
            raise ConfigError(f"Error de sintaxi YAML a {self.path}: {e}") from e
        except ValidationError as e:
            raise ConfigError(f"Configuració no vàlida a {self.path}:\n{e}") from e
        logger.info(
            "Configuració carregada de %s (%d equips declarats, %d credencials).",
            self.path, len(self.config.devices), len(self.config.credentials),
        )
        return self.config
