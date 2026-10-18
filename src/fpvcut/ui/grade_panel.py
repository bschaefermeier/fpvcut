"""Farbkorrektur der in der Timeline ausgewählten Clips: Regler, LUT, auf alle übertragen.

Sind mehrere Clips ausgewählt, zeigen die Regler die Werte des zuletzt angeklickten Clips.
Eine Änderung übernimmt nur den bewegten Regler (bzw. die LUT) in alle ausgewählten Clips;
ihre übrigen Werte bleiben, wie sie sind.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fpvcut.timeline.grade import RANGES, Grade
from fpvcut.ui.timeline_panel import TimelinePanel

# Regler: Name → (Beschriftung, Schritte pro Einheit, Anzeigeformat)
SLIDERS = {
    "brightness": ("Helligkeit", 1000, lambda v: f"{v:+.2f}"),
    "contrast": ("Kontrast", 1000, lambda v: f"{v:.2f}"),
    "saturation": ("Sättigung", 1000, lambda v: f"{v:.2f}"),
    "gamma": ("Gamma", 1000, lambda v: f"{v:.2f}"),
    "temperature": ("Temperatur", 1, lambda v: f"{v:.0f} K"),
}


class GradePanel(QWidget):
    grade_changed = Signal()  # nach jeder Änderung, z. B. um die Vorschau zu zeigen

    def __init__(self, timeline_panel: TimelinePanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.timeline_panel = timeline_panel
        self._updating = False
        self._dragging = False
        self._reset_targets: dict[QObject, str] = {}  # Regler/Wert → Name, für Doppelklick

        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")
        form = QFormLayout()
        self.sliders: dict[str, QSlider] = {}
        self._labels: dict[str, QLabel] = {}
        for name, (label, steps, _fmt) in SLIDERS.items():
            low, high, neutral = RANGES[name]
            slider = QSlider(Qt.Orientation.Horizontal, self)
            slider.setRange(round(low * steps), round(high * steps))
            slider.setValue(round(neutral * steps))
            slider.setPageStep(max((slider.maximum() - slider.minimum()) // 20, 1))
            slider.setToolTip("Doppelklick: zurück auf neutral")
            slider.sliderPressed.connect(self._on_press)
            slider.sliderReleased.connect(self._on_release)
            slider.valueChanged.connect(self._on_value)
            value = QLabel(self)
            value.setMinimumWidth(56)
            value.setToolTip("Doppelklick: zurück auf neutral")
            # Doppelklick auf Regler oder Wert setzt zurück (Ereignisfilter, da Qt-Methoden
            # in PySide nicht per Zuweisung überschrieben werden können).
            slider.installEventFilter(self)
            value.installEventFilter(self)
            self._reset_targets[slider] = self._reset_targets[value] = name
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(value)
            form.addRow(label + ":", row)
            self.sliders[name] = slider
            self._labels[name] = value

        self._lut_label = QLabel("keine", self)
        self._lut_label.setWordWrap(True)
        choose = QPushButton("LUT wählen …", self)
        choose.setToolTip("3D-LUT im .cube-Format, z. B. zum Umwandeln von D-Log/Flat-Aufnahmen")
        choose.clicked.connect(self.choose_lut)
        self._clear_lut = QToolButton(self)
        self._clear_lut.setText("✕")
        self._clear_lut.setToolTip("LUT entfernen")
        self._clear_lut.clicked.connect(lambda: self.set_lut(None))
        lut_row = QHBoxLayout()
        lut_row.addWidget(choose)
        lut_row.addWidget(self._clear_lut)
        lut_row.addStretch(1)
        form.addRow("LUT:", lut_row)
        form.addRow("", self._lut_label)

        self._reset = QPushButton("Zurücksetzen", self)
        self._reset.clicked.connect(self.reset)
        self._to_all = QPushButton("Auf alle Clips übertragen", self)
        self._to_all.setToolTip("Dieselbe Korrektur für alle Clips der Timeline, z. B. bei gleicher Kamera")
        self._to_all.clicked.connect(self.apply_to_all)
        buttons = QHBoxLayout()
        buttons.addWidget(self._reset)
        buttons.addWidget(self._to_all)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._hint)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addStretch(1)

        timeline_panel.view.selection_changed.connect(self.refresh)
        timeline_panel.changed.connect(self.refresh)  # z. B. nach Rückgängig
        self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt-Name)
        if event.type() == QEvent.Type.MouseButtonDblClick and watched in self._reset_targets:
            self._dragging = False
            self.reset_value(self._reset_targets[watched])
            return True
        return super().eventFilter(watched, event)

    # --- Anzeige ---------------------------------------------------------

    def current_index(self) -> int | None:
        return self.timeline_panel.selected_clip()

    def targets(self) -> list[int]:
        """Clips, auf die eine Änderung wirkt: alle ausgewählten."""
        index = self.current_index()
        return [] if index is None else (self.timeline_panel.selected_clips() or [index])

    def current_grade(self) -> Grade:
        index = self.current_index()
        return Grade() if index is None else Grade.from_dict(self.timeline_panel.timeline.clips[index].grade)

    def refresh(self) -> None:
        if self._updating:
            return
        index = self.current_index()
        enabled = index is not None
        for widget in (*self.sliders.values(), self._reset, self._to_all, self._clear_lut):
            widget.setEnabled(enabled)
        several = enabled and len(self.targets()) > 1
        self._to_all.setText("Auf ausgewählte Clips übertragen" if several else "Auf alle Clips übertragen")
        self._to_all.setToolTip(
            "Die komplette Korrektur dieses Clips für alle ausgewählten Clips" if several
            else "Dieselbe Korrektur für alle Clips der Timeline, z. B. bei gleicher Kamera"
        )
        if several:
            targets = self.targets()
            clip = self.timeline_panel.timeline.clips[index]
            self._hint.setText(
                f"{len(targets)} Clips ausgewählt. Die Regler zeigen „{clip.label}“ (Clip {index + 1}); "
                "eine Änderung übernimmt nur diesen Wert in alle ausgewählten Clips."
            )
        elif enabled:
            clip = self.timeline_panel.timeline.clips[index]
            self._hint.setText(f"Farbkorrektur für „{clip.label}“ (Clip {index + 1}).")
        else:
            self._hint.setText("Einen Clip in der Timeline anklicken, um seine Farben zu korrigieren.")
        grade = self.current_grade()
        self._updating = True
        for name, slider in self.sliders.items():
            steps = SLIDERS[name][1]
            slider.setValue(round(getattr(grade, name) * steps))
            self._labels[name].setText(SLIDERS[name][2](getattr(grade, name)))
        self._lut_label.setText(Path(grade.lut).name if grade.lut else "keine")
        self._lut_label.setToolTip(grade.lut or "")
        self._clear_lut.setEnabled(enabled and bool(grade.lut))
        self._updating = False

    # --- Ändern ----------------------------------------------------------

    def _store(self, grade: Grade, remember: bool) -> None:
        index = self.current_index()
        if index is None:
            return
        # Nur geänderte Werte übernehmen, damit bei mehreren Clips deren übrige Werte bleiben.
        before = self.current_grade()
        changes = {f: getattr(grade, f) for f in vars(grade) if getattr(grade, f) != getattr(before, f)}
        clips = self.timeline_panel.timeline.clips
        grades = {}
        for target in self.targets():
            own = grade if target == index else Grade.from_dict(clips[target].grade)
            for name, value in changes.items():
                setattr(own, name, value)
            grades[target] = own.to_dict()
        self._updating = True
        try:
            self.timeline_panel.set_grades(grades, remember=remember)
        finally:
            self._updating = False
        self.refresh()
        self.grade_changed.emit()

    def _on_press(self) -> None:
        self.timeline_panel.remember()  # ein Rückgängig-Schritt pro Zug am Regler
        self._dragging = True

    def _on_release(self) -> None:
        self._dragging = False

    def _on_value(self) -> None:
        if self._updating:
            return
        grade = self.current_grade()
        for name, slider in self.sliders.items():
            setattr(grade, name, slider.value() / SLIDERS[name][1])
        self._store(grade, remember=not self._dragging)

    def reset_value(self, name: str) -> None:
        if self.current_index() is None:
            return
        grade = self.current_grade()
        setattr(grade, name, RANGES[name][2])
        self._store(grade, remember=True)

    def set_lut(self, path: str | None) -> None:
        grade = self.current_grade()
        grade.lut = path
        self._store(grade, remember=True)

    def choose_lut(self) -> None:
        if self.current_index() is None:
            return
        current = self.current_grade().lut
        path, _ = QFileDialog.getOpenFileName(self, "LUT wählen", current or "", "3D-LUT (*.cube)")
        if path:
            self.set_lut(path)

    def reset(self) -> None:
        """Alle ausgewählten Clips ganz auf neutral."""
        if self.current_index() is None:
            return
        self.timeline_panel.set_grade(self.targets(), None)
        self.grade_changed.emit()

    def apply_to_all(self) -> None:
        """Korrektur des angezeigten Clips komplett übertragen: auf die Auswahl, sonst auf alle Clips."""
        if self.current_index() is None:
            return
        grade = self.current_grade().to_dict()
        targets = self.targets()
        if len(targets) < 2:
            targets = list(range(len(self.timeline_panel.timeline.clips)))
        self.timeline_panel.set_grade(targets, grade)
        self.grade_changed.emit()
