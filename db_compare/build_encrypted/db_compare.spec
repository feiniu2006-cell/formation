# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

BUILD_ROOT = Path(SPECPATH).resolve()
TOOL_ROOT = BUILD_ROOT.parent
PROJECT_ROOT = TOOL_ROOT.parent

hiddenimports = [
    "mysql.connector",
    "mysql.connector.connection",
    "mysql.connector.cursor",
    "mysql.connector.errors",
    "mysql.connector.locales.eng.client_error",
    "mysql.connector.plugins.caching_sha2_password",
    "mysql.connector.plugins.mysql_native_password",
]
hiddenimports += collect_submodules("mysql.connector")


a = Analysis(
    [str(BUILD_ROOT / "db_compare_encrypted_launcher.py")],
    pathex=[str(BUILD_ROOT), str(TOOL_ROOT), str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="db_compare",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
