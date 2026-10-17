"""Hauptfenster: Player, Tastenkürzel und Systemcheck."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QMessageBox

from fpvcut import __version__
from fpvcut.core.ffmpeg_tools import EncoderReport, FFmpegNotFound, check_encoders
from fpvcut.ui.player import PlayerWidget

VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.MP4 *.MOV *.MKV *.AVI);;Alle Dateien (*)"


class _CheckSignals(QObject):
    finished = Signal(object)  # EncoderReport
    failed = Signal(str)


class _EncoderCheck(QRunnable):
    """Prüft ffmpeg im Hintergrund, damit das Fenster sofort bedienbar ist."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = _CheckSignals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(check_encoders())
        except FFmpegNotFound as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"ffmpeg-Check fehlgeschlagen: {exc}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"FPVCut {__version__}")
        self.resize(1280, 800)
        self.encoder_report: EncoderReport | None = None

        self.player = PlayerWidget(self)
        self.player.double_clicked.connect(self.toggle_fullscreen)
        self.setCentralWidget(self.player)

        self._ffmpeg_status = QLabel("ffmpeg: wird geprüft …")
        self.statusBar().addPermanentWidget(self._ffmpeg_status)

        self._build_menu()
        self._start_encoder_check()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datei")
        self._add_action(file_menu, "Video &öffnen …", "Ctrl+O", self.open_video_dialog)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Beenden", "Ctrl+Q", self.close)

        play_menu = self.menuBar().addMenu("&Wiedergabe")
        self._add_action(play_menu, "Abspielen/Pause", "Space", self.player.toggle_pause)
        self._add_action(play_menu, "Frame vor", "Right", lambda: self.player.step_frame(True))
        self._add_action(play_menu, "Frame zurück", "Left", lambda: self.player.step_frame(False))
        self._add_action(play_menu, "1 s vor", "Shift+Right", lambda: self.player.seek_relative(1))
        self._add_action(play_menu, "1 s zurück", "Shift+Left", lambda: self.player.seek_relative(-1))
        self._add_action(play_menu, "5 s vor", "L", lambda: self.player.seek_relative(5))
        self._add_action(play_menu, "5 s zurück", "J", lambda: self.player.seek_relative(-5))

        play_menu.addSeparator()
        self._add_action(play_menu, "Vollbild", "F11", self.toggle_fullscreen)
        self._add_action(play_menu, "Vollbild beenden", "Esc", self.exit_fullscreen)

        help_menu = self.menuBar().addMenu("&Hilfe")
        self._add_action(help_menu, "&Systemcheck …", None, self.show_system_check)

    def _add_action(self, menu, text: str, shortcut: str | None, slot) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        # Auch am Fenster registrieren, sonst greifen die Kürzel bei ausgeblendetem Menü nicht.
        self.addAction(action)
        return action

    def open_video_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Video öffnen", "", VIDEO_FILTER)
        if path:
            self.open_video(Path(path))

    def open_video(self, path: Path) -> None:
        self.player.open(path)
        self.statusBar().showMessage(str(path))

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
            return
        self._was_maximized = self.isMaximized()
        self.menuBar().hide()
        self.statusBar().hide()
        self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self.menuBar().show()
        self.statusBar().show()
        if getattr(self, "_was_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()

    # --- Systemcheck -----------------------------------------------------

    def _start_encoder_check(self) -> None:
        task = _EncoderCheck()
        task.signals.finished.connect(self._on_encoder_report)
        task.signals.failed.connect(self._on_encoder_failed)
        QThreadPool.globalInstance().start(task)

    def _on_encoder_report(self, report: EncoderReport) -> None:
        self.encoder_report = report
        gpu = ", ".join(report.gpu_encoders) or "keine GPU, CPU-Encoding"
        self._ffmpeg_status.setText(f"ffmpeg OK · {gpu}")

    def _on_encoder_failed(self, message: str) -> None:
        self._ffmpeg_status.setText("ffmpeg fehlt")
        self._ffmpeg_status.setToolTip(message)

    def show_system_check(self) -> None:
        report = self.encoder_report
        mpv_state = "OK" if self.player.available else "nicht gefunden"
        if report is None:
            text = f"libmpv: {mpv_state}\nffmpeg: {self._ffmpeg_status.toolTip() or 'Prüfung läuft noch.'}"
        else:
            def best(codec: str) -> str:
                return report.best_encoder(codec) or "nicht verfügbar"

            text = (
                f"libmpv: {mpv_state}\n"
                f"ffmpeg: {report.ffmpeg}\n{report.version}\n"
                f"ffprobe: {report.ffprobe or 'nicht gefunden'}\n\n"
                f"Funktionierende GPU-Encoder: {', '.join(report.gpu_encoders) or 'keine'}\n"
                f"H.264 → {best('h264')}\nH.265 → {best('hevc')}\nAV1 → {best('av1')}"
            )
        QMessageBox.information(self, "Systemcheck", text)

    def closeEvent(self, event) -> None:  # noqa: N802  (Qt-Name)
        self.player.shutdown()
        super().closeEvent(event)
