#!/usr/bin/env python3
"""Lanzador de HyprDisplay desde el árbol de fuentes."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hyprdisplay.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
