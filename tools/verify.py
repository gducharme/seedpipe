#!/usr/bin/env python3
"""CLI wrapper for verifier.

Relationship:
- ``tools/verify.py`` is the thin command entrypoint used from repository root
  and module invocation (``python -m tools.verify``).
- ``seedpipe/tools/verify.py`` contains the reusable verifier implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedpipe.tools.verify import main


if __name__ == "__main__":
    raise SystemExit(main())
