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
from fpvcut.i18n import translate
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
        self.setWindowTitle(self.tr("Render timeline"))
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
            self._profile.addItem(translate("profiles", profile.label), profile.key)
        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")

        self._resolution = QComboBox(self)
        self._resolution.addItem(self.tr("Same as source ({width} × {height})").format(width=source.width, height=source.height),
                                 f"{source.width}x{source.height}")
        for w, h in RESOLUTIONS:
            if (w, h) != (source.width, source.height):
                self._resolution.addItem(f"{w} × {h}", f"{w}x{h}")
        self._fps = QComboBox(self)
        self._fps.addItem(self.tr("Same as source ({fps} fps)").format(fps=f"{source.fps:g}"), source.fps)
        for fps in FRAME_RATES:
            if fps != source.fps:
                self._fps.addItem(f"{fps} fps", float(fps))
        self._quality = QSpinBox(self)
        self._quality.setRange(10, 40)
        self._quality.setToolTip(self.tr("Lower = better quality and larger file (CQ with NVENC, CRF on the CPU)"))
        self._encoder = QLabel(self)

        self._path = QLineEdit(self)
        browse = QPushButton("…", self)
        browse.setFixedWidth(32)
        browse.clicked.connect(self._choose_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self._path, 1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.addRow(self.tr("Profile:"), self._profile)
        form.addRow("", self._hint)
        form.addRow(self.tr("Resolution:"), self._resolution)
        form.addRow(self.tr("Frame rate:"), self._fps)
        form.addRow(self.tr("Quality:"), self._quality)
        form.addRow(self.tr("Encoder:"), self._encoder)
        form.addRow(self.tr("File:"), path_row)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        self._status = QLabel(self.tr("Timeline length: {duration}").format(duration=format_duration(timeline.duration)), self)
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._open_folder = QPushButton(self.tr("Open folder"), self)
        self._open_folder.clicked.connect(lambda: self._open(self._output.parent if self._output else None))
        self._play = QPushButton(self.tr("Play"), self)
        self._play.clicked.connect(lambda: self._open(self._output))
        self._start = QPushButton(self.tr("Render"), self)
        self._start.setDefault(True)
        self._start.clicked.connect(self.start)
        self._close = QPushButton(self.tr("Close"), self)
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
        self._hint.setText(translate("profiles", profile.hint))
        self._quality.setValue(profile.quality)
        encoder = self.encoder()
        kind = "GPU" if encoder in GPU_ENCODERS else self.tr("CPU, slower")
        self._encoder.setText(f"{encoder} ({kind})")
        current = Path(self._path.text()) if self._path.text() else None
        if current is None or current.name.startswith("fpvcut_"):
            self._path.setText(str(default_output(profile.key)))

    def _choose_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Output file"), self._path.text(), self.tr("MP4 video (*.mp4)"))
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
            answer = QMessageBox.question(
                self, self.tr("Overwrite file"),
                self.tr("{name} already exists. Overwrite?").format(name=settings.output.name))
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            settings.output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._status.setText(self.tr("Folder cannot be created: {error}").format(error=exc))
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
        self._status.setText(self.tr("Rendering starts …"))
        self._process.start()
        return True

    def _set_running(self, running: bool) -> None:
        for widget in (self._profile, self._resolution, self._fps, self._quality, self._path, self._start):
            widget.setEnabled(not running)
        self._close.setText(self.tr("Cancel") if running else self.tr("Close"))
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
        text = self.tr("{done} of {total} · {speed}× real time").format(
            done=format_duration(done), total=format_duration(total), speed=f"{speed:.1f}")
        if remaining is not None:
            text += self.tr(" · about {remaining} left").format(remaining=format_duration(remaining))
        self._status.setText(text)

    def _read_errors(self) -> None:
        self._stderr += bytes(self._process.readAllStandardError()).decode(errors="replace")
        self._stderr = self._stderr[-4000:]

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._set_running(False)
            self._status.setText(self.tr("ffmpeg could not be started: {path}").format(path=self.ffmpeg))

    def _on_finished(self, code: int, _status) -> None:
        self._set_running(False)
        elapsed = format_duration(time.monotonic() - self._started)
        if self._cancelled:
            self._output.unlink(missing_ok=True)
            self._progress.setValue(0)
            self._status.setText(self.tr("Cancelled, the unfinished file was deleted."))
        elif code != 0:
            self._progress.setValue(0)
            lines = [line for line in self._stderr.strip().splitlines() if line.strip()][-6:]
            details = "\n".join(lines) or self.tr("ffmpeg error code {code}").format(code=code)
            self._status.setText(self.tr("Rendering failed:") + "\n" + details)
        else:
            self._progress.setValue(1000)
            size = self._output.stat().st_size / 1_000_000 if self._output.exists() else 0
            self._status.setText(self.tr("Done in {elapsed}: {path} ({size} MB)").format(elapsed=elapsed, path=self._output, size=f"{size:.1f}"))
            self._open_folder.show()
            self._play.show()

    def cancel(self) -> None:
        if self.running:
            self._cancelled = True
            self._process.kill()

    def reject(self) -> None:
        if self.running:
            answer = QMessageBox.question(self, self.tr("Cancel rendering"), self.tr("Cancel rendering?"))
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
