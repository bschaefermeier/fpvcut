"""Wo die mitgelieferten Programme (libmpv, ffmpeg) liegen: im Projekt oder in der .exe."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Läuft FPVCut als gepackte .exe (PyInstaller)?"""
    return bool(getattr(sys, "frozen", False))


def vendor_dir(name: str) -> Path:
    """``vendor/<name>``: neben dem Quellcode, in der .exe im entpackten Programmordner."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[3]
    return base / "vendor" / name
