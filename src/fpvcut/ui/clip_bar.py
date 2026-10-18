"""Schmale Leiste unter der Zeitleiste: gespeicherte Ausschnitte und aktuelle In/Out-Auswahl."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

CLIP_COLOR = QColor(255, 196, 0, 90)  # Ausschnitte
FAVORITE_COLOR = QColor(255, 196, 0, 235)  # Favoriten
MARK_COLOR = QColor(61, 174, 233)  # aktuelle Auswahl
TRACK_COLOR = QColor(128, 128, 128, 60)


class ClipBar(QWidget):
    seek_requested = Signal(float)  # Sekunden

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("Gelb: Ausschnitte, kräftig gelb = Favorit · Blau: aktuelle In/Out-Auswahl (Klick springt)")
        self._duration = 0.0
        self._clips: list[tuple[float, float | None, bool]] = []
        self._in: float | None = None
        self._out: float | None = None
        self._inset = 0

    def set_inset(self, pixels: int) -> None:
        """Seitlicher Abstand, damit die Leiste mit der Schiene des Sliders fluchtet."""
        self._inset = pixels
        self.update()

    def set_duration(self, duration: float) -> None:
        self._duration = duration
        self.update()

    def set_clips(self, clips: list[tuple]) -> None:
        """(Start, Ende) oder (Start, Ende, Favorit); Ende ``None`` = bis zum Schluss."""
        self._clips = [(c[0], c[1], bool(c[2]) if len(c) > 2 else False) for c in clips]
        self.update()

    def set_marks(self, in_s: float | None, out_s: float | None) -> None:
        self._in, self._out = in_s, out_s
        self.update()

    def _x(self, seconds: float) -> float:
        width = self.width() - 2 * self._inset
        return self._inset + width * min(max(seconds / self._duration, 0.0), 1.0)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802  (Qt-Name)
        painter = QPainter(self)
        h = self.height()
        painter.fillRect(QRectF(self._inset, 2, self.width() - 2 * self._inset, h - 4), TRACK_COLOR)
        if self._duration <= 0:
            return
        # Favoriten zuletzt, damit sie bei Überlappung oben liegen.
        for start, end, favorite in sorted(self._clips, key=lambda c: c[2]):
            x1, x2 = self._x(start), self._x(self._duration if end is None else end)
            painter.fillRect(QRectF(x1, 1, max(x2 - x1, 2), h - 2), FAVORITE_COLOR if favorite else CLIP_COLOR)
        if self._in is not None and self._out is not None:
            x1, x2 = self._x(self._in), self._x(self._out)
            painter.fillRect(QRectF(x1, 0, max(x2 - x1, 2), h), MARK_COLOR)
        for mark in (self._in, self._out):
            if mark is not None:
                painter.fillRect(QRectF(self._x(mark) - 1, 0, 3, h), MARK_COLOR)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            width = max(self.width() - 2 * self._inset, 1)
            fraction = (event.position().x() - self._inset) / width
            self.seek_requested.emit(min(max(fraction, 0.0), 1.0) * self._duration)
