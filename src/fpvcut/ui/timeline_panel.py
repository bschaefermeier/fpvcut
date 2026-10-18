"""Timeline unter dem Player: Werkzeugleiste, Zeichenfläche, Rückgängig."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fpvcut.timeline.model import MusicTrack, Timeline, TimelineClip
from fpvcut.ui.library_panel import format_duration
from fpvcut.ui.timeline_view import TimelineView

HISTORY_LIMIT = 100


class TimelinePanel(QWidget):
    preview_requested = Signal(float)  # ab dieser Timeline-Zeit abspielen
    seek_requested = Signal(float)
    clips_dropped = Signal(list, int)  # Favoriten-IDs, Einfügeposition
    media_dropped = Signal(list, int)  # Video-IDs, Einfügeposition
    music_requested = Signal()
    render_requested = Signal()
    changed = Signal()  # nach jeder Änderung (Speichern, Vorschau aktualisieren)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._undo: list[Timeline] = []
        self._redo: list[Timeline] = []

        self.view = TimelineView()
        self.view.seek_requested.connect(self.seek_requested)
        self.view.clips_dropped.connect(self.clips_dropped)
        self.view.media_dropped.connect(self.media_dropped)
        self.view.edit_started.connect(self.remember)
        self.view.edited.connect(self._on_edited)
        self.view.wheel_zoom.connect(self.zoom)
        self.view.wheel_scroll.connect(self._scroll_by)
        self.view.clip_double_clicked.connect(
            lambda i: self.preview_requested.emit(self.timeline.starts()[i])
        )
        self._scroll = QScrollArea(self)
        self._scroll.setWidget(self.view)
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(self.view.height() + self._scroll.horizontalScrollBar().sizeHint().height() + 4)

        self._play = QPushButton("▶ Timeline abspielen", self)
        self._play.setToolTip("Spielt die Timeline ab dem roten Abspielkopf ab (P). Doppelklick auf einen Clip: ab dort.")
        self._play.clicked.connect(lambda: self.preview_requested.emit(self.view.playhead))
        music = QPushButton("♪ Musik …", self)
        music.clicked.connect(self.music_requested)
        self._original = self._volume_slider("Originalton der Clips")
        self._music = self._volume_slider("Lautstärke der Musik")
        self._fade = QDoubleSpinBox(self)
        self._fade.setRange(0, 30)
        self._fade.setSingleStep(0.5)
        self._fade.setSuffix(" s")
        self._fade.setToolTip("Musik am Ende ausblenden")
        self._fade.valueChanged.connect(self._on_audio_changed)
        self._original.valueChanged.connect(self._on_audio_changed)
        self._music.valueChanged.connect(self._on_audio_changed)
        zoom_out = QToolButton(self)
        zoom_out.setText("−")
        zoom_out.setToolTip("Herauszoomen")
        zoom_out.clicked.connect(lambda: self.zoom(1 / 1.5))
        zoom_in = QToolButton(self)
        zoom_in.setText("+")
        zoom_in.setToolTip("Hineinzoomen")
        zoom_in.clicked.connect(lambda: self.zoom(1.5))
        self._summary = QLabel(self)
        self._render = QPushButton("Rendern …", self)
        self._render.setToolTip("Timeline als Video-Datei rendern (Strg+R)")
        self._render.clicked.connect(self.render_requested)
        for widget in (self._play, music, zoom_in, zoom_out, self._fade, self._render):
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        bar = QHBoxLayout()
        bar.addWidget(self._play)
        bar.addWidget(music)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Originalton", self))
        bar.addWidget(self._original)
        bar.addWidget(QLabel("Musik", self))
        bar.addWidget(self._music)
        bar.addWidget(QLabel("Ausblenden", self))
        bar.addWidget(self._fade)
        bar.addStretch(1)
        bar.addWidget(self._summary)
        bar.addSpacing(12)
        bar.addWidget(zoom_out)
        bar.addWidget(zoom_in)
        bar.addSpacing(12)
        bar.addWidget(self._render)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        layout.addLayout(bar)
        layout.addWidget(self._scroll)
        self.set_timeline(Timeline())

    def _volume_slider(self, tooltip: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(0, 150)
        slider.setFixedWidth(90)
        slider.setToolTip(tooltip)
        slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return slider

    # --- Zustand ---------------------------------------------------------

    @property
    def timeline(self) -> Timeline:
        return self.view.timeline

    def set_timeline(self, timeline: Timeline, keep_history: bool = False) -> None:
        if not keep_history:
            self._undo.clear()
            self._redo.clear()
        self.view.set_timeline(timeline)
        self._sync_controls()

    def _sync_controls(self) -> None:
        timeline = self.timeline
        for widget, value in (
            (self._original, round(timeline.original_volume * 100)),
            (self._music, round(timeline.music.volume * 100) if timeline.music else 80),
            (self._fade, timeline.music.fade_out if timeline.music else 3.0),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._music.setEnabled(timeline.music is not None)
        self._fade.setEnabled(timeline.music is not None)
        self._play.setEnabled(bool(timeline.clips))
        self._render.setEnabled(bool(timeline.clips))
        count = len(timeline.clips)
        self._summary.setText(f"{count} Clip{'' if count == 1 else 's'} · {format_duration(timeline.duration)}")

    def set_playhead(self, t: float) -> None:
        self.view.set_playhead(t)
        self._scroll.ensureVisible(self.view.playhead_x(), 0, 60, 0)

    def zoom(self, factor: float, anchor_x: float | None = None) -> None:
        """Zoomen; die Zeit unter ``anchor_x`` (sonst unter dem Abspielkopf) bleibt an ihrer Stelle."""
        bar = self._scroll.horizontalScrollBar()
        if anchor_x is None:
            anchor_x = float(self.view.playhead_x())
            if not bar.value() <= anchor_x <= bar.value() + self._scroll.viewport().width():
                anchor_x = bar.value() + self._scroll.viewport().width() / 2
        on_screen = anchor_x - bar.value()
        t = self.view._t(anchor_x)
        self.view.set_zoom(self.view.pps * factor)
        # Größe sofort übernehmen, damit der Scrollbalken den neuen Bereich schon kennt.
        self.view.resize(max(self.view.minimumWidth(), self._scroll.viewport().width()), self.view.height())
        bar.setValue(int(self.view._x(t) - on_screen))

    def _scroll_by(self, pixels: int) -> None:
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() + pixels)

    # --- Bearbeiten ------------------------------------------------------

    def remember(self) -> None:
        self._undo.append(self.timeline.copy())
        del self._undo[:-HISTORY_LIMIT]
        self._redo.clear()

    def _on_edited(self) -> None:
        self._sync_controls()
        self.changed.emit()

    def _on_audio_changed(self) -> None:
        timeline = self.timeline
        timeline.original_volume = self._original.value() / 100
        if timeline.music is not None:
            timeline.music.volume = self._music.value() / 100
            timeline.music.fade_out = self._fade.value()
        self.view.update()
        self.changed.emit()

    def add_clips(self, clips: list[TimelineClip], index: int | None = None) -> None:
        if not clips:
            return
        self.remember()
        self.timeline.insert(clips, index)
        self.view.set_timeline(self.timeline)
        self._on_edited()

    def set_music(self, music: MusicTrack | None) -> None:
        self.remember()
        self.timeline.music = music
        self.view.set_timeline(self.timeline)
        self._on_edited()

    def split_at_playhead(self) -> bool:
        snapshot = self.timeline.copy()
        index = self.timeline.split(self.view.playhead)
        if index is None:
            return False
        self._undo.append(snapshot)
        self._redo.clear()
        self.view.select(index)
        self.view.set_timeline(self.timeline)
        self._on_edited()
        return True

    def delete_selected(self) -> bool:
        return self.view.delete_selected()

    def selected_clip(self) -> int | None:
        return self.view.selected if isinstance(self.view.selected, int) else None

    def selected_clips(self) -> list[int]:
        """Alle ausgewählten Clips (Strg/Shift+Klick)."""
        return self.view.selection

    def set_grades(self, grades: dict[int, dict | None], remember: bool = True) -> None:
        """Je Clip eine eigene Farbkorrektur setzen, z. B. wenn mehrere Clips ausgewählt sind."""
        if remember:
            self.remember()
        for index, grade in grades.items():
            self.timeline.clips[index].grade = dict(grade) if grade else None
        self.view.update()
        self.changed.emit()

    def set_grade(self, indices: list[int], grade: dict | None, remember: bool = True) -> None:
        """Farbkorrektur setzen; beim Ziehen eines Reglers nur einmal für Rückgängig merken."""
        if remember:
            self.remember()
        for index in indices:
            self.timeline.clips[index].grade = dict(grade) if grade else None
        self.view.update()
        self.changed.emit()

    def undo(self) -> bool:
        return self._step(self._undo, self._redo)

    def redo(self) -> bool:
        return self._step(self._redo, self._undo)

    def _step(self, source: list[Timeline], target: list[Timeline]) -> bool:
        if not source:
            return False
        target.append(self.timeline.copy())
        self.view.set_timeline(source.pop())
        self._on_edited()
        return True
