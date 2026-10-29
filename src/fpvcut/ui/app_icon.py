"""App-Icon: FPV-Dreiblatt-Propeller, die Bohrung der Nabe ist ein Play-Symbol.

``resources/fpvcut.svg`` ist die große Fassung, ``resources/fpvcut_small.svg`` eine vereinfachte,
an ganzen Pixeln ausgerichtete Fassung für 16 und 24 px (Taskleiste, Titelleiste).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_SVG = Path(__file__).resolve().parent.parent / "resources" / "fpvcut.svg"
ICON_SVG_SMALL = ICON_SVG.with_name("fpvcut_small.svg")
SMALL_MAX = 24  # bis zu dieser Größe die vereinfachte Fassung
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_icon(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(ICON_SVG_SMALL if size <= SMALL_MAX else ICON_SVG)).render(painter)
    painter.end()
    return image


def app_icon() -> QIcon:
    """Alle gängigen Größen vorrendern, damit Taskleiste und Titelleiste scharf sind."""
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(QPixmap.fromImage(render_icon(size)))
    return icon


def set_windows_app_id() -> None:
    """Eigene App-ID, sonst zeigt die Windows-Taskleiste das Python-Icon statt unseres."""
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FPVCut.FPVCut")
        except (AttributeError, OSError):
            pass
