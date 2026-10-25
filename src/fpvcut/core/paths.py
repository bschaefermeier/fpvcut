"""Wo Mitgeliefertes (libmpv, ffmpeg, KI-Modell) liegt: im Projekt oder in der .exe."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Läuft FPVCut als gepackte .exe (PyInstaller)?"""
    return bool(getattr(sys, "frozen", False))


def app_dir(name: str) -> Path:
    """Ordner ``<name>`` im Repo, in der .exe im entpackten Programmordner (z. B. ``models``)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[3]
    return base / name


def vendor_dir(name: str) -> Path:
    """``vendor/<name>``: neben dem Quellcode, in der .exe im entpackten Programmordner."""
    return app_dir("vendor") / name
