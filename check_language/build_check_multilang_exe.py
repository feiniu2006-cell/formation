"""Build encrypted check_multilang_folder.exe for the multilang checker."""
import shutil
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet


TOOL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TOOL_ROOT.parent
BUILD_ROOT = TOOL_ROOT / "build_encrypted"
DIST_ROOT = TOOL_ROOT / "dist_encrypted"
MAIN_PATH = TOOL_ROOT / "check_multilang_folder.py"
SPECIAL_PHRASE_CONFIG_PATH = TOOL_ROOT / "special_phrase_translations.json"
DB_CONFIG_PATH = PROJECT_ROOT / "db_config.py"
LAUNCHER_PATH = BUILD_ROOT / "check_multilang_encrypted_launcher.py"
SPEC_PATH = BUILD_ROOT / "check_multilang_folder.spec"
EXE_PATH = DIST_ROOT / "check_multilang_folder.exe"


def encrypt_text(fernet, path):
    return fernet.encrypt(path.read_text(encoding="utf-8").encode("utf-8"))


def build_launcher():
    if not MAIN_PATH.is_file():
        raise FileNotFoundError(f"未找到多语言检测主脚本: {MAIN_PATH}")
    if not SPECIAL_PHRASE_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"未找到特殊短语配置: {SPECIAL_PHRASE_CONFIG_PATH}")
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
import contextlib  # noqa: F401
import datetime  # noqa: F401
import importlib.util  # noqa: F401
import json  # noqa: F401
import os as _os  # noqa: F401
import pathlib  # noqa: F401
import queue  # noqa: F401
import random  # noqa: F401
import re  # noqa: F401
import string  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import traceback  # noqa: F401
import tkinter as tk  # noqa: F401
from tkinter import filedialog, messagebox, ttk  # noqa: F401
import pymysql  # noqa: F401
import requests  # noqa: F401
import translators  # noqa: F401
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
    filename = os.path.join(app_dir, 'check_multilang_folder.py')
    globals_dict = {{
        '__name__': '__main__',
        '__file__': filename,
        '__package__': None,
        '__builtins__': __builtins__,
    }}
    exec(compile(source, filename, 'exec'), globals_dict)


def main():
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
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
    "pymysql",
    "requests",
    "translators",
]
hiddenimports += collect_submodules("pymysql")
hiddenimports += collect_submodules("requests")
hiddenimports += collect_submodules("translators")


a = Analysis(
    [str(BUILD_ROOT / "check_multilang_encrypted_launcher.py")],
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
    name="check_multilang_folder",
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


def copy_runtime_configs():
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SPECIAL_PHRASE_CONFIG_PATH, DIST_ROOT / SPECIAL_PHRASE_CONFIG_PATH.name)


def main():
    launcher_path = build_launcher()
    spec_path = write_spec()
    print(f"已生成加密启动器: {launcher_path}")
    print(f"已生成 PyInstaller 配置: {spec_path}")
    run_pyinstaller()
    copy_runtime_configs()
    print(f"已复制特殊短语配置: {DIST_ROOT / SPECIAL_PHRASE_CONFIG_PATH.name}")
    print(f"打包完成: {EXE_PATH}")


if __name__ == "__main__":
    main()
