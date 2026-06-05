"""Run formation_tool tests from one stable entrypoint."""

import shutil
import unittest
from pathlib import Path


def load_tests():
    root = Path(__file__).resolve().parent
    return unittest.defaultTestLoader.discover(
        str(root),
        pattern='test_*.py',
        top_level_dir=str(root),
    )


def cleanup_pycache(root):
    for cache_dir in root.rglob('__pycache__'):
        shutil.rmtree(cache_dir, ignore_errors=True)


def main():
    root = Path(__file__).resolve().parent
    runner = unittest.TextTestRunner(verbosity=2)
    try:
        result = runner.run(load_tests())
        return 0 if result.wasSuccessful() else 1
    finally:
        cleanup_pycache(root)


if __name__ == '__main__':
    raise SystemExit(main())
