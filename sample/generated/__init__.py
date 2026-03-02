"""Generated package marker.

Discovery guard: prevent `python -m unittest` from recursing into compiled modules.
"""

from __future__ import annotations

import unittest


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
    _ = loader, tests, pattern
    return unittest.TestSuite()
