"""Build encrypted backup_db.exe for the database backup tool."""
import json
import runpy
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet


TOOL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TOOL_ROOT.parent
BUILD_ROOT = TOOL_ROOT / "build_encrypted"
DIST_ROOT = TOOL_ROOT
MAIN_PATH = TOOL_ROOT / "backup_db.py"
DB_CONFIG_PATH = PROJECT_ROOT / "db_config.py"
DB_CONFIG_JSON_PATH = DIST_ROOT / "db_config.example.json"
LAUNCHER_PATH = BUILD_ROOT / "backup_db_encrypted_launcher.py"
SPEC_PATH = BUILD_ROOT / "backup_db.spec"
EXE_PATH = DIST_ROOT / "backup_db.exe"


def encrypt_text(fernet, path):
    return fernet.encrypt(path.read_text(encoding="utf-8").encode("utf-8"))


def write_config_json():
    if not DB_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"未找到公共数据库配置: {DB_CONFIG_PATH}")

    namespace = runpy.run_path(str(DB_CONFIG_PATH))
    configs = namespace.get("DATABASE_CONFIGS")
    if not isinstance(configs, dict) or not configs:
        raise RuntimeError(f"{DB_CONFIG_PATH} 中缺少有效的 DATABASE_CONFIGS")

    payload = {"DATABASE_CONFIGS": configs}
    for optional_key in ("MAX_DB_RETRIES", "DB_RETRY_DELAY"):
        if optional_key in namespace:
            payload[optional_key] = namespace[optional_key]

    try:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
    except TypeError as exc:
        raise RuntimeError(f"{DB_CONFIG_PATH} 中存在无法写入 JSON 的配置值: {exc}") from exc

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    DB_CONFIG_JSON_PATH.write_text(content + "\n", encoding="utf-8")
    return DB_CONFIG_JSON_PATH


def build_launcher():
    if not MAIN_PATH.is_file():
        raise FileNotFoundError(f"未找到备份工具主脚本: {MAIN_PATH}")

    key = Fernet.generate_key()
    fernet = Fernet(key)
    main_payload = encrypt_text(fernet, MAIN_PATH)

    launcher = f'''# Auto-generated encrypted launcher. Do not edit by hand.
import os
import sys

# These imports make PyInstaller collect the runtime dependencies used by the encrypted payload.
import argparse  # noqa: F401
import contextlib  # noqa: F401
import json  # noqa: F401
import os as _os  # noqa: F401
import pathlib  # noqa: F401
import queue  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401
import socket  # noqa: F401
import subprocess  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import tkinter as tk  # noqa: F401
from datetime import datetime  # noqa: F401
from tkinter import messagebox, scrolledtext, ttk  # noqa: F401
from sqlalchemy import MetaData, create_engine, func, inspect, select, text  # noqa: F401
from sqlalchemy.dialects.mysql import pymysql as _sa_pymysql  # noqa: F401
from sqlalchemy.engine import Engine  # noqa: F401
from sqlalchemy.engine.url import URL, make_url  # noqa: F401
from sqlalchemy.exc import SQLAlchemyError  # noqa: F401
from sqlalchemy.sql.schema import Table  # noqa: F401
import pymysql  # noqa: F401
from cryptography.fernet import Fernet

_KEY = {key!r}
_MAIN_PAYLOAD = {main_payload!r}


def _decrypt(payload):
    return Fernet(_KEY).decrypt(payload).decode('utf-8')


def _run_main(base_dir):
    source = _decrypt(_MAIN_PAYLOAD)
    filename = os.path.join(base_dir, 'db_backup', 'backup_db.py')
    globals_dict = {{
        '__name__': '__main__',
        '__file__': filename,
        '__package__': None,
        '__builtins__': __builtins__,
    }}
    exec(compile(source, filename, 'exec'), globals_dict)


def main():
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
    _run_main(base_dir)


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
    "sqlalchemy.dialects.mysql",
    "sqlalchemy.dialects.mysql.pymysql",
]
hiddenimports += collect_submodules("pymysql")
hiddenimports += collect_submodules("sqlalchemy.dialects.mysql")


a = Analysis(
    [str(BUILD_ROOT / "backup_db_encrypted_launcher.py")],
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
    name="backup_db",
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


def main():
    config_json_path = write_config_json()
    launcher_path = build_launcher()
    spec_path = write_spec()
    print(f"已生成运行时配置: {config_json_path}")
    print(f"已生成加密启动器: {launcher_path}")
    print(f"已生成 PyInstaller 配置: {spec_path}")
    run_pyinstaller()
    print(f"打包完成: {EXE_PATH}")


if __name__ == "__main__":
    main()
