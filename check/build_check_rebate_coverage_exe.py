"""Build encrypted check_rebate_coverage.exe for the rebate coverage checker."""
import shutil
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet


TOOL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TOOL_ROOT.parent
BUILD_ROOT = TOOL_ROOT / "build_encrypted"
DIST_ROOT = TOOL_ROOT / "dist_encrypted"
MAIN_PATH = TOOL_ROOT / "check_rebate_coverage.py"
DB_CONFIG_PATH = PROJECT_ROOT / "db_config.py"
LAUNCHER_PATH = BUILD_ROOT / "check_rebate_coverage_encrypted_launcher.py"
SPEC_PATH = BUILD_ROOT / "check_rebate_coverage.spec"
EXE_PATH = DIST_ROOT / "check_rebate_coverage.exe"


def encrypt_text(fernet, path):
    return fernet.encrypt(path.read_text(encoding="utf-8").encode("utf-8"))


def build_launcher():
    if not MAIN_PATH.is_file():
        raise FileNotFoundError(f"未找到 rebate 覆盖核对主脚本: {MAIN_PATH}")
    if not DB_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"未找到公共数据库配置: {DB_CONFIG_PATH}")

    key = Fernet.generate_key()
    fernet = Fernet(key)
    main_payload = encrypt_text(fernet, MAIN_PATH)
    db_payload = encrypt_text(fernet, DB_CONFIG_PATH)

    launcher = f'''# Auto-generated encrypted launcher. Do not edit by hand.
import os
import sys
import types

# These imports make PyInstaller collect the runtime dependencies used by the encrypted payload.
import argparse  # noqa: F401
import contextlib  # noqa: F401
import dataclasses  # noqa: F401
import datetime  # noqa: F401
import json  # noqa: F401
import pathlib  # noqa: F401
import queue  # noqa: F401
import re  # noqa: F401
import threading  # noqa: F401
import traceback  # noqa: F401
import tkinter as tk  # noqa: F401
from tkinter import messagebox, scrolledtext, ttk  # noqa: F401
from types import SimpleNamespace  # noqa: F401
import mysql.connector  # noqa: F401
from cryptography.fernet import Fernet

_KEY = {key!r}
_DB_CONFIG_PAYLOAD = {db_payload!r}
_MAIN_PAYLOAD = {main_payload!r}


def _decrypt(payload):
    return Fernet(_KEY).decrypt(payload).decode('utf-8')


def _install_db_config(app_dir):
    source = _decrypt(_DB_CONFIG_PAYLOAD)
    module = types.ModuleType('db_config')
    module.__file__ = os.path.join(app_dir, 'db_config.py')
    module.__package__ = ''
    sys.modules['db_config'] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)


def _run_main(app_dir):
    source = _decrypt(_MAIN_PAYLOAD)
    filename = os.path.join(app_dir, 'check', 'check_rebate_coverage.py')
    globals_dict = {{
        '__name__': '__main__',
        '__file__': filename,
        '__package__': None,
        '__builtins__': __builtins__,
    }}
    exec(compile(source, filename, 'exec'), globals_dict)


def main():
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    _install_db_config(app_dir)
    _run_main(app_dir)


if __name__ == '__main__':
    main()
'''
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    LAUNCHER_PATH.write_text(launcher, encoding="utf-8")
    return LAUNCHER_PATH


def write_spec():
    spec = r'''# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

BUILD_ROOT = Path(SPECPATH).resolve()
TOOL_ROOT = BUILD_ROOT.parent
PROJECT_ROOT = TOOL_ROOT.parent

hiddenimports = [
    "mysql.connector",
    "mysql.connector.locales.eng.client_error",
    "mysql.connector.plugins.caching_sha2_password",
    "mysql.connector.plugins.mysql_native_password",
]
hiddenimports += collect_submodules("mysql.connector")


a = Analysis(
    [str(BUILD_ROOT / "check_rebate_coverage_encrypted_launcher.py")],
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
    name="check_rebate_coverage",
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
'''
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(spec, encoding="utf-8")
    return SPEC_PATH


def run_pyinstaller():
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(DIST_ROOT),
            "--workpath",
            str(BUILD_ROOT / "pyinstaller_work"),
            str(SPEC_PATH),
        ],
        cwd=str(BUILD_ROOT),
        check=True,
    )


def cleanup_runtime_settings():
    settings_path = DIST_ROOT / "formation_tool_settings.json"
    profile_dir = DIST_ROOT / "formation_tool_settings"
    if settings_path.exists():
        settings_path.unlink()
        print(f"已移除旧默认配置: {settings_path}")
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
        print(f"已移除旧房间配置目录: {profile_dir}")


def main():
    launcher_path = build_launcher()
    spec_path = write_spec()
    print(f"已生成加密启动器: {launcher_path}")
    print(f"已生成 PyInstaller 配置: {spec_path}")
    run_pyinstaller()
    cleanup_runtime_settings()
    print(f"打包完成: {EXE_PATH}")


if __name__ == "__main__":
    main()
