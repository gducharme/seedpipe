#!/usr/bin/env python3
"""Verify entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedpipe.tools.verify import main


if __name__ == "__main__":
    raise SystemExit(main())
