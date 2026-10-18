"""Schmale Leiste unter der Zeitleiste: gespeicherte Ausschnitte und aktuelle In/Out-Auswahl."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

CLIP_COLOR = QColor(255, 196, 0, 90)  # Ausschnitte
FAVORITE_COLOR = QColor(255, 196, 0, 235)  # Favoriten
MARK_COLOR = QColor(61, 174, 233)  # aktuelle Auswahl
TRACK_COLOR = QColor(128, 128, 128, 60)


DRAG_PIXELS = 4  # ab hier wird aus einem Klick ein gezogener Bereich


class ClipBar(QWidget):
    seek_requested = Signal(float)  # Sekunden
    scrub_requested = Signal(float)  # beim Ziehen: Bild an dieser Stelle zeigen
    range_selected = Signal(float, float)  # gezogener Bereich (Start, Ende)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setToolTip(
            "Gelb: Ausschnitte, kräftig gelb = Favorit · Blau: aktuelle In/Out-Auswahl\n"
            "Klick springt, Ziehen markiert einen neuen Ausschnitt"
        )
        self._duration = 0.0
        self._clips: list[tuple[float, float | None, bool]] = []
        self._in: float | None = None
        self._out: float | None = None
        self._inset = 0
        self._press_x: float | None = None
        self._drag: tuple[float, float] | None = None  # (Start, aktuelle Stelle) beim Ziehen

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

    def _seconds(self, x: float) -> float:
        width = max(self.width() - 2 * self._inset, 1)
        return min(max((x - self._inset) / width, 0.0), 1.0) * self._duration

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
        marks = (self._in, self._out) if self._drag is None else self._drag
        if marks[0] is not None and marks[1] is not None:
            x1, x2 = sorted((self._x(marks[0]), self._x(marks[1])))
            painter.fillRect(QRectF(x1, 0, max(x2 - x1, 2), h), MARK_COLOR)
        for mark in marks:
            if mark is not None:
                painter.fillRect(QRectF(self._x(mark) - 1, 0, 3, h), MARK_COLOR)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self._press_x = event.position().x()
            self.seek_requested.emit(self._seconds(self._press_x))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_x is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        if self._drag is None and abs(x - self._press_x) < DRAG_PIXELS:
            return
        self._drag = (self._seconds(self._press_x), self._seconds(x))
        self.update()
        self.scrub_requested.emit(self._drag[1])

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        drag, self._drag, self._press_x = self._drag, None, None
        self.update()
        if drag is not None:
            start, end = sorted(drag)
            if end > start:
                self.range_selected.emit(start, end)
