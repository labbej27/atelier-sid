# -*- mode: python ; coding: utf-8 -*-
# Recette PyInstaller, la même sur macOS, Windows et Linux : python -m PyInstaller atelier_sid.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all

datas = [("atelier_sid/bin", "atelier_sid/bin")]
binaries, hiddenimports = [], []
for paquet in ("pyresidfp", "rtmidi", "sounddevice", "_sounddevice_data", "py65", "mido"):
    try:
        d, b, h = collect_all(paquet)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

icone = os.environ.get("ATELIER_ICONE")
a = Analysis(["atelier_sid.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Atelier SID", console=False,
          icon=icone if icone and sys.platform != "darwin" else None)
coll = COLLECT(exe, a.binaries, a.datas, name="Atelier SID")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Atelier SID.app", icon=icone, bundle_identifier="local.atelier-sid.app",
                 info_plist={"CFBundleShortVersionString": "0.1", "NSHighResolutionCapable": True,
                             "LSApplicationCategoryType": "public.app-category.music"})
