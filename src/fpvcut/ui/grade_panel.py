"""Farbkorrektur der in der Timeline ausgewählten Clips: Regler (auch Schärfe), LUT, Automatik, auf alle übertragen.

Ganz oben der Schalter für die KI-Bildreinigung (normales Modell live in der Vorschau). Sie läuft
vor allen Farbfiltern, die Regler wirken also auf das gereinigte Bild.

Sind mehrere Clips ausgewählt, zeigen die Regler die Werte des zuletzt angeklickten Clips.
Eine Änderung übernimmt nur den bewegten Regler (bzw. die LUT) in alle ausgewählten Clips;
ihre übrigen Werte bleiben, wie sie sind.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
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

from fpvcut import restore
from fpvcut.core.ffmpeg_tools import FFmpegNotFound, find_tool
from fpvcut.timeline.auto_grade import measure, suggest
from fpvcut.timeline.grade import RANGES, Grade
from fpvcut.ui.timeline_panel import TimelinePanel

# Regler: Name → (Beschriftung, Schritte pro Einheit, Anzeigeformat)
SLIDERS = {
    "brightness": (QT_TRANSLATE_NOOP("GradePanel", "Brightness"), 1000, lambda v: f"{v:+.2f}"),
    "contrast": (QT_TRANSLATE_NOOP("GradePanel", "Contrast"), 1000, lambda v: f"{v:.2f}"),
    "gamma": (QT_TRANSLATE_NOOP("GradePanel", "Gamma"), 1000, lambda v: f"{v:.2f}"),
    "shadows": (QT_TRANSLATE_NOOP("GradePanel", "Shadows"), 100, lambda v: f"{v:+.2f}"),
    "highlights": (QT_TRANSLATE_NOOP("GradePanel", "Highlights"), 100, lambda v: f"{v:+.2f}"),
    "saturation": (QT_TRANSLATE_NOOP("GradePanel", "Saturation"), 1000, lambda v: f"{v:.2f}"),
    "vibrance": (QT_TRANSLATE_NOOP("GradePanel", "Vibrance"), 100, lambda v: f"{v:+.2f}"),
    "temperature": (QT_TRANSLATE_NOOP("GradePanel", "Temperature"), 1, lambda v: f"{v:.0f} K"),
    "sharpness": (QT_TRANSLATE_NOOP("GradePanel", "Sharpness"), 100, lambda v: f"{v:+.2f}"),
}
TOOLTIPS = {
    "shadows": QT_TRANSLATE_NOOP("GradePanel", "Brighten (right) or darken (left) the dark parts of the image"),
    "highlights": QT_TRANSLATE_NOOP("GradePanel", "Recover (left) the bright parts of the image, e.g. an almost white sky"),
    "vibrance": QT_TRANSLATE_NOOP("GradePanel", "Like saturation, but boosts pale colors more and spares strong ones"),
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

        self._restore = QCheckBox(self.tr("Clean up analog image (AI)"), self)
        self._restore.toggled.connect(lambda on: self._set_flag("restore", on))
        self._remove_osd = QCheckBox(self.tr("Remove OSD"), self)
        self._remove_osd.setToolTip(self.tr("The model also removes the OSD (voltage, timer, …); "
                                            "otherwise it keeps it sharp"))
        self._remove_osd.toggled.connect(lambda on: self._set_flag("remove_osd", on))
        self.refresh_restore(update=False)
        osd_row = QHBoxLayout()
        osd_row.addSpacing(20)
        osd_row.addWidget(self._remove_osd)
        osd_row.addStretch(1)

        form = QFormLayout()
        self.sliders: dict[str, QSlider] = {}
        self._labels: dict[str, QLabel] = {}
        for name, (label, steps, _fmt) in SLIDERS.items():
            low, high, neutral = RANGES[name]
            slider = QSlider(Qt.Orientation.Horizontal, self)
            slider.setRange(round(low * steps), round(high * steps))
            slider.setValue(round(neutral * steps))
            slider.setPageStep(max((slider.maximum() - slider.minimum()) // 20, 1))
            tooltip = self.tr(TOOLTIPS[name]) if name in TOOLTIPS else ""
            slider.setToolTip("\n".join(filter(None, [tooltip, self.tr("Double-click: back to neutral")])))
            slider.sliderPressed.connect(self._on_press)
            slider.sliderReleased.connect(self._on_release)
            slider.valueChanged.connect(self._on_value)
            value = QLabel(self)
            value.setMinimumWidth(56)
            value.setToolTip(self.tr("Double-click: back to neutral"))
            # Doppelklick auf Regler oder Wert setzt zurück (Ereignisfilter, da Qt-Methoden
            # in PySide nicht per Zuweisung überschrieben werden können).
            slider.installEventFilter(self)
            value.installEventFilter(self)
            self._reset_targets[slider] = self._reset_targets[value] = name
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(value)
            form.addRow(self.tr("{label}:").format(label=self.tr(label)), row)
            self.sliders[name] = slider
            self._labels[name] = value

        self._lut_label = QLabel(self.tr("none"), self)
        self._lut_label.setWordWrap(True)
        choose = QPushButton(self.tr("Choose LUT …"), self)
        choose.setToolTip(self.tr("3D LUT in .cube format, e.g. for converting D-Log/flat footage"))
        choose.clicked.connect(self.choose_lut)
        self._clear_lut = QToolButton(self)
        self._clear_lut.setText("✕")
        self._clear_lut.setToolTip(self.tr("Remove LUT"))
        self._clear_lut.clicked.connect(lambda: self.set_lut(None))
        lut_row = QHBoxLayout()
        lut_row.addWidget(choose)
        lut_row.addWidget(self._clear_lut)
        lut_row.addStretch(1)
        form.addRow(self.tr("LUT:"), lut_row)
        form.addRow("", self._lut_label)

        self._auto = QPushButton(self.tr("✨ Automatic"), self)
        self._auto.setToolTip(
            self.tr("Measures a few frames of the clip and sets brightness, contrast, gamma, shadows, highlights, "
                    "vibrance and temperature to suit (LUT and sharpness stay). Can be fine-tuned by hand afterwards.")
        )
        self._auto.clicked.connect(self.auto_grade)
        self._reset = QPushButton(self.tr("Reset"), self)
        self._reset.clicked.connect(self.reset)
        self._to_all = QPushButton(self.tr("Apply to all clips"), self)
        self._to_all.setToolTip(self.tr("The same correction for all clips of the timeline, e.g. with the same camera"))
        self._to_all.clicked.connect(self.apply_to_all)
        buttons = QHBoxLayout()
        buttons.addWidget(self._reset)
        buttons.addWidget(self._to_all)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._hint)
        layout.addWidget(self._restore)
        layout.addLayout(osd_row)
        auto_row = QHBoxLayout()
        auto_row.addWidget(self._auto)
        auto_row.addStretch(1)
        layout.addLayout(auto_row)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addStretch(1)

        timeline_panel.view.selection_changed.connect(self.refresh)
        timeline_panel.changed.connect(self.refresh)  # z. B. nach Rückgängig
        self.refresh()

    def refresh_restore(self, update: bool = True) -> None:
        """Prüfen, ob die KI-Reinigung verfügbar ist (ONNX Runtime, normales Modell)."""
        self._restore_problem = restore.problem("normal")
        if self._restore_problem:
            self._restore.setToolTip(self.tr("Not available: {reason}").format(reason=self._restore_problem))
        else:
            self._restore.setToolTip(
                self.tr("Removes noise, rainbow stripes and color tears from analog FPV footage "
                        "(normal model, live in the preview). Runs before the color correction. "
                        "When rendering, the slower high-quality model can be used instead.")
            )
        if update:
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
        for widget in (*self.sliders.values(), self._auto, self._reset, self._to_all, self._clear_lut):
            widget.setEnabled(enabled)
        several = enabled and len(self.targets()) > 1
        self._to_all.setText(self.tr("Apply to selected clips") if several else self.tr("Apply to all clips"))
        self._to_all.setToolTip(
            self.tr("The complete correction of this clip for all selected clips") if several
            else self.tr("The same correction for all clips of the timeline, e.g. with the same camera")
        )
        if several:
            targets = self.targets()
            clip = self.timeline_panel.timeline.clips[index]
            self._hint.setText(
                self.tr("{count} clips selected. The sliders show “{label}” (clip {number}); "
                        "a change applies only this value to all selected clips.").format(
                    count=len(targets), label=clip.label, number=index + 1)
            )
        elif enabled:
            clip = self.timeline_panel.timeline.clips[index]
            self._hint.setText(self.tr("Color correction for “{label}” (clip {number}).").format(label=clip.label, number=index + 1))
        else:
            self._hint.setText(self.tr("Click a clip in the timeline to correct its colors."))
        grade = self.current_grade()
        self._updating = True
        for name, slider in self.sliders.items():
            steps = SLIDERS[name][1]
            slider.setValue(round(getattr(grade, name) * steps))
            self._labels[name].setText(SLIDERS[name][2](getattr(grade, name)))
        self._lut_label.setText(Path(grade.lut).name if grade.lut else self.tr("none"))
        self._lut_label.setToolTip(grade.lut or "")
        self._clear_lut.setEnabled(enabled and bool(grade.lut))
        self._restore.setChecked(grade.restore)
        self._remove_osd.setChecked(grade.remove_osd)
        # Ausschalten geht auch, wenn die Reinigung gerade nicht verfügbar ist.
        self._restore.setEnabled(enabled and (not self._restore_problem or grade.restore))
        self._remove_osd.setEnabled(enabled and grade.restore)
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

    def _set_flag(self, name: str, on: bool) -> None:
        """Schalter der KI-Reinigung (``restore`` oder ``remove_osd``) für die ausgewählten Clips."""
        if self._updating or self.current_index() is None:
            return
        grade = self.current_grade()
        setattr(grade, name, on)
        self._store(grade, remember=True)

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
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Choose LUT"), current or "", self.tr("3D LUT (*.cube)"))
        if path:
            self.set_lut(path)

    def auto_grade(self) -> None:
        """Zauberstab: jeden ausgewählten Clip messen und seine Regler passend setzen."""
        if self.current_index() is None:
            return
        clips = self.timeline_panel.timeline.clips
        grades, problems = {}, []
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ffmpeg = find_tool("ffmpeg")
            for index in self.targets():
                clip = clips[index]
                own = Grade.from_dict(clip.grade)
                if clip.path is None:
                    problems.append(clip.label)
                    continue
                try:
                    stats = measure(ffmpeg, clip.path, clip.src_in, clip.src_out, own.lut)
                except (OSError, ValueError, subprocess.SubprocessError):
                    problems.append(clip.label)
                    continue
                grades[index] = suggest(stats, own).to_dict()
        except FFmpegNotFound as exc:
            problems.append(str(exc))
        finally:
            QGuiApplication.restoreOverrideCursor()
        if grades:
            self._updating = True
            try:
                self.timeline_panel.set_grades(grades, remember=True)  # ein Rückgängig-Schritt für alle
            finally:
                self._updating = False
            self.refresh()
            self.grade_changed.emit()
        if problems:
            self._hint.setText(self.tr("Automatic not possible for: {clips}").format(clips=", ".join(problems)))

    def reset(self) -> None:
        """Farben aller ausgewählten Clips ganz auf neutral; die KI-Reinigung bleibt, wie sie ist."""
        if self.current_index() is None:
            return
        clips = self.timeline_panel.timeline.clips
        grades = {}
        for index in self.targets():
            own = Grade.from_dict(clips[index].grade)
            grades[index] = Grade(restore=own.restore, remove_osd=own.remove_osd).to_dict()
        self.timeline_panel.set_grades(grades)
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
