"""Hauptfenster: Bibliothek, Player, Tastenkürzel und Systemcheck."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QStandardPaths, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QMessageBox, QSplitter

from fpvcut import __version__
from fpvcut.core.ffmpeg_tools import EncoderReport, FFmpegNotFound, check_encoders, find_tool
from fpvcut.core.fingerprint import fingerprint
from fpvcut.core.library import Clip, Library, LibraryEntry
from fpvcut.core.marks import resolve_range
from fpvcut.core.probe import probe
from fpvcut.core.scanner import ScanResult, scan_library
from fpvcut.ui.favorite_dialog import FavoriteDialog
from fpvcut.ui.info_panel import InfoPanel, clip_range_text
from fpvcut.ui.library_panel import LibraryPanel
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


def default_db_path() -> Path:
    """``%APPDATA%\\FPVCut\\library.sqlite`` unter Windows; ``FPVCUT_DB`` überschreibt das."""
    if env := os.environ.get("FPVCUT_DB"):
        return Path(env)
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "library.sqlite"


class _ScanSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)  # ScanResult


class _LibraryScan(QRunnable):
    """Scannt im Hintergrund mit eigener Datenbankverbindung."""

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self.signals = _ScanSignals()

    def run(self) -> None:
        try:
            ffprobe = find_tool("ffprobe")
        except FFmpegNotFound:
            ffprobe = None
        library = Library(self.db_path)
        try:
            result = scan_library(
                library,
                (lambda path: probe(ffprobe, path)) if ffprobe else (lambda _path: None),
                self.signals.progress.emit,
            )
        except Exception as exc:  # noqa: BLE001
            result = ScanResult(errors=[f"Scan abgebrochen: {exc}"])
        finally:
            library.close()
        self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"FPVCut {__version__}")
        self.resize(1400, 820)
        self.encoder_report: EncoderReport | None = None
        self.db_path = db_path or default_db_path()
        self.library = Library(self.db_path)
        self._scanning = False
        self.current_entry: LibraryEntry | None = None

        self.player = PlayerWidget(self)
        self.player.double_clicked.connect(self.toggle_fullscreen)
        self.library_panel = LibraryPanel(self)
        self.library_panel.video_activated.connect(self.open_entry)
        self.library_panel.review_toggled.connect(self._on_review_toggled)
        self.info_panel = InfoPanel(self)
        self.info_panel.clip_activated.connect(self.play_clip)
        self.info_panel.clip_edit_requested.connect(self.edit_clip)
        self.info_panel.clip_delete_requested.connect(self.delete_clip)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self.library_panel)
        self._splitter.addWidget(self.player)
        self._splitter.addWidget(self.info_panel)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([380, 760, 300])
        self.setCentralWidget(self._splitter)

        self._ffmpeg_status = QLabel("ffmpeg: wird geprüft …")
        self.statusBar().addPermanentWidget(self._ffmpeg_status)

        self._build_menu()
        self._start_encoder_check()
        self.reload_library()
        self.rescan_library()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datei")
        self._add_action(file_menu, "Video &öffnen …", "Ctrl+O", self.open_video_dialog)
        file_menu.addSeparator()
        self._add_action(file_menu, "Bibliotheksordner &hinzufügen …", "Ctrl+Shift+O", self.add_root_dialog)
        self._add_action(file_menu, "Bibliothek neu &scannen", "F5", self.rescan_library)
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
        self._add_action(play_menu, "Vollbild beenden / Auswahl aufheben", "Esc", self._on_escape)

        fav_menu = self.menuBar().addMenu("F&avoriten")
        self._add_action(fav_menu, "In-Punkt setzen", "I", self.player.set_in)
        self._add_action(fav_menu, "Out-Punkt setzen", "O", self.player.set_out)
        self._add_action(fav_menu, "Ausschnitt als Favorit speichern …", "F", self.save_favorite)
        self._add_action(fav_menu, "Ganzes Video als Favorit speichern …", "Shift+F", self.save_whole_video)

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

    def open_video(self, path: Path, entry: LibraryEntry | None = None) -> None:
        if entry is None:
            entry = self._entry_for_file(path)
        self.player.open(path)
        self.current_entry = entry
        self._refresh_clips()
        self.statusBar().showMessage(str(path))

    def _entry_for_file(self, path: Path) -> LibraryEntry | None:
        """Über Datei → Öffnen gewählte Videos per Fingerprint in der Bibliothek suchen."""
        try:
            media_id = self.library.media_id_for(fingerprint(path))
        except OSError:
            return None
        return self.library.entry_for_media(media_id) if media_id else None

    # --- Bibliothek ------------------------------------------------------

    def reload_library(self) -> None:
        self.library_panel.set_entries(self.library.entries())

    def add_root_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Bibliotheksordner wählen")
        if folder:
            self.library.add_root(folder)
            self.rescan_library()

    def rescan_library(self) -> None:
        if self._scanning:
            return
        if not self.library.roots():
            self.statusBar().showMessage("Tipp: Datei → Bibliotheksordner hinzufügen (z. B. E:\\FPV_Videos)")
            return
        self._scanning = True
        self.library_panel.set_placeholder_text("Bibliothek wird gescannt …")
        task = _LibraryScan(self.db_path)
        task.signals.progress.connect(
            lambda i, n, name: self.statusBar().showMessage(f"Scanne {i}/{n}: {name}")
        )
        task.signals.finished.connect(self._on_scan_finished)
        QThreadPool.globalInstance().start(task)

    def _on_scan_finished(self, result: ScanResult) -> None:
        self._scanning = False
        self.library_panel.set_placeholder_text("Keine Videos gefunden.")
        self.reload_library()
        parts = [f"{result.new} neu"]
        if result.rehashed:
            parts.append(f"{result.rehashed} verschoben/kopiert")
        if result.missing:
            parts.append(f"{result.missing} fehlen")
        message = "Scan fertig: " + ", ".join(parts)
        if result.errors:
            message += f" · {len(result.errors)} Problem(e): {result.errors[0]}"
        self.statusBar().showMessage(message)

    def open_entry(self, entry: LibraryEntry) -> None:
        self.open_video(entry.path, entry)
        if entry.is_new:
            self.library.set_reviewed([entry.media_id])
            self.reload_library()

    def _on_review_toggled(self, media_ids: list[int], reviewed: bool) -> None:
        self.library.set_reviewed(media_ids, reviewed)
        self.reload_library()

    # --- Favoriten -------------------------------------------------------

    def _refresh_clips(self) -> None:
        clips = self.library.clips_for(self.current_entry.media_id) if self.current_entry else []
        self.info_panel.set_entry(self.current_entry, clips)
        self.player.set_clips([(c.in_s, c.out_s) for c in clips])

    def save_favorite(self) -> None:
        if self.current_entry is None:
            self.statusBar().showMessage("Favoriten gehen nur für Videos aus der Bibliothek.")
            return
        in_ms, out_ms = resolve_range(self.player.in_point, self.player.out_point, self.player.position())
        self._save_clip(in_ms, out_ms)

    def save_whole_video(self) -> None:
        if self.current_entry is None:
            self.statusBar().showMessage("Favoriten gehen nur für Videos aus der Bibliothek.")
            return
        self._save_clip(0, None)

    def _save_clip(self, in_ms: int, out_ms: int | None) -> None:
        dialog = FavoriteDialog(
            clip_range_text(in_ms / 1000, None if out_ms is None else out_ms / 1000),
            self.library.all_tags(),
            parent=self,
        )
        if dialog.exec() != FavoriteDialog.DialogCode.Accepted:
            return
        self.library.add_clip(self.current_entry.media_id, in_ms, out_ms, dialog.tags, dialog.note)
        self.player.clear_marks()
        self._refresh_clips()
        self.reload_library()
        tags = ", ".join(dialog.tags) or "ohne Tags"
        self.statusBar().showMessage(f"Favorit gespeichert ({tags})")

    def play_clip(self, clip: Clip) -> None:
        self.player.play_range(clip.in_s, clip.out_s)

    def edit_clip(self, clip: Clip) -> None:
        dialog = FavoriteDialog(
            clip_range_text(clip.in_s, clip.out_s), self.library.all_tags(), clip.tags, clip.note,
            title="Favorit bearbeiten", parent=self,
        )
        if dialog.exec() == FavoriteDialog.DialogCode.Accepted:
            self.library.update_clip(clip.id, dialog.tags, dialog.note)
            self._refresh_clips()

    def delete_clip(self, clip: Clip) -> None:
        answer = QMessageBox.question(
            self, "Favorit löschen", f"Favorit {clip_range_text(clip.in_s, clip.out_s)} wirklich löschen?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.library.delete_clip(clip.id)
            self._refresh_clips()
            self.reload_library()

    def _on_escape(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self.player.clear_marks()

    # --- Vollbild --------------------------------------------------------

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
            return
        self._was_maximized = self.isMaximized()
        self.menuBar().hide()
        self.statusBar().hide()
        self.library_panel.hide()
        self.info_panel.hide()
        self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self.menuBar().show()
        self.statusBar().show()
        self.library_panel.show()
        self.info_panel.show()
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
        QThreadPool.globalInstance().waitForDone(5000)
        self.library.close()
        super().closeEvent(event)
