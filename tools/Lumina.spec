# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

try:
    _TOOLS_DIR = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _TOOLS_DIR = os.path.abspath(os.getcwd())

_APP_DIR = os.path.dirname(_TOOLS_DIR)
_SRC_DIR = os.path.join(_APP_DIR, "src")
_APP_ICON = os.path.join(_APP_DIR, "assets", "Lumina.ico")
_APP_ICON_IMAGE = os.path.join(_APP_DIR, "assets", "Lumina.png")

auto_dim_analysis = Analysis(
    [os.path.join(_SRC_DIR, "auto_dim_screen.py")],
    pathex=[_SRC_DIR],
    binaries=[],
    datas=[
        (_APP_ICON_IMAGE, "assets"),
    ],
    hiddenimports=collect_submodules("pystray") + [
        "brightness_tray_panel",
        "hid",
        "lumina_orientation_service",
        "monitor_rotation",
        "PIL",
        "PIL.Image",
        "pythoncom",
        "tkinter",
        "tkinter.font",
        "tkinter.messagebox",
        "tkinter.ttk",
        "win32com",
        "win32com.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
auto_dim_pyz = PYZ(auto_dim_analysis.pure)

auto_dim_exe = EXE(
    auto_dim_pyz,
    auto_dim_analysis.scripts,
    [],
    exclude_binaries=True,
    name="Lumina",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_APP_ICON,
)

coll = COLLECT(
    auto_dim_exe,
    auto_dim_analysis.binaries,
    auto_dim_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Lumina",
)
