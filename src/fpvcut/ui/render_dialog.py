"""Render-Dialog: Profil wählen, ffmpeg im Hintergrund laufen lassen, Fortschritt zeigen.

Haben Clips die KI-Reinigung eingeschaltet, werden sie vorher einzeln gereinigt (Schüler oder,
mit Haken, der bessere, langsamere Lehrer mit wählbarem Stride); erst dann läuft ffmpeg.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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

from fpvcut import restore
from fpvcut.core.ffmpeg_tools import GPU_ENCODERS, EncoderReport
from fpvcut.render.command import RenderSettings, SourceFormat, build_command, parse_progress
from fpvcut.render.profiles import PROFILES, profile_by_key
from fpvcut.i18n import translate
from fpvcut.timeline.grade import Grade
from fpvcut.timeline.model import Timeline
from fpvcut.ui.library_panel import format_duration

RESOLUTIONS = [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]
FRAME_RATES = [24, 25, 30, 50, 60]
CPU_FALLBACK = {"h264": "libx264", "hevc": "libx265"}
# Ungefähre Bilder pro Sekunde auf einer RTX 3070 (halbe Auflösung), nur für die Zeitschätzung
TEACHER_FPS_PER_STRIDE = 2.1
STUDENT_FPS = 60.0


def app_settings() -> QSettings:
    return QSettings("FPVCut", "FPVCut")


def default_output(profile_key: str) -> Path:
    settings = app_settings()
    folder = settings.value("render/dir") or str(
        Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)) / "FPVCut"
    )
    return Path(folder) / f"fpvcut_{datetime.now():%Y-%m-%d_%H%M}_{profile_key}.mp4"


class _RestoreJob(QObject):
    """Reinigt die Clips nacheinander in einem eigenen Thread; Signale kommen im Qt-Thread an."""

    progress = Signal(int, int)  # fertige Bilder, Bilder insgesamt
    finished = Signal(object)  # {Clip-Index: Zwischendatei}, oder Fehlertext (str), oder None = abgebrochen

    def __init__(self, ffmpeg: Path, jobs: list, folder: Path, kind: str, stride: int, gpu_encoder: bool) -> None:
        super().__init__()
        self.ffmpeg, self.jobs, self.folder = ffmpeg, jobs, folder
        self.kind, self.stride, self.gpu_encoder = kind, stride, gpu_encoder
        self.stopped = threading.Event()
        self.total = sum(spec.frames for _, spec in jobs)
        self._thread = threading.Thread(target=self._run, daemon=True, name="fpvcut-restore")

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        from fpvcut.restore.render import Cancelled, restore_clip  # noqa: PLC0415  (lädt PyTorch)

        models = restore.models()
        outputs, done = {}, 0
        try:
            for index, spec in self.jobs:
                output = self.folder / f"clip_{index:03d}.mp4"
                restore_clip(self.ffmpeg, spec, models, output, kind=self.kind, stride=self.stride,
                             gpu_encoder=self.gpu_encoder, stopped=self.stopped,
                             progress=lambda n, base=done: self.progress.emit(base + n, self.total))
                done += spec.frames
                outputs[index] = output
            self.finished.emit(outputs)
        except Cancelled:
            self.finished.emit(None)
        except Exception as exc:  # noqa: BLE001  (Grafikkarte, Speicher, ffmpeg: alles im Dialog melden)
            self.finished.emit(str(exc).strip().splitlines()[-1] if str(exc).strip() else type(exc).__name__)
        finally:
            if self.kind == "teacher":
                models.release("teacher")  # fast 4 GB Grafikspeicher wieder frei für die Vorschau


class RenderDialog(QDialog):
    def __init__(
        self,
        timeline: Timeline,
        source: SourceFormat,
        ffmpeg: Path,
        report: EncoderReport | None,
        marked: tuple[float, float] | None = None,
        parent: QWidget | None = None,
        formats: Callable[[Timeline], list[SourceFormat | None]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Render timeline"))
        self.setMinimumWidth(560)
        self.timeline = timeline
        self.source = source
        self.ffmpeg = ffmpeg
        self.report = report
        self._process: QProcess | None = None
        self._formats = formats
        self._restore_job: _RestoreJob | None = None
        self._restored: dict[int, Path] = {}
        self._temp: Path | None = None  # Ordner der gereinigten Zwischendateien
        self._cancelled = False
        self._started = 0.0
        self._stderr = ""
        self._output: Path | None = None
        self._rendering = timeline  # was gerade gerendert wird: alles oder nur der Bereich

        # Mit markiertem Bereich: nur ihn oder alles rendern (vorgewählt ist der Bereich).
        self._range = QComboBox(self)
        if marked is not None:
            start, end = marked
            self._range.addItem(self.tr("Marked range ({start} – {end}, {length})").format(
                start=format_duration(start), end=format_duration(end), length=format_duration(end - start)), marked)
        self._range.addItem(self.tr("Whole timeline ({length})").format(length=format_duration(timeline.duration)), None)
        self._range.setVisible(marked is not None)

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
        if marked is not None:
            form.addRow(self.tr("Render:"), self._range)
        form.addRow(self.tr("Profile:"), self._profile)
        form.addRow("", self._hint)
        form.addRow(self.tr("Resolution:"), self._resolution)
        form.addRow(self.tr("Frame rate:"), self._fps)
        form.addRow(self.tr("Quality:"), self._quality)
        form.addRow(self.tr("Encoder:"), self._encoder)
        form.addRow(self.tr("File:"), path_row)

        # KI-Reinigung: welches Modell für die Clips, bei denen sie eingeschaltet ist
        stored = app_settings()
        self._restore_info = QLabel(self)
        self._restore_info.setWordWrap(True)
        self._teacher = QCheckBox(self.tr("Use the teacher model (best quality, much slower)"), self)
        self._teacher.setChecked(stored.value("render/teacher", False, type=bool))
        self._stride = QSpinBox(self)
        self._stride.setRange(1, 5)
        self._stride.setValue(int(stored.value("render/stride", 3)))
        self._stride.setToolTip(
            self.tr("The teacher cleans 5 frames at a time. Stride 1 uses only the middle one (best, slowest), "
                    "stride 5 all five: about five times as fast, slightly worse, it can jump a little "
                    "every 5 frames.")
        )
        self._stride_hint = QLabel(self.tr("1 = best, 5 = about five times as fast"), self)
        self._stride_hint.setStyleSheet("color: gray;")
        stride_row = QHBoxLayout()
        stride_row.addWidget(self._stride)
        stride_row.addWidget(self._stride_hint, 1)
        form.addRow(self.tr("AI cleanup:"), self._restore_info)
        form.addRow("", self._teacher)
        form.addRow(self.tr("Stride:"), stride_row)
        self._teacher.toggled.connect(self._update_restore)
        self._stride.valueChanged.connect(self._update_restore)
        self._range.currentIndexChanged.connect(self._update_restore)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        length = "" if marked else self.tr("Timeline length: {duration}").format(duration=format_duration(timeline.duration))
        self._status = QLabel(length, self)
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
        self._update_restore()

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

    def render_timeline(self) -> Timeline:
        """Die ganze Timeline oder nur der gewählte Bereich."""
        marked = self._range.currentData()
        return self.timeline if marked is None else self.timeline.excerpt(*marked)

    def settings(self) -> RenderSettings:
        width, height = (int(v) for v in self._resolution.currentData().split("x"))
        profile = self.profile
        return RenderSettings(
            output=Path(self._path.text()).expanduser(),
            width=width, height=height, fps=self._fps.currentData(),
            encoder=self.encoder(), quality=self._quality.value(),
            audio_bitrate=profile.audio_bitrate, ten_bit=profile.ten_bit, faststart=profile.faststart,
        )

    # --- KI-Reinigung ----------------------------------------------------

    @staticmethod
    def restored_clips(timeline: Timeline) -> list[int]:
        return [i for i, clip in enumerate(timeline.clips) if Grade.from_dict(clip.grade).restore]

    @property
    def restore_kind(self) -> str:
        return "teacher" if self._teacher.isChecked() else "student"

    def _model_name(self, kind: str) -> str:
        return self.tr("teacher") if kind == "teacher" else self.tr("student")

    def _update_restore(self) -> None:
        timeline = self.render_timeline()
        clips = self.restored_clips(timeline)
        self._teacher.setEnabled(bool(clips))
        self._stride.setEnabled(bool(clips) and self._teacher.isChecked())
        self._stride_hint.setEnabled(self._stride.isEnabled())
        if not clips:
            self._restore_info.setText(self.tr("No clip uses it (switch it on in the Color tab)."))
            self._restore_info.setStyleSheet("color: gray;")
            return
        if problem := restore.problem(self.restore_kind):
            self._restore_info.setText(self.tr("Not available: {reason}").format(reason=problem))
            self._restore_info.setStyleSheet("color: #c0392b;")
            return
        formats = self._clip_formats(timeline)
        frames = sum(round(timeline.clips[i].duration * formats[i].fps) for i in clips)
        rate = TEACHER_FPS_PER_STRIDE * self._stride.value() if self._teacher.isChecked() else STUDENT_FPS
        self._restore_info.setText(
            self.tr("%n clip(s) with the {model} model, about {time} before rendering", "", len(clips)).format(
                model=self._model_name(self.restore_kind), time=format_duration(frames / rate))
        )
        self._restore_info.setStyleSheet("")

    def _clip_formats(self, timeline: Timeline) -> list[SourceFormat]:
        """Format je Clip; wo es unbekannt ist, das der Timeline."""
        formats = self._formats(timeline) if self._formats else []
        formats += [None] * (len(timeline.clips) - len(formats))
        return [fmt if fmt is not None and fmt.fps else self.source for fmt in formats]

    def restore_jobs(self, timeline: Timeline) -> list:
        """(Index, ClipSpec) für jeden Clip mit KI-Reinigung."""
        from fpvcut.restore.engine import ClipSpec, Geometry  # noqa: PLC0415  (lädt PyTorch)

        formats = self._clip_formats(timeline)
        jobs = []
        for index in self.restored_clips(timeline):
            clip, fmt = timeline.clips[index], formats[index]
            geometry = Geometry.for_source(fmt.width, fmt.height)
            jobs.append((index, ClipSpec(clip.path, clip.src_in, clip.duration, fmt.fps, geometry,
                                         Grade.from_dict(clip.grade).remove_osd)))
        return jobs

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
        stored = app_settings()
        stored.setValue("render/dir", str(settings.output.parent))
        stored.setValue("render/teacher", self._teacher.isChecked())
        stored.setValue("render/stride", self._stride.value())
        self.timeline.render_profile = self.profile.key
        self._output = settings.output
        self._settings = settings
        self._rendering = self.render_timeline()
        self._restored = {}
        self._cancelled = False
        self._stderr = ""
        self._started = time.monotonic()
        if self.restored_clips(self._rendering):
            return self._start_restore()
        self._start_ffmpeg()
        return True

    def _start_restore(self) -> bool:
        """Erst die Clips mit KI-Reinigung einzeln reinigen, danach rendert ffmpeg."""
        if problem := restore.problem(self.restore_kind):
            self._status.setText(self.tr("AI cleanup not available: {reason}").format(reason=problem))
            return False
        try:
            jobs = self.restore_jobs(self._rendering)
        except ImportError as exc:
            self._status.setText(self.tr("AI cleanup not available: {reason}").format(reason=exc))
            return False
        self._temp = Path(tempfile.mkdtemp(prefix="fpvcut_ki_"))
        gpu = self.report is not None and "h264_nvenc" in self.report.working
        self._restore_job = _RestoreJob(self.ffmpeg, jobs, self._temp, self.restore_kind, self._stride.value(), gpu)
        self._restore_job.progress.connect(self._on_restore_progress)
        self._restore_job.finished.connect(self._on_restore_finished)
        self._set_running(True)
        self._status.setText(self.tr("AI cleanup starts (loading the model) …"))
        self._restore_job.start()
        return True

    def _on_restore_progress(self, done: int, total: int) -> None:
        if self._restore_job is None:
            return
        self._progress.setValue(int(done / max(total, 1) * 1000))
        elapsed = time.monotonic() - self._started
        rate = done / elapsed if elapsed > 0 else 0
        text = self.tr("AI cleanup ({model}): frame {done} of {total} · {rate} frames/s").format(
            model=self._model_name(self._restore_job.kind), done=done, total=total, rate=f"{rate:.1f}")
        if rate > 0:
            text += self.tr(" · about {remaining} left").format(remaining=format_duration((total - done) / rate))
        self._status.setText(text)

    def _on_restore_finished(self, result) -> None:
        self._restore_job = None
        if isinstance(result, dict) and not self._cancelled:
            self._restored = result
            self._start_ffmpeg()
            return
        self._set_running(False)
        self._progress.setValue(0)
        self._remove_temp()
        if result is None or self._cancelled:
            self._status.setText(self.tr("Cancelled."))
        else:
            self._status.setText(self.tr("AI cleanup failed:") + "\n" + str(result))

    def _remove_temp(self) -> None:
        if self._temp is not None:
            shutil.rmtree(self._temp, ignore_errors=True)
            self._temp = None

    def _start_ffmpeg(self) -> None:
        command = build_command(self.ffmpeg, self._rendering, self._settings, self._restored)
        self._process = QProcess(self)
        self._process.setProgram(command[0])
        self._process.setArguments(command[1:])
        self._process.readyReadStandardOutput.connect(self._read_progress)
        self._process.readyReadStandardError.connect(self._read_errors)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._render_started = time.monotonic()
        self._set_running(True)
        self._status.setText(self.tr("Rendering starts …"))
        self._process.start()

    def _set_running(self, running: bool) -> None:
        for widget in (self._range, self._profile, self._resolution, self._fps, self._quality, self._path, self._start):
            widget.setEnabled(not running)
        if running:
            self._teacher.setEnabled(False)
            self._stride.setEnabled(False)
        else:
            self._update_restore()
        self._close.setText(self.tr("Cancel") if running else self.tr("Close"))
        self._open_folder.setVisible(False)
        self._play.setVisible(False)

    @property
    def running(self) -> bool:
        if self._restore_job is not None:
            return True
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def _read_progress(self) -> None:
        data = bytes(self._process.readAllStandardOutput()).decode(errors="replace")
        done = None
        for line in data.splitlines():
            if (seconds := parse_progress(line)) is not None:
                done = seconds
        total = self._rendering.duration
        if done is None or total <= 0:
            return
        fraction = min(done / total, 1.0)
        self._progress.setValue(int(fraction * 1000))
        elapsed = time.monotonic() - self._render_started
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
            self._remove_temp()
            self._status.setText(self.tr("ffmpeg could not be started: {path}").format(path=self.ffmpeg))

    def _on_finished(self, code: int, _status) -> None:
        self._set_running(False)
        self._remove_temp()
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
            if self._restore_job is not None:
                self._restore_job.stopped.set()
            elif self._process is not None:
                self._process.kill()

    def reject(self) -> None:
        if self.running:
            answer = QMessageBox.question(self, self.tr("Cancel rendering"), self.tr("Cancel rendering?"))
            if answer == QMessageBox.StandardButton.Yes:
                self.cancel()
            return
        super().reject()

    def wait(self, msecs: int = 60000) -> bool:
        """Für Tests: auf das Ende der KI-Reinigung und von ffmpeg warten."""
        deadline = time.monotonic() + msecs / 1000
        while self._restore_job is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        if self._restore_job is not None:
            return False
        left = max(int((deadline - time.monotonic()) * 1000), 1)
        return self._process is None or self._process.waitForFinished(left)

    @staticmethod
    def _open(path: Path | None) -> None:
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
