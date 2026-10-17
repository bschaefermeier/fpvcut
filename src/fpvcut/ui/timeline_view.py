"""Timeline-Zeichenfläche: Videospur und Musikspur, Ziehen, Trimmen, Abspielkopf."""

from __future__ import annotations

import json

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from fpvcut.timeline.model import Timeline
from fpvcut.ui.library_panel import format_duration
from fpvcut.ui.mime import MIME_CLIPS, MIME_MEDIA


CLIP_COLORS = (QColor("#2f6fa8"), QColor("#3a82c4"))
MISSING_COLOR = QColor("#7a3b3b")
MUSIC_COLOR = QColor("#3f8f5a")
SELECT_COLOR = QColor("#ffc400")
PLAYHEAD_COLOR = QColor("#e53935")
EXTENSION_COLOR = QColor(255, 255, 255, 45)  # über den Favoriten hinaus verlängert
TICK_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600)


class TimelineView(QWidget):
    seek_requested = Signal(float)
    clips_dropped = Signal(list, int)  # Favoriten-IDs, Einfügeposition
    media_dropped = Signal(list, int)  # Video-IDs, Einfügeposition
    edit_started = Signal()  # vor einer Änderung (für Rückgängig)
    edited = Signal()  # nach einer Änderung
    clip_double_clicked = Signal(int)
    wheel_zoom = Signal(float, float)  # Faktor, Mausposition x
    wheel_scroll = Signal(int)  # Pixel nach rechts

    RULER = 20
    VIDEO_H = 54
    MUSIC_H = 26
    GAP = 4
    PAD = 8  # Rand links, damit der erste Clip greifbar bleibt
    EDGE = 6  # so nah an der Kante wird getrimmt statt verschoben

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.timeline = Timeline()
        self.pps = 20.0  # Pixel pro Sekunde
        self.selected: int | str | None = None  # Clip-Index oder "music"
        self.playhead = 0.0
        self._drag: dict | None = None
        self._drop_index: int | None = None
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(self.RULER + self.VIDEO_H + self.MUSIC_H + 3 * self.GAP)
        self._update_size()

    # --- Zustand ---------------------------------------------------------

    def set_timeline(self, timeline: Timeline) -> None:
        self.timeline = timeline
        if isinstance(self.selected, int) and self.selected >= len(timeline.clips):
            self.selected = None
        if self.selected == "music" and timeline.music is None:
            self.selected = None
        self._update_size()
        self.update()

    def set_zoom(self, pps: float) -> None:
        self.pps = max(2.0, min(pps, 400.0))
        self._update_size()
        self.update()

    def set_playhead(self, t: float) -> None:
        self.playhead = max(0.0, t)
        self.update()

    def playhead_x(self) -> int:
        return int(self._x(self.playhead))

    def select(self, selection: int | str | None) -> None:
        self.selected = selection
        self.update()

    def _update_size(self) -> None:
        self.setMinimumWidth(int(self._x(max(self.timeline.duration, 10.0))) + 200)

    def _x(self, t: float) -> float:
        return self.PAD + t * self.pps

    def _t(self, x: float) -> float:
        return max(0.0, (x - self.PAD) / self.pps)

    def _video_rect(self) -> QRectF:
        return QRectF(0, self.RULER + self.GAP, self.width(), self.VIDEO_H)

    def _music_rect(self) -> QRectF:
        top = self.RULER + 2 * self.GAP + self.VIDEO_H
        return QRectF(0, top, self.width(), self.MUSIC_H)

    def clip_rects(self) -> list[QRectF]:
        track = self._video_rect()
        return [
            QRectF(self._x(start), track.top(), clip.duration * self.pps, track.height())
            for start, clip in zip(self.timeline.starts(), self.timeline.clips)
        ]

    def music_rect(self) -> QRectF | None:
        if self.timeline.music is None:
            return None
        track = self._music_rect()
        width = max(self.timeline.music_length() * self.pps, 40)
        return QRectF(self._x(0), track.top(), width, track.height())

    # --- Zeichnen --------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802  (Qt-Name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        self._paint_ruler(painter)
        for track in (self._video_rect(), self._music_rect()):
            painter.fillRect(track, palette.alternateBase())

        small = QFont(self.font())
        small.setPointSizeF(max(small.pointSizeF() * 0.9, 7))
        painter.setFont(small)
        metrics = QFontMetrics(small)

        if not self.timeline.clips:
            painter.setPen(palette.placeholderText().color())
            painter.drawText(
                self._video_rect().adjusted(self.PAD + 4, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter,
                "Favoriten hierher ziehen oder im Favoriten-Reiter E drücken",
            )

        for index, (rect, clip) in enumerate(zip(self.clip_rects(), self.timeline.clips)):
            color = MISSING_COLOR if clip.path is None else CLIP_COLORS[index % 2]
            self._paint_block(painter, rect, color, index == self.selected)
            self._paint_extensions(painter, rect, clip)
            name = clip.label + ("  (fehlt)" if clip.path is None else "")
            text_rect = rect.adjusted(5, 3, -4, -3)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignTop, metrics.elidedText(name, Qt.TextElideMode.ElideRight, int(text_rect.width())))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignBottom, metrics.elidedText(f"{clip.duration:.1f} s", Qt.TextElideMode.ElideRight, int(text_rect.width())))

        music = self.timeline.music
        if (rect := self.music_rect()) is not None and music is not None:
            self._paint_block(painter, rect, MUSIC_COLOR, self.selected == "music")
            painter.setPen(Qt.GlobalColor.white)
            text = f"♪ {music.name}  ·  {int(music.volume * 100)} %"
            text_rect = rect.adjusted(5, 0, -4, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(text_rect.width())))
        elif self.timeline.clips:
            painter.setPen(palette.placeholderText().color())
            painter.drawText(self._music_rect().adjusted(self.PAD + 4, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "Keine Musik (Timeline → Musik hinzufügen)")

        if self._drop_index is not None:
            starts = self.timeline.starts() + [self.timeline.duration]
            x = self._x(starts[self._drop_index])
            painter.setPen(QPen(SELECT_COLOR, 3))
            track = self._video_rect()
            painter.drawLine(QPointF(x, track.top() - 2), QPointF(x, track.bottom() + 2))

        x = self._x(self.playhead)
        painter.setPen(QPen(PLAYHEAD_COLOR, 2))
        painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        painter.end()

    def _paint_block(self, painter: QPainter, rect: QRectF, color: QColor, selected: bool) -> None:
        painter.setPen(QPen(SELECT_COLOR, 2) if selected else QPen(color.darker(140), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

    def _paint_extensions(self, painter: QPainter, rect: QRectF, clip) -> None:
        """Teile außerhalb des ursprünglichen Favoriten heller und schraffiert zeigen."""
        if clip.fav_in is None or clip.fav_out is None:
            return
        spans = []
        if clip.src_in < clip.fav_in:
            spans.append((clip.src_in, min(clip.fav_in, clip.src_out)))
        if clip.src_out > clip.fav_out:
            spans.append((max(clip.fav_out, clip.src_in), clip.src_out))
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for start, end in spans:
            if end <= start:
                continue
            x0 = rect.left() + (start - clip.src_in) * self.pps
            span = QRectF(x0, rect.top() + 1, (end - start) * self.pps, rect.height() - 2)
            painter.setBrush(EXTENSION_COLOR)
            painter.drawRect(span)
            painter.setBrush(QBrush(QColor(255, 255, 255, 60), Qt.BrushStyle.BDiagPattern))
            painter.drawRect(span)
        painter.restore()

    def _paint_ruler(self, painter: QPainter) -> None:
        step = next((s for s in TICK_STEPS if s * self.pps >= 70), TICK_STEPS[-1])
        painter.setPen(self.palette().text().color())
        end = self._t(self.width())
        t = 0
        while t <= end:
            x = self._x(t)
            painter.drawLine(QPointF(x, self.RULER - 6), QPointF(x, self.RULER))
            painter.drawText(QPointF(x + 3, self.RULER - 7), format_duration(t))
            t += step

    # --- Maus ------------------------------------------------------------

    def hit(self, pos: QPointF) -> tuple:
        """Was liegt unter der Maus? ("clip", i, "start"|"end"|"body"), ("music",), ("empty",)."""
        if self._video_rect().contains(pos):
            x = pos.x()
            rects = self.clip_rects()
            # Kantenzonen reichen EDGE Pixel nach beiden Seiten über die Kante hinaus, so liegen an
            # einer Grenze immer beide Clips zur Auswahl, egal auf welcher Seite die Maus steht.
            edges = []
            for index, rect in enumerate(rects):
                inner = min(self.EDGE, rect.width() / 3)
                if rect.left() - self.EDGE <= x <= rect.left() + inner:
                    edges.append(("clip", index, "start"))
                if rect.right() - inner <= x <= rect.right() + self.EDGE:
                    edges.append(("clip", index, "end"))
            if edges:
                # Der ausgewählte Clip gewinnt, sonst der, in dem die Maus liegt.
                for hit in edges:
                    if hit[1] == self.selected:
                        return hit
                inside = [h for h in edges if rects[h[1]].left() <= x < rects[h[1]].right()]
                return (inside or edges)[0]
            for index, rect in enumerate(rects):
                if rect.left() <= x < rect.right():
                    return ("clip", index, "body")
        if (rect := self.music_rect()) is not None and rect.contains(pos):
            return ("music",)
        return ("empty",)

    def gap_at(self, x: float) -> int:
        """Einfügeposition (0 … Anzahl Clips) für Mausposition ``x``."""
        t = self._t(x)
        for index, (start, clip) in enumerate(zip(self.timeline.starts(), self.timeline.clips)):
            if t < start + clip.duration / 2:
                return index
        return len(self.timeline.clips)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        hit = self.hit(pos)
        if hit[0] == "clip":
            _, index, part = hit
            clip = self.timeline.clips[index]
            self.select(index)
            self._drag = {
                "mode": "move" if part == "body" else part, "index": index, "x": pos.x(),
                "src_in": clip.src_in, "src_out": clip.src_out, "active": False,
            }
        elif hit[0] == "music":
            self.select("music")
        else:
            self.select(None)
            self._drag = {"mode": "scrub"}
            self._scrub(pos.x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        drag = self._drag
        if drag is None:
            hit = self.hit(pos)
            edge = hit[0] == "clip" and hit[2] != "body"
            self.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.ArrowCursor)
            return
        if drag["mode"] == "scrub":
            self._scrub(pos.x())
            return
        dx = pos.x() - drag["x"]
        if not drag["active"]:
            if abs(dx) < 3:
                return
            drag["active"] = True
            if drag["mode"] != "move":
                self.edit_started.emit()
        if drag["mode"] == "move":
            self._drop_index = self.gap_at(pos.x())
        elif drag["mode"] == "start":
            self.timeline.trim_start(drag["index"], drag["src_in"] + dx / self.pps)
            self._update_size()
        else:
            self.timeline.trim_end(drag["index"], drag["src_out"] + dx / self.pps)
            self._update_size()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        drag, self._drag = self._drag, None
        target, self._drop_index = self._drop_index, None
        if drag is None or not drag.get("active"):
            self.update()
            return
        if drag["mode"] == "move":
            index = drag["index"]
            if target is not None and target not in (index, index + 1):
                self.edit_started.emit()
                self.selected = self.timeline.move(index, target)
                self._update_size()
                self.edited.emit()
        else:
            self.edited.emit()
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        hit = self.hit(event.position())
        if hit[0] == "clip":
            self.clip_double_clicked.emit(hit[1])

    def _scrub(self, x: float) -> None:
        self.set_playhead(min(self._t(x), self.timeline.duration))
        self.seek_requested.emit(self.playhead)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Mausrad zoomt um die Mausposition; Shift+Mausrad oder seitliches Wischen scrollt."""
        delta = event.angleDelta()
        if delta.x() and not delta.y():
            self.wheel_scroll.emit(-delta.x())
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.wheel_scroll.emit(-(delta.y() or delta.x()))
        elif delta.y():
            self.wheel_zoom.emit(1.25 ** (delta.y() / 120), event.position().x())
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        else:
            super().keyPressEvent(event)

    def delete_selected(self) -> bool:
        if self.selected is None:
            return False
        self.edit_started.emit()
        if self.selected == "music":
            self.timeline.music = None
            self.selected = None
        else:
            self.timeline.remove(self.selected)
            self.selected = min(self.selected, len(self.timeline.clips) - 1) if self.timeline.clips else None
        self._update_size()
        self.update()
        self.edited.emit()
        return True

    # --- Drag & Drop aus dem Favoriten-Browser ---------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()

    @staticmethod
    def _accepts(mime) -> bool:
        return mime.hasFormat(MIME_CLIPS) or mime.hasFormat(MIME_MEDIA)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._accepts(event.mimeData()):
            self._drop_index = self.gap_at(event.position().x())
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802
        self._drop_index = None
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        index = self.gap_at(event.position().x())
        self._drop_index = None
        self.update()
        mime = event.mimeData()
        kind, signal = (MIME_CLIPS, self.clips_dropped) if mime.hasFormat(MIME_CLIPS) else (MIME_MEDIA, self.media_dropped)
        try:
            ids = [int(i) for i in json.loads(bytes(mime.data(kind)).decode())]
        except (ValueError, TypeError):
            return
        event.acceptProposedAction()
        signal.emit(ids, index)
