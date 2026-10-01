"""Configuration loader and manager for Magewell Mini-NMS."""

import logging
import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import ValidationError

from app.models import AppConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.environ.get("NMS_CONFIG_PATH", "config/devices.yaml")

_cached_config: Optional[AppConfig] = None


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load and validate configuration from YAML file."""
    global _cached_config
    target_path = Path(config_path or DEFAULT_CONFIG_PATH)

    if not target_path.exists():
        logger.warning(f"Configuration file {target_path} not found. Creating default configuration.")
        default_config = AppConfig()
        _cached_config = default_config
        return default_config

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

        config = AppConfig.model_validate(raw_data)
        logger.info(f"Loaded configuration from {target_path} with {len(config.devices)} devices.")
        _cached_config = config
        return config
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file {target_path}: {e}")
        raise ValueError(f"Invalid YAML syntax in {target_path}: {e}") from e
    except ValidationError as e:
        logger.error(f"Validation error in {target_path}: {e}")
        raise ValueError(f"Configuration validation error: {e}") from e


def get_config() -> AppConfig:
    """Get the currently cached config, loading it if not already loaded."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def reload_config(config_path: Optional[str] = None) -> AppConfig:
    """Force reload configuration from disk."""
    return load_config(config_path)
