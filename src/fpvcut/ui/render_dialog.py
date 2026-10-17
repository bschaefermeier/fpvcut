"""Render-Dialog: Profil wählen, ffmpeg im Hintergrund laufen lassen, Fortschritt zeigen."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core.ffmpeg_tools import GPU_ENCODERS, EncoderReport
from fpvcut.render.command import RenderSettings, SourceFormat, build_command, parse_progress
from fpvcut.render.profiles import PROFILES, profile_by_key
from fpvcut.timeline.model import Timeline
from fpvcut.ui.library_panel import format_duration

RESOLUTIONS = [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]
FRAME_RATES = [24, 25, 30, 50, 60]
CPU_FALLBACK = {"h264": "libx264", "hevc": "libx265"}


def app_settings() -> QSettings:
    return QSettings("FPVCut", "FPVCut")


def default_output(profile_key: str) -> Path:
    settings = app_settings()
    folder = settings.value("render/dir") or str(
        Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)) / "FPVCut"
    )
    return Path(folder) / f"fpvcut_{datetime.now():%Y-%m-%d_%H%M}_{profile_key}.mp4"


class RenderDialog(QDialog):
    def __init__(
        self,
        timeline: Timeline,
        source: SourceFormat,
        ffmpeg: Path,
        report: EncoderReport | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Timeline rendern")
        self.setMinimumWidth(560)
        self.timeline = timeline
        self.source = source
        self.ffmpeg = ffmpeg
        self.report = report
        self._process: QProcess | None = None
        self._cancelled = False
        self._started = 0.0
        self._stderr = ""
        self._output: Path | None = None

        self._profile = QComboBox(self)
        for profile in PROFILES:
            self._profile.addItem(profile.label, profile.key)
        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")

        self._resolution = QComboBox(self)
        self._resolution.addItem(f"Wie Quelle ({source.width} × {source.height})", f"{source.width}x{source.height}")
        for w, h in RESOLUTIONS:
            if (w, h) != (source.width, source.height):
                self._resolution.addItem(f"{w} × {h}", f"{w}x{h}")
        self._fps = QComboBox(self)
        self._fps.addItem(f"Wie Quelle ({source.fps:g} fps)", source.fps)
        for fps in FRAME_RATES:
            if fps != source.fps:
                self._fps.addItem(f"{fps} fps", float(fps))
        self._quality = QSpinBox(self)
        self._quality.setRange(10, 40)
        self._quality.setToolTip("Kleiner = bessere Qualität und größere Datei (CQ bei NVENC, CRF auf der CPU)")
        self._encoder = QLabel(self)

        self._path = QLineEdit(self)
        browse = QPushButton("…", self)
        browse.setFixedWidth(32)
        browse.clicked.connect(self._choose_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self._path, 1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Profil:", self._profile)
        form.addRow("", self._hint)
        form.addRow("Auflösung:", self._resolution)
        form.addRow("Bildrate:", self._fps)
        form.addRow("Qualität:", self._quality)
        form.addRow("Encoder:", self._encoder)
        form.addRow("Datei:", path_row)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        self._status = QLabel(f"Länge der Timeline: {format_duration(timeline.duration)}", self)
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._open_folder = QPushButton("Ordner öffnen", self)
        self._open_folder.clicked.connect(lambda: self._open(self._output.parent if self._output else None))
        self._play = QPushButton("Abspielen", self)
        self._play.clicked.connect(lambda: self._open(self._output))
        self._start = QPushButton("Rendern", self)
        self._start.setDefault(True)
        self._start.clicked.connect(self.start)
        self._close = QPushButton("Schließen", self)
        self._close.clicked.connect(self.reject)
        for button in (self._open_folder, self._play):
            button.hide()
        buttons = QHBoxLayout()
        buttons.addWidget(self._open_folder)
        buttons.addWidget(self._play)
        buttons.addStretch(1)
        buttons.addWidget(self._start)
        buttons.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        self._profile.currentIndexChanged.connect(self._apply_profile)
        index = self._profile.findData(timeline.render_profile)
        self._profile.setCurrentIndex(max(index, 0))
        self._apply_profile()

    # --- Einstellungen ---------------------------------------------------

    @property
    def profile(self):
        return profile_by_key(self._profile.currentData())

    def encoder(self) -> str:
        codec = self.profile.codec
        if self.report is not None:
            return self.report.best_encoder(codec) or CPU_FALLBACK[codec]
        return CPU_FALLBACK[codec]

    def _apply_profile(self) -> None:
        profile = self.profile
        self._hint.setText(profile.hint)
        self._quality.setValue(profile.quality)
        encoder = self.encoder()
        kind = "GPU" if encoder in GPU_ENCODERS else "CPU, langsamer"
        self._encoder.setText(f"{encoder} ({kind})")
        current = Path(self._path.text()) if self._path.text() else None
        if current is None or current.name.startswith("fpvcut_"):
            self._path.setText(str(default_output(profile.key)))

    def _choose_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Zieldatei", self._path.text(), "MP4-Video (*.mp4)")
        if path:
            self._path.setText(path if path.lower().endswith(".mp4") else path + ".mp4")

    def settings(self) -> RenderSettings:
        width, height = (int(v) for v in self._resolution.currentData().split("x"))
        profile = self.profile
        return RenderSettings(
            output=Path(self._path.text()).expanduser(),
            width=width, height=height, fps=self._fps.currentData(),
            encoder=self.encoder(), quality=self._quality.value(),
            audio_bitrate=profile.audio_bitrate, ten_bit=profile.ten_bit, faststart=profile.faststart,
        )

    # --- Rendern ---------------------------------------------------------

    def start(self) -> bool:
        settings = self.settings()
        if settings.output.exists():
            answer = QMessageBox.question(self, "Datei überschreiben", f"{settings.output.name} existiert schon. Überschreiben?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            settings.output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._status.setText(f"Ordner kann nicht angelegt werden: {exc}")
            return False
        app_settings().setValue("render/dir", str(settings.output.parent))
        self.timeline.render_profile = self.profile.key
        self._output = settings.output

        command = build_command(self.ffmpeg, self.timeline, settings)
        self._process = QProcess(self)
        self._process.setProgram(command[0])
        self._process.setArguments(command[1:])
        self._process.readyReadStandardOutput.connect(self._read_progress)
        self._process.readyReadStandardError.connect(self._read_errors)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._cancelled = False
        self._stderr = ""
        self._started = time.monotonic()
        self._set_running(True)
        self._status.setText("Rendern startet …")
        self._process.start()
        return True

    def _set_running(self, running: bool) -> None:
        for widget in (self._profile, self._resolution, self._fps, self._quality, self._path, self._start):
            widget.setEnabled(not running)
        self._close.setText("Abbrechen" if running else "Schließen")
        self._open_folder.setVisible(False)
        self._play.setVisible(False)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def _read_progress(self) -> None:
        data = bytes(self._process.readAllStandardOutput()).decode(errors="replace")
        done = None
        for line in data.splitlines():
            if (seconds := parse_progress(line)) is not None:
                done = seconds
        total = self.timeline.duration
        if done is None or total <= 0:
            return
        fraction = min(done / total, 1.0)
        self._progress.setValue(int(fraction * 1000))
        elapsed = time.monotonic() - self._started
        speed = done / elapsed if elapsed > 0 else 0
        remaining = (total - done) / speed if speed > 0 else None
        text = f"{format_duration(done)} von {format_duration(total)} · {speed:.1f}× Echtzeit"
        if remaining is not None:
            text += f" · noch ca. {format_duration(remaining)}"
        self._status.setText(text)

    def _read_errors(self) -> None:
        self._stderr += bytes(self._process.readAllStandardError()).decode(errors="replace")
        self._stderr = self._stderr[-4000:]

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._set_running(False)
            self._status.setText(f"ffmpeg konnte nicht gestartet werden: {self.ffmpeg}")

    def _on_finished(self, code: int, _status) -> None:
        self._set_running(False)
        elapsed = format_duration(time.monotonic() - self._started)
        if self._cancelled:
            self._output.unlink(missing_ok=True)
            self._progress.setValue(0)
            self._status.setText("Abgebrochen, die halbfertige Datei wurde gelöscht.")
        elif code != 0:
            self._progress.setValue(0)
            lines = [line for line in self._stderr.strip().splitlines() if line.strip()][-6:]
            self._status.setText("Rendern fehlgeschlagen:\n" + ("\n".join(lines) or f"ffmpeg-Fehlercode {code}"))
        else:
            self._progress.setValue(1000)
            size = self._output.stat().st_size / 1_000_000 if self._output.exists() else 0
            self._status.setText(f"Fertig in {elapsed}: {self._output} ({size:.1f} MB)")
            self._open_folder.show()
            self._play.show()

    def cancel(self) -> None:
        if self.running:
            self._cancelled = True
            self._process.kill()

    def reject(self) -> None:
        if self.running:
            answer = QMessageBox.question(self, "Rendern abbrechen", "Rendern abbrechen?")
            if answer == QMessageBox.StandardButton.Yes:
                self.cancel()
            return
        super().reject()

    def wait(self, msecs: int = 60000) -> bool:
        """Für Tests: auf das Ende von ffmpeg warten."""
        return self._process is None or self._process.waitForFinished(msecs)

    @staticmethod
    def _open(path: Path | None) -> None:
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
