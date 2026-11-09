# -*- mode: python ; coding: utf-8 -*-
# Construcció:  pyinstaller packaging/MagewellNMS.spec --noconfirm
# Resultat:     dist/MagewellNMS/MagewellNMS.exe  (carpeta "onedir": arrenca més ràpid i dona menys
#               falsos positius d'antivirus que un únic .exe autoextraïble)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

hiddenimports = collect_submodules("uvicorn") + collect_submodules("app") + ["ifaddr"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "static"), "static"),
        (str(ROOT / "templates"), "templates"),
        (str(ROOT / "config.example.yaml"), "."),
    ],
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "simulator", "uvloop", "watchfiles", "websockets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MagewellNMS",
    console=True,  # finestra de consola: es veu el log i es tanca el programa tancant-la
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MagewellNMS", upx=False)
