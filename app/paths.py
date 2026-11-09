"""Resolució de camins compatible amb execució des del codi font i des d'un .exe (PyInstaller).

- RESOURCE_DIR: on viuen els fitxers empaquetats (static/, templates/, config.example.yaml).
- BASE_DIR: on viuen els fitxers de l'usuari (config.yaml, data/). En mode .exe és la carpeta de l'executable.
"""

import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    RESOURCE_DIR = Path(__file__).resolve().parent.parent
    BASE_DIR = RESOURCE_DIR

STATIC_DIR = RESOURCE_DIR / "static"
TEMPLATES_DIR = RESOURCE_DIR / "templates"
EXAMPLE_CONFIG = RESOURCE_DIR / "config.example.yaml"
DEFAULT_CONFIG = BASE_DIR / "config.yaml"
DATA_DIR = BASE_DIR / "data"


def ensure_user_files(config_path: Path) -> None:
    """Crea config.yaml a partir de l'exemple i la carpeta data/ si no existeixen."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config_path.exists() and EXAMPLE_CONFIG.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EXAMPLE_CONFIG, config_path)
