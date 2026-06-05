"""File helpers for the formation tool."""

import json
import os
from pathlib import Path


def write_json_atomic(path, data):
    """原子写入 JSON，并为已有文件保留 .bak。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + '.tmp')
    bak_path = path.with_name(path.name + '.bak')
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    if path.exists():
        try:
            if bak_path.exists():
                bak_path.unlink()
            os.replace(path, bak_path)
        except OSError:
            pass
    os.replace(tmp_path, path)

