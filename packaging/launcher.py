"""Punt d'entrada per a PyInstaller (MagewellNMS.exe)."""

import sys

from app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
