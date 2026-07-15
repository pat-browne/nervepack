"""Tests for the nervepack CLI dispatcher (engine/nervepack_engine/cli.py).
Stdlib unittest only, run via engine/setup/tests/run-all.sh."""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestPackageSkeleton(unittest.TestCase):
    def test_package_importable(self):
        import nervepack_engine
        self.assertTrue(hasattr(nervepack_engine, "__version__"))


if __name__ == "__main__":
    unittest.main()
