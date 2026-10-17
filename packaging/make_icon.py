"""Erzeugt ``src/fpvcut/resources/fpvcut.ico`` aus dem SVG-Icon (für die .exe).

Aufruf: ``uv run python packaging/make_icon.py``
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

from fpvcut.ui.app_icon import ICON_SVG, render_icon

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    render_icon(size).save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(path: Path) -> None:
    """ICO mit PNG-Einträgen (seit Windows Vista unterstützt)."""
    images = [png_bytes(size) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in zip(ICO_SIZES, images):
        dim = 0 if size >= 256 else size  # 0 steht für 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + entries + b"".join(images))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    target = ICON_SVG.with_suffix(".ico")
    write_ico(target)
    print(target)
