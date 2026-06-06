"""Shared pytest bootstrap for Edict tests.

Ensure the repository root is importable so tests can reliably import the
`edict.backend...` package tree without depending on collection order or other
modules mutating ``sys.path`` first.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROOT_STR = str(ROOT)

if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)
