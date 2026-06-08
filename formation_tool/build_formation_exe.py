"""Build encrypted formation.exe for the formation tool."""
import argparse
import importlib.util
import json
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TOOL_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from formation_tool.db import db_config_utils
from formation_tool.utils import log_utils

BUILD_ROOT = TOOL_ROOT / 'build_encrypted'
DIST_ROOT = TOOL_ROOT / 'dist_encrypted'
MAIN_PATH = TOOL_ROOT / 'process_formation_slots_way_combined.py'
DB_CONFIG_PATH = PROJECT_ROOT / 'db_config.py'
LAUNCHER_PATH = BUILD_ROOT / 'formation_encrypted_launcher.py'
SPEC_PATH = BUILD_ROOT / 'formation.spec'
EXE_NAME = 'formation'
EXE_PATH = DIST_ROOT / f'{EXE_NAME}.exe'
EXTERNAL_DB_CONFIG_NAME = 'db_config.json'
EXTERNAL_DB_CONFIG_EXAMPLE_NAME = 'db_config.example.json'
TEMP_LAUNCHERS = (
    LAUNCHER_PATH,
    BUILD_ROOT / 'slot_encrypted_launcher.py',
)
TEMP_WORK_DIRS = (
    BUILD_ROOT / 'formation_work',
    BUILD_ROOT / 'pyinstaller_work',
)
TEMP_SPEC_FILES = (
    SPEC_PATH,
)
REQUIRED_MODULES = (
    'PyInstaller',
    'cryptography.fernet',
    'mysql.connector',
    'pandas',
    'sqlalchemy',
    'tkinter',
)
PRODUCTION_EXCLUDED_NAMES = {
    'build_formation_exe.py',
    'process_formation_slots_way_combined.py',
    'run_tests.py',
    'test_formation_logic.py',
}
PRODUCTION_EXCLUDED_DIRS = {
    '__pycache__',
    'build',
    'build_encrypted',
    'dist_encrypted',
    'formation_tool_settings',
}


def is_in_excluded_dir(path):
    return any(part in PRODUCTION_EXCLUDED_DIRS for part in path.relative_to(TOOL_ROOT).parts)


def production_module_name(path):
    relative = path.relative_to(TOOL_ROOT).with_suffix('')
    parts = relative.parts
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return 'formation_tool' + ('.' + '.'.join(parts) if parts else '')


def list_package_init_files():
    return sorted(
        path
        for path in TOOL_ROOT.rglob('__init__.py')
        if not is_in_excluded_dir(path)
    )


def list_production_module_files():
    return sorted(
        path
        for path in TOOL_ROOT.rglob('*.py')
        if not is_in_excluded_dir(path)
        and path.name != '__init__.py'
        and not path.name.startswith('test_')
        and path.name not in PRODUCTION_EXCLUDED_NAMES
    )


def get_encrypted_modules():
    return tuple(production_module_name(path) for path in list_production_module_files())


def get_source_compile_targets():
    return (
        MAIN_PATH,
        DB_CONFIG_PATH,
        *list_package_init_files(),
        *list_production_module_files(),
    )


FORMATION_TOOL_ENCRYPTED_MODULES = get_encrypted_modules()
SOURCE_COMPILE_TARGETS = get_source_compile_targets()


def print_encrypted_module_list():
    """Print the modules that will be encrypted into formation.exe."""
    log_utils.emit(f"Encrypted module count: {len(FORMATION_TOOL_ENCRYPTED_MODULES)}")
    for module_name in FORMATION_TOOL_ENCRYPTED_MODULES:
        log_utils.emit(module_name)


def encrypt_text(fernet, path):
    return fernet.encrypt(path.read_text(encoding='utf-8-sig').encode('utf-8'))


def require_build_inputs():
    if not MAIN_PATH.is_file():
        raise FileNotFoundError(f"Missing main script: {MAIN_PATH}")
    if not DB_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Missing shared db_config.py: {DB_CONFIG_PATH}")


def find_missing_modules(module_names):
    """Return import names that are not available in the current Python."""
    missing = []
    for module_name in module_names:
        try:
            if importlib.util.find_spec(module_name) is None:
                missing.append(module_name)
        except (ImportError, AttributeError, ValueError):
            missing.append(module_name)
    return missing


def formation_tool_module_path(module_name):
    """Return the source path for a formation_tool submodule."""
    prefix = 'formation_tool.'
    if not module_name.startswith(prefix):
        raise ValueError(f"Unsupported encrypted module: {module_name}")
    relative_name = module_name[len(prefix):].replace('.', '/')
    return TOOL_ROOT / f'{relative_name}.py'


def collect_module_manifest_errors():
    errors = []
    production_files = list_production_module_files()
    expected_modules = {
        production_module_name(path)
        for path in production_files
    }
    encrypted_modules = set(FORMATION_TOOL_ENCRYPTED_MODULES)
    missing_encrypted = sorted(expected_modules - encrypted_modules)
    extra_encrypted = sorted(encrypted_modules - expected_modules)
    if missing_encrypted:
        errors.append("Encrypted module manifest is missing: " + ", ".join(missing_encrypted))
    if extra_encrypted:
        errors.append("Encrypted module manifest has unexpected modules: " + ", ".join(extra_encrypted))

    expected_compile_targets = {
        MAIN_PATH,
        DB_CONFIG_PATH,
        TOOL_ROOT / '__init__.py',
        *list_package_init_files(),
        *production_files,
    }
    compile_targets = {Path(path) for path in SOURCE_COMPILE_TARGETS}
    missing_compile = sorted(expected_compile_targets - compile_targets, key=str)
    extra_compile = sorted(compile_targets - expected_compile_targets, key=str)
    if missing_compile:
        errors.append("Compile target manifest is missing: " + ", ".join(str(path) for path in missing_compile))
    if extra_compile:
        errors.append("Compile target manifest has unexpected files: " + ", ".join(str(path) for path in extra_compile))
    return errors


def validate_embedded_db_config():
    data = load_embedded_db_config_data()
    db_config_utils.validate_database_configs(data.get('DATABASE_CONFIGS'), 'embedded db_config.py')
    db_config_utils.validate_db_runtime_options(data, 'embedded db_config.py')
    json.dumps(data, ensure_ascii=False)


def validate_optional_external_db_config():
    """Validate editable external db_config.json when it already exists."""
    candidates = [
        DIST_ROOT / EXTERNAL_DB_CONFIG_NAME,
        TOOL_ROOT / EXTERNAL_DB_CONFIG_NAME,
        PROJECT_ROOT / EXTERNAL_DB_CONFIG_NAME,
    ]
    seen = set()
    errors = []
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            embedded_configs = load_embedded_db_config_data().get('DATABASE_CONFIGS', {})
            db_config_utils.validate_database_configs(
                db_config_utils.extract_database_configs(data, str(path)),
                str(path),
                base_configs=embedded_configs,
            )
            db_config_utils.validate_db_runtime_options(data, str(path))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return errors


def compile_sources_for_preflight():
    for path in SOURCE_COMPILE_TARGETS:
        if not path.is_file():
            raise FileNotFoundError(f"Missing source file: {path}")
        py_compile.compile(str(path), doraise=True)


def collect_preflight_errors():
    errors = []
    try:
        require_build_inputs()
    except Exception as exc:
        errors.append(str(exc))

    missing_modules = find_missing_modules(REQUIRED_MODULES)
    if missing_modules:
        errors.append("Missing Python modules: " + ", ".join(missing_modules))

    errors.extend(collect_module_manifest_errors())

    if not errors:
        try:
            compile_sources_for_preflight()
        except Exception as exc:
            errors.append(f"Source compile check failed: {exc}")

    if not errors:
        try:
            validate_embedded_db_config()
        except Exception as exc:
            errors.append(f"Embedded database config check failed: {exc}")

    errors.extend(f"External db_config.json check failed: {item}" for item in validate_optional_external_db_config())
    return errors


def run_preflight_checks():
    """Run build preflight checks and raise with a clear list of problems."""
    log_utils.emit("Running build preflight checks...")
    errors = collect_preflight_errors()
    if errors:
        detail = "\n".join(f"  - {error}" for error in errors)
        raise RuntimeError(f"Build preflight failed:\n{detail}")
    log_utils.emit("Build preflight passed")


def build_launcher():
    require_build_inputs()
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    fernet = Fernet(key)
    main_payload = encrypt_text(fernet, MAIN_PATH)
    db_payload = encrypt_text(fernet, DB_CONFIG_PATH)
    module_payloads = [
        (module_name, encrypt_text(fernet, formation_tool_module_path(module_name)))
        for module_name in FORMATION_TOOL_ENCRYPTED_MODULES
    ]
    module_payloads_repr = "(\n" + "\n".join(
        f"    ({module_name!r}, {payload!r}),"
        for module_name, payload in module_payloads
    ) + "\n)"

    launcher = f'''# Auto-generated encrypted launcher. Do not edit by hand.
import importlib.abc
import importlib.util
import os
import sys
import types

# These imports make PyInstaller collect the runtime dependencies used by the encrypted payload.
import contextlib  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import pathlib  # noqa: F401
import queue  # noqa: F401
import re  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import traceback  # noqa: F401
import tkinter as tk  # noqa: F401
from tkinter import messagebox, scrolledtext, ttk  # noqa: F401
import mysql.connector  # noqa: F401
import pandas as pd  # noqa: F401
from sqlalchemy import create_engine  # noqa: F401
from sqlalchemy.dialects.mysql import mysqlconnector as _sa_mysqlconnector  # noqa: F401
from cryptography.fernet import Fernet

_KEY = {key!r}
_DB_CONFIG_PAYLOAD = {db_payload!r}
_MODULE_PAYLOADS = {module_payloads_repr}
_MAIN_PAYLOAD = {main_payload!r}


def _decrypt(payload):
    return Fernet(_KEY).decrypt(payload).decode('utf-8-sig')


def _ensure_formation_package(base_dir):
    package_dir = os.path.join(base_dir, 'formation_tool')
    package = sys.modules.get('formation_tool')
    if package is None:
        package = types.ModuleType('formation_tool')
        sys.modules['formation_tool'] = package
    package.__file__ = os.path.join(package_dir, '__init__.py')
    package.__path__ = [package_dir]
    package.__package__ = 'formation_tool'
    return package


def _ensure_package(package_name, base_dir):
    if package_name == 'formation_tool':
        return _ensure_formation_package(base_dir)
    package = sys.modules.get(package_name)
    if package is not None:
        return package
    parent_name, _, short_name = package_name.rpartition('.')
    parent = _ensure_package(parent_name, base_dir)
    package_dir = os.path.join(base_dir, *package_name.split('.'))
    package = types.ModuleType(package_name)
    package.__file__ = os.path.join(package_dir, '__init__.py')
    package.__path__ = [package_dir]
    package.__package__ = package_name
    sys.modules[package_name] = package
    setattr(parent, short_name, package)
    return package


class _EncryptedModuleLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, base_dir, payloads):
        self.base_dir = base_dir
        self.payloads = dict(payloads)

    def _filename_for(self, fullname):
        package_name, _, short_name = fullname.rpartition('.')
        module_dir = os.path.join(self.base_dir, *package_name.split('.'))
        return os.path.join(module_dir, short_name + '.py')

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.payloads:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            self,
            origin=self._filename_for(fullname),
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        fullname = module.__name__
        package_name, _, short_name = fullname.rpartition('.')
        filename = self._filename_for(fullname)
        module.__file__ = filename
        module.__package__ = package_name
        exec(compile(_decrypt(self.payloads[fullname]), filename, 'exec'), module.__dict__)
        parent = sys.modules.get(package_name)
        if parent is not None:
            setattr(parent, short_name, module)


def _install_encrypted_importer(base_dir):
    _ensure_formation_package(base_dir)
    for module_name, _payload in _MODULE_PAYLOADS:
        package_name, _, _short_name = module_name.rpartition('.')
        _ensure_package(package_name, base_dir)
    sys.meta_path.insert(0, _EncryptedModuleLoader(base_dir, _MODULE_PAYLOADS))


def _install_db_config(base_dir):
    source = _decrypt(_DB_CONFIG_PAYLOAD)
    module = types.ModuleType('db_config')
    module.__file__ = os.path.join(base_dir, 'db_config.py')
    module.__package__ = ''
    sys.modules['db_config'] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)


def _run_main(base_dir):
    source = _decrypt(_MAIN_PAYLOAD)
    filename = os.path.join(base_dir, 'formation_tool', 'process_formation_slots_way_combined.py')
    globals_dict = {{
        '__name__': '__main__',
        '__file__': filename,
        '__package__': None,
        '__builtins__': __builtins__,
    }}
    exec(compile(source, filename, 'exec'), globals_dict)


def main():
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
    _install_db_config(base_dir)
    _install_encrypted_importer(base_dir)
    _run_main(base_dir)


if __name__ == '__main__':
    main()
'''
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    LAUNCHER_PATH.write_text(launcher, encoding='utf-8')
    return LAUNCHER_PATH


def build_spec():
    """Generate the PyInstaller spec used by this encrypted build."""
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    spec = f"""# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

BUILD_ROOT = Path(SPECPATH).resolve()
TOOL_ROOT = BUILD_ROOT.parent
PROJECT_ROOT = TOOL_ROOT.parent

hiddenimports = [
    'sqlalchemy.dialects.mysql.mysqlconnector',
]
hiddenimports += collect_submodules('mysql.connector')


a = Analysis(
    [str(BUILD_ROOT / '{LAUNCHER_PATH.name}')],
    pathex=[str(BUILD_ROOT), str(TOOL_ROOT), str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
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
    name='{EXE_NAME}',
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
"""
    SPEC_PATH.write_text(spec, encoding='utf-8')
    return SPEC_PATH


def load_embedded_db_config_data():
    """Load db_config.py as data for writing an external example file."""
    spec = importlib.util.spec_from_file_location('formation_build_db_config', DB_CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing_attrs = [
        name
        for name in ('MAX_DB_RETRIES', 'DB_RETRY_DELAY', 'DATABASE_CONFIGS')
        if not hasattr(module, name)
    ]
    if missing_attrs:
        raise ValueError(f"db_config.py missing required names: {missing_attrs}")
    return {
        'MAX_DB_RETRIES': int(module.MAX_DB_RETRIES),
        'DB_RETRY_DELAY': int(module.DB_RETRY_DELAY),
        'DATABASE_CONFIGS': module.DATABASE_CONFIGS,
    }


def write_json_if_missing(path, data):
    if path.exists():
        return False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


def unlink_file_with_retry(path, *, attempts=8, delay=0.15):
    """Delete a file, tolerating short Windows file-lock delays."""
    path = Path(path)
    last_error = None
    for attempt in range(attempts):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay * (attempt + 1))
    raise last_error


def remove_path(path):
    """Remove a generated build artifact if it exists."""
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
        log_utils.emit(f"Cleaned directory: {path}")
        return True
    if path.exists():
        unlink_file_with_retry(path)
        log_utils.emit(f"Cleaned file: {path}")
        return True
    return False


def clean_build_artifacts(*, include_spec=False):
    """Clean generated launcher/work files without touching db_config.json."""
    cleaned = 0
    for path in TEMP_LAUNCHERS:
        cleaned += int(remove_path(path))
    for path in TEMP_WORK_DIRS:
        cleaned += int(remove_path(path))
    if include_spec:
        for path in TEMP_SPEC_FILES:
            cleaned += int(remove_path(path))
    if cleaned == 0:
        log_utils.emit("No temporary build artifacts found")


def ensure_external_db_config_hint():
    """Keep existing db_config.json; otherwise provide an editable example next to the exe."""
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    dist_config = DIST_ROOT / EXTERNAL_DB_CONFIG_NAME
    if dist_config.is_file():
        log_utils.emit(f"Kept external database config: {dist_config}")
        return

    source_candidates = [
        TOOL_ROOT / EXTERNAL_DB_CONFIG_NAME,
        PROJECT_ROOT / EXTERNAL_DB_CONFIG_NAME,
    ]
    for source in source_candidates:
        if source.is_file():
            shutil.copy2(source, dist_config)
            log_utils.emit(f"Copied external database config: {source} -> {dist_config}")
            return

    example_path = DIST_ROOT / EXTERNAL_DB_CONFIG_EXAMPLE_NAME
    if write_json_if_missing(example_path, load_embedded_db_config_data()):
        log_utils.emit(f"db_config.json not found; generated example config: {example_path}")
    else:
        log_utils.emit(f"db_config.json not found; example config already exists: {example_path}")


def cleanup_temp_launcher():
    """Remove generated source-like encrypted launcher after a successful build."""
    if LAUNCHER_PATH.exists():
        unlink_file_with_retry(LAUNCHER_PATH)
        log_utils.emit(f"Cleaned temporary launcher: {LAUNCHER_PATH}")


def run_pyinstaller():
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            '-m',
            'PyInstaller',
            '--clean',
            '--noconfirm',
            '--distpath',
            str(DIST_ROOT),
            '--workpath',
            str(BUILD_ROOT / 'formation_work'),
            str(SPEC_PATH),
        ],
        cwd=str(BUILD_ROOT),
        check=True,
    )


def run_test_suite():
    """Run the local test suite before building when requested."""
    subprocess.run(
        [sys.executable, str(TOOL_ROOT / 'run_tests.py')],
        cwd=str(PROJECT_ROOT),
        check=True,
    )


def build_arg_parser():
    """Build the command-line parser for the encrypted exe builder."""
    parser = argparse.ArgumentParser(
        description="Build encrypted formation.exe for the formation tool.",
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='run build preflight checks and exit',
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='run the local test suite before check/build',
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='remove temporary build artifacts and exit',
    )
    parser.add_argument(
        '--list-modules',
        action='store_true',
        help='list production modules that will be encrypted and exit',
    )
    return parser


def parse_args(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.clean and (args.check or args.test or args.list_modules):
        parser.error('--clean cannot be combined with --check, --test, or --list-modules')
    if args.list_modules and (args.check or args.test):
        parser.error('--list-modules cannot be combined with --check or --test')
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.list_modules:
        print_encrypted_module_list()
        return
    if args.clean:
        clean_build_artifacts(include_spec=True)
        return
    if args.check:
        run_preflight_checks()
        if args.test:
            run_test_suite()
        return

    run_preflight_checks()
    if args.test:
        run_test_suite()
    clean_build_artifacts(include_spec=False)
    spec_path = build_spec()
    log_utils.emit(f"Generated build spec: {spec_path}")
    launcher_created = False
    try:
        launcher_path = build_launcher()
        launcher_created = True
        log_utils.emit(f"Generated encrypted launcher: {launcher_path}")
        run_pyinstaller()
        ensure_external_db_config_hint()
    finally:
        if launcher_created:
            cleanup_temp_launcher()
    log_utils.emit(f"Build completed: {EXE_PATH}")


if __name__ == '__main__':
    main()

