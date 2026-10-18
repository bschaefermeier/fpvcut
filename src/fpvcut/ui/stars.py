"""Favorit-Stern für Listen: gelb ★ für Favoriten, blass ☆ zum Anklicken für die übrigen Ausschnitte."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QTreeWidgetItem

FAVORITE_COLOR = QColor("#ffc400")  # wie die Favoriten-Balken unter der Zeitleiste
PLAIN_COLOR = QColor(128, 128, 128, 140)


def set_star(item: QTreeWidgetItem, column: int, favorite: bool) -> None:
    item.setText(column, "★" if favorite else "☆")
    item.setForeground(column, QBrush(FAVORITE_COLOR if favorite else PLAIN_COLOR))
    item.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
    item.setToolTip(column, "Favorit (Klick entfernt die Markierung)" if favorite else "Klick markiert als Favorit")
    font = QFont(item.font(column))
    font.setBold(favorite)
    item.setFont(column, font)


def star_icon(favorite: bool, size: int = 16) -> QIcon:
    """Gelber Stern für Favoriten, sonst ein leeres Icon gleicher Größe (damit die Texte fluchten)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if favorite:
        painter = QPainter(pixmap)
        font = painter.font()
        font.setPixelSize(size)
        painter.setFont(font)
        painter.setPen(FAVORITE_COLOR)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "★")
        painter.end()
    return QIcon(pixmap)
