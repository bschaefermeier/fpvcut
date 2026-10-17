"""Hauptfenster: Bibliothek, Player, Tastenkürzel und Systemcheck."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QObject,
    QPropertyAnimation,
    QRunnable,
    QSequentialAnimationGroup,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget

from fpvcut import __version__
from fpvcut.core import backup
from fpvcut.core.ffmpeg_tools import EncoderReport, FFmpegNotFound, check_encoders, find_tool
from fpvcut.core.fingerprint import fingerprint
from fpvcut.core.library import Clip, Library, LibraryEntry
from fpvcut.core.marks import resolve_range
from fpvcut.core.probe import probe
from fpvcut.core.scanner import ScanResult, scan_library
from fpvcut.render.command import SourceFormat, source_format
from fpvcut.timeline.edl import build_edl, build_lavfi
from fpvcut.timeline.model import MusicTrack, Timeline, TimelineClip
from fpvcut.ui.favorite_dialog import FavoriteDialog
from fpvcut.ui.favorites_panel import FavoritesPanel
from fpvcut.ui.info_panel import InfoPanel, clip_range_text
from fpvcut.ui.library_panel import LibraryPanel
from fpvcut.ui.player import PlayerWidget
from fpvcut.ui.render_dialog import RenderDialog
from fpvcut.ui.rename_dialog import RenameDialog
from fpvcut.ui.timeline_panel import TimelinePanel

VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.MP4 *.MOV *.MKV *.AVI);;Alle Dateien (*)"
MUSIC_FILTER = "Musik (*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.opus);;Alle Dateien (*)"
TIMELINE_FILTER = "FPVCut-Timeline (*.fpvcut.json *.json)"


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
        self.timeline_mode = False  # Player zeigt gerade die Timeline-Vorschau
        self.timeline_path = self.db_path.with_name("timeline.json")
        self.backup_dir = self.db_path.with_name("sicherungen")

        self.player = PlayerWidget(self)
        self.player.double_clicked.connect(self.toggle_fullscreen)
        self.player.position_changed.connect(self._on_player_position)
        self.player.nothing_loaded.connect(self._on_nothing_loaded)
        self.library_panel = LibraryPanel(self)
        self.library_panel.video_activated.connect(self.open_entry)
        self.library_panel.review_toggled.connect(self._on_review_toggled)
        self.library_panel.add_to_timeline_requested.connect(self.add_videos_to_timeline)
        self.favorites_panel = FavoritesPanel(self)
        self.favorites_panel.clip_activated.connect(self.play_favorite)
        self.favorites_panel.clip_edit_requested.connect(self.edit_clip)
        self.favorites_panel.clip_delete_requested.connect(self.delete_clip)
        self.favorites_panel.add_to_timeline_requested.connect(self.add_favorites_to_timeline)
        self.side_tabs = QTabWidget(self)
        self.side_tabs.addTab(self.library_panel, "Bibliothek")
        self.side_tabs.addTab(self.favorites_panel, "Favoriten")
        self.info_panel = InfoPanel(self)
        self.info_panel.clip_activated.connect(self.play_clip)
        self.info_panel.clip_edit_requested.connect(self.edit_clip)
        self.info_panel.clip_delete_requested.connect(self.delete_clip)
        self.info_panel.add_to_timeline_requested.connect(self.add_favorites_to_timeline)
        self.timeline_panel = TimelinePanel(self)
        self.timeline_panel.preview_requested.connect(self.play_timeline)
        self.timeline_panel.seek_requested.connect(self._on_timeline_seek)
        self.timeline_panel.clips_dropped.connect(self.add_favorites_to_timeline)
        self.timeline_panel.media_dropped.connect(self.add_videos_to_timeline)
        self.timeline_panel.music_requested.connect(self.add_music_dialog)
        self.timeline_panel.render_requested.connect(self.render_dialog)
        self.timeline_panel.changed.connect(self._on_timeline_changed)
        # Vorschau erst neu laden, wenn sich nichts mehr tut (z. B. beim Ziehen eines Reglers).
        self._preview_reload = QTimer(self)
        self._preview_reload.setSingleShot(True)
        self._preview_reload.setInterval(350)
        self._preview_reload.timeout.connect(self._reload_preview)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self.side_tabs)
        self._splitter.addWidget(self.player)
        self._splitter.addWidget(self.info_panel)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([380, 760, 300])
        self._vsplitter = QSplitter(Qt.Orientation.Vertical, self)
        self._vsplitter.addWidget(self._splitter)
        self._vsplitter.addWidget(self.timeline_panel)
        self._vsplitter.setStretchFactor(0, 1)
        self._vsplitter.setCollapsible(0, False)
        self.setCentralWidget(self._vsplitter)

        self._ffmpeg_status = QLabel("ffmpeg: wird geprüft …")
        self.statusBar().addPermanentWidget(self._ffmpeg_status)

        self._build_menu()
        self._start_encoder_check()
        self.reload_library()
        self._load_autosaved_timeline()
        self._backup_favorites()
        QTimer.singleShot(0, self._offer_restore)
        self.rescan_library()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datei")
        self._add_action(file_menu, "Video &öffnen …", "Ctrl+O", self.open_video_dialog)
        file_menu.addSeparator()
        self._add_action(file_menu, "Bibliotheksordner &hinzufügen …", "Ctrl+Shift+O", self.add_root_dialog)
        self._add_action(file_menu, "Bibliothek neu &scannen", "F5", self.rescan_library)
        self._add_action(file_menu, "Ordner ins Schema &umbenennen …", None, self.rename_dialog)
        file_menu.addSeparator()
        self._add_action(file_menu, "Favoriten &exportieren …", None, self.export_favorites_dialog)
        self._add_action(file_menu, "Favoriten &importieren …", None, self.import_favorites_dialog)
        file_menu.addSeparator()
        quit_action = self._add_action(file_menu, "&Beenden", "Ctrl+Q", self.close)
        # Alt+F4 erledigt sonst Windows, kommt aber nicht an, wenn der eingebettete Player den Fokus hat.
        quit_action.setShortcuts([QKeySequence("Ctrl+Q"), QKeySequence("Alt+F4")])

        play_menu = self.menuBar().addMenu("&Wiedergabe")
        self._add_action(play_menu, "Abspielen/Pause", "Space", self.player.toggle_pause)
        self._add_action(play_menu, "Frame vor", "Right", lambda: self.player.step_frame(True))
        self._add_action(play_menu, "Frame zurück", "Left", lambda: self.player.step_frame(False))
        self._add_action(play_menu, "1 s vor", "Shift+Right", lambda: self.player.seek_relative(1))
        self._add_action(play_menu, "1 s zurück", "Shift+Left", lambda: self.player.seek_relative(-1))
        self._add_action(play_menu, "5 s vor", "L", lambda: self.player.seek_relative(5))
        self._add_action(play_menu, "5 s zurück", "J", lambda: self.player.seek_relative(-5))
        self._add_action(play_menu, "Zum Anfang der Timeline", "Ctrl+Left", lambda: self.jump_in_timeline(False))
        self._add_action(play_menu, "Zum Ende der Timeline", "Ctrl+Right", lambda: self.jump_in_timeline(True))

        play_menu.addSeparator()
        self._add_action(play_menu, "Vollbild", "F11", self.toggle_fullscreen)
        self._add_action(play_menu, "Vollbild beenden / Auswahl aufheben", "Esc", self._on_escape)

        fav_menu = self.menuBar().addMenu("F&avoriten")
        self._add_action(fav_menu, "In-Punkt setzen", "I", self.player.set_in)
        self._add_action(fav_menu, "Out-Punkt setzen", "O", self.player.set_out)
        self._add_action(fav_menu, "Ausschnitt als Favorit speichern …", "F", self.save_favorite)
        self._add_action(fav_menu, "Ganzes Video als Favorit speichern …", "Shift+F", self.save_whole_video)

        tl_menu = self.menuBar().addMenu("&Timeline")
        self._add_action(tl_menu, "Zur Timeline hinzufügen", "E", self.add_selection_to_timeline)
        self._add_action(tl_menu, "Timeline abspielen", "P", lambda: self.play_timeline(None))
        self._add_action(tl_menu, "Clip am Abspielkopf teilen", "S", self.split_timeline)
        self._add_action(tl_menu, "Rendern …", "Ctrl+R", self.render_dialog)
        self._add_action(tl_menu, "Ausgewählten Clip entfernen", None, self.timeline_panel.delete_selected)
        tl_menu.addSeparator()
        self._add_action(tl_menu, "Rückgängig", "Ctrl+Z", self.timeline_panel.undo)
        self._add_action(tl_menu, "Wiederholen", "Ctrl+Y", self.timeline_panel.redo)
        tl_menu.addSeparator()
        self._add_action(tl_menu, "Musik hinzufügen …", None, self.add_music_dialog)
        self._add_action(tl_menu, "Musik entfernen", None, lambda: self.timeline_panel.set_music(None))
        tl_menu.addSeparator()
        self._add_action(tl_menu, "Neue Timeline", None, self.new_timeline)
        self._add_action(tl_menu, "Timeline öffnen …", None, self.open_timeline_dialog)
        self._add_action(tl_menu, "Timeline speichern unter …", None, self.save_timeline_dialog)

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

    def open_video(
        self, path: Path, entry: LibraryEntry | None = None, start: float | None = None, end: float | None = None
    ) -> None:
        if entry is None:
            entry = self._entry_for_file(path)
        self.timeline_mode = False
        self.player.open(path, start, end)
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
        self.favorites_panel.set_data(self.library.all_clips(), self.library.tag_counts())

    # --- Sicherung ---------------------------------------------------------

    def _backup_favorites(self) -> None:
        """Tagessicherung der Favoriten neben der Datenbank (beim Start und beim Beenden)."""
        try:
            backup.daily_backup(self.library, self.backup_dir)
        except OSError as exc:
            self.statusBar().showMessage(f"Favoriten-Sicherung fehlgeschlagen: {exc}")

    def _offer_restore(self) -> None:
        """Leere Bibliothek, aber eine Sicherung da (z. B. nach Neuinstallation): Wiederherstellen anbieten."""
        if self.library.conn.execute("SELECT 1 FROM clip LIMIT 1").fetchone():
            return
        latest = backup.latest_backup(self.backup_dir)
        if latest is None:
            return
        answer = QMessageBox.question(
            self, "Favoriten wiederherstellen",
            f"Die Bibliothek enthält keine Favoriten, es gibt aber eine Sicherung ({latest.name}).\n\n"
            "Favoriten, Tags und Gesichtet-Status daraus übernehmen?")
        if answer == QMessageBox.StandardButton.Yes:
            self.import_favorites(latest)

    def import_favorites(self, path: Path) -> backup.ImportResult | None:
        try:
            result = backup.import_from(self.library, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Import fehlgeschlagen", f"{path.name}: {exc}")
            return None
        self.reload_library()
        if self.current_entry is not None:
            self._refresh_clips()
        text = f"{result.clips_added} Favoriten übernommen"
        if result.clips_skipped:
            text += f", {result.clips_skipped} waren schon da"
        if result.media_added:
            text += f"; {result.media_added} Videos erscheinen nach dem nächsten Scan"
        self.statusBar().showMessage(text)
        return result

    def export_favorites_dialog(self) -> None:
        default = str(Path.home() / f"fpvcut_favoriten_{datetime.now():%Y-%m-%d}.json")
        path, _ = QFileDialog.getSaveFileName(self, "Favoriten exportieren", default, "FPVCut-Sicherung (*.json)")
        if path:
            try:
                count = backup.export_to(self.library, Path(path))
            except OSError as exc:
                QMessageBox.warning(self, "Export fehlgeschlagen", str(exc))
                return
            self.statusBar().showMessage(f"{count} Favoriten exportiert nach {path}")

    def import_favorites_dialog(self) -> None:
        start = str(self.backup_dir if self.backup_dir.is_dir() else Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Favoriten importieren", start, "FPVCut-Sicherung (*.json)")
        if path:
            self.import_favorites(Path(path))

    def rename_dialog(self) -> RenameDialog | None:
        if self._scanning:
            self.statusBar().showMessage("Bitte warten, bis der Scan fertig ist.")
            return None
        dialog = RenameDialog(self.library, self.db_path.parent / "umbenannt", self._close_media, self)
        dialog.finished.connect(lambda _code: self._after_rename(dialog))
        dialog.open()
        return dialog

    def _close_media(self) -> None:
        """Vor dem Umbenennen: geöffnetes Video schließen, sonst sperrt Windows den Ordner."""
        self.player.stop()
        self.current_entry = None
        self.timeline_mode = False
        self._refresh_clips()

    def _after_rename(self, dialog: RenameDialog) -> None:
        if dialog.changed:
            self.reload_library()
            self.timeline_panel.set_timeline(self.resolve_timeline(self.timeline_panel.timeline))

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

    def open_entry(self, entry: LibraryEntry, start: float | None = None, end: float | None = None) -> None:
        self.open_video(entry.path, entry, start, end)
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

    def play_favorite(self, clip: Clip, entry: LibraryEntry) -> None:
        """Favorit aus dem Browser: Video öffnen (falls nötig) und Ausschnitt in Schleife abspielen."""
        if self.current_entry is not None and self.current_entry.media_id == entry.media_id:
            self.play_clip(clip)
        else:
            self.open_entry(entry, clip.in_s, clip.out_s)

    def edit_clip(self, clip: Clip) -> None:
        dialog = FavoriteDialog(
            clip_range_text(clip.in_s, clip.out_s), self.library.all_tags(), clip.tags, clip.note,
            title="Favorit bearbeiten", parent=self,
        )
        if dialog.exec() == FavoriteDialog.DialogCode.Accepted:
            self.library.update_clip(clip.id, dialog.tags, dialog.note)
            self._refresh_clips()
            self.reload_library()

    def delete_clip(self, clip: Clip) -> None:
        answer = QMessageBox.question(
            self, "Favorit löschen", f"Favorit {clip_range_text(clip.in_s, clip.out_s)} wirklich löschen?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.library.delete_clip(clip.id)
            self._refresh_clips()
            self.reload_library()

    # --- Timeline --------------------------------------------------------

    def _timeline_clip(self, clip: Clip | None, entry: LibraryEntry) -> TimelineClip | None:
        """Timeline-Clip aus einem Favoriten oder, ohne ``clip``, aus dem ganzen Video."""
        start = clip.in_s if clip else 0.0
        end = clip.out_s if clip and clip.out_s is not None else entry.duration
        if end is None or end <= start:
            return None
        return TimelineClip(
            entry.fingerprint, start, end, entry.duration, entry.path.name,
            has_audio=bool(entry.acodec),
            fav_in=start if clip else None, fav_out=end if clip else None,
            path=None if entry.missing else entry.path,
        )

    def add_videos_to_timeline(self, media_ids: list[int], index: int | None = None) -> None:
        entries = {e.media_id: e for e in self.library.entries()}
        clips = [self._timeline_clip(None, entries[i]) for i in media_ids if i in entries]
        self._add_to_timeline([c for c in clips if c is not None], index, bool(media_ids))

    def add_favorites_to_timeline(self, clip_ids: list[int], index: int | None = None) -> None:
        by_id = {clip.id: (clip, entry) for clip, entry in self.library.all_clips()}
        clips = [self._timeline_clip(*by_id[i]) for i in clip_ids if i in by_id]
        self._add_to_timeline([c for c in clips if c is not None], index, bool(clip_ids))

    def _add_to_timeline(self, clips: list[TimelineClip], index: int | None, requested: bool) -> None:
        self.timeline_panel.add_clips(clips, index)
        if clips:
            self.statusBar().showMessage(f"{len(clips)} Clip(s) zur Timeline hinzugefügt")
        elif requested:
            self.statusBar().showMessage("Länge des Videos unbekannt, nichts hinzugefügt.")

    def add_selection_to_timeline(self) -> None:
        """E: markierten Ausschnitt im Player, sonst die Auswahl im linken Reiter in die Timeline."""
        if self.current_entry is not None and self.player.has_marks():
            in_ms, out_ms = resolve_range(self.player.in_point, self.player.out_point, self.player.position())
            clip = Clip(0, self.current_entry.media_id, in_ms, out_ms, "", 0.0)
            if (item := self._timeline_clip(clip, self.current_entry)) is not None:
                self.timeline_panel.add_clips([item])
                self.player.clear_marks()
                self.statusBar().showMessage("Ausschnitt zur Timeline hinzugefügt")
            return
        tab = self.side_tabs.currentWidget()
        if tab is self.favorites_panel and (ids := self.favorites_panel.selected_clip_ids()):
            self.add_favorites_to_timeline(ids)
        elif tab is self.library_panel and (entries := self.library_panel.selected_entries()):
            self.add_videos_to_timeline([e.media_id for e in entries if not e.missing])
        elif (clip := self.info_panel.current_clip()) is not None:
            self.add_favorites_to_timeline([clip.id])
        else:
            self.statusBar().showMessage("Erst Videos oder Favoriten auswählen oder im Player mit I/O markieren.")

    def resolve_timeline(self, timeline: Timeline) -> Timeline:
        """Pfade der Clips über den Fingerprint in der Bibliothek suchen."""
        for clip in timeline.clips:
            media_id = self.library.media_id_for(clip.fingerprint)
            entry = self.library.entry_for_media(media_id) if media_id else None
            clip.path = entry.path if entry is not None and not entry.missing else None
            if entry is not None:
                clip.label = entry.path.name
                clip.has_audio = bool(entry.acodec)
        return timeline

    def _load_autosaved_timeline(self) -> None:
        if self.timeline_path.exists():
            try:
                self.timeline_panel.set_timeline(self.resolve_timeline(Timeline.load(self.timeline_path)))
            except (OSError, ValueError, TypeError) as exc:
                self.statusBar().showMessage(f"Gespeicherte Timeline konnte nicht geladen werden: {exc}")

    def _save_timeline(self) -> None:
        try:
            self.timeline_panel.timeline.save(self.timeline_path)
        except OSError as exc:
            self.statusBar().showMessage(f"Timeline konnte nicht gespeichert werden: {exc}")

    def _on_timeline_changed(self) -> None:
        self._save_timeline()
        if self.timeline_mode:
            self._preview_reload.start()

    def play_timeline(self, start: float | None = None, paused: bool = False) -> None:
        timeline = self.timeline_panel.timeline
        if not timeline.clips:
            self.statusBar().showMessage("Die Timeline ist leer.")
            return
        if missing := timeline.missing_clips():
            names = ", ".join(sorted({c.label for c in missing}))
            self.statusBar().showMessage(f"Vorschau nicht möglich, Dateien fehlen: {names}")
            return
        if start is None:
            start = self.timeline_panel.view.playhead
        if start >= timeline.duration - 0.05:
            start = 0.0
        self.timeline_mode = True
        self.current_entry = None
        self._refresh_clips()
        self.player.open_timeline(build_edl(timeline), build_lavfi(timeline, start), start, paused)
        self.player.seek_handler = self._seek_timeline
        self.timeline_panel.set_playhead(start)
        self.statusBar().showMessage("Timeline-Vorschau")

    def _reload_preview(self) -> None:
        if self.timeline_mode:
            if self.timeline_panel.timeline.clips:
                self.play_timeline(self.timeline_panel.view.playhead, self.player.paused)
            else:
                self.timeline_mode = False
                self.player.stop()

    def _on_player_position(self, t: float) -> None:
        if self.timeline_mode:
            self.timeline_panel.set_playhead(t)

    def _seek_timeline(self, t: float) -> None:
        """Sprung in der Vorschau: ab ``t`` neu laden, damit Musik und Originalton synchron bleiben."""
        end = self.timeline_panel.timeline.duration
        self.play_timeline(min(max(t, 0.0), max(end - 0.1, 0.0)), self.player.paused)

    def _on_timeline_seek(self, t: float) -> None:
        if self.timeline_mode:
            self._seek_timeline(t)
        else:
            self.play_timeline(t, paused=True)  # Klick in die Timeline zeigt das Bild an dieser Stelle

    def jump_in_timeline(self, to_end: bool) -> None:
        """Strg+Pfeil: Abspielkopf an Anfang oder Ende der Timeline (zeigt dort das Bild)."""
        end = self.timeline_panel.timeline.duration
        if end <= 0:
            return
        # Kurz vor dem Ende, damit noch ein Bild zu sehen ist.
        self._on_timeline_seek(max(end - 0.1, 0.0) if to_end else 0.0)

    def _on_nothing_loaded(self) -> None:
        """Play/Leertaste ohne geöffnetes Video: dann die Timeline abspielen."""
        if self.timeline_panel.timeline.clips:
            self.play_timeline()

    def split_timeline(self) -> None:
        if not self.timeline_panel.split_at_playhead():
            self.statusBar().showMessage("Zum Teilen den roten Abspielkopf mitten in einen Clip setzen.")

    def render_formats(self, timeline: Timeline) -> list[SourceFormat | None]:
        formats = []
        for clip in timeline.clips:
            media_id = self.library.media_id_for(clip.fingerprint)
            entry = self.library.entry_for_media(media_id) if media_id else None
            ok = entry is not None and entry.width and entry.height and entry.fps
            formats.append(SourceFormat(entry.width, entry.height, entry.fps) if ok else None)
        return formats

    def render_dialog(self) -> None:
        timeline = self.timeline_panel.timeline
        if not timeline.clips:
            self.statusBar().showMessage("Die Timeline ist leer.")
            return
        if missing := timeline.missing_clips():
            names = ", ".join(sorted({c.label for c in missing}))
            QMessageBox.warning(self, "Rendern", f"Diese Dateien fehlen gerade: {names}")
            return
        try:
            ffmpeg = self.encoder_report.ffmpeg if self.encoder_report else find_tool("ffmpeg")
        except FFmpegNotFound as exc:
            QMessageBox.warning(self, "Rendern", str(exc))
            return
        if not self.player.paused:
            self.player.toggle_pause()  # Vorschau anhalten, solange gerendert wird
        source = source_format(timeline, self.render_formats(timeline))
        dialog = RenderDialog(timeline, source, ffmpeg, self.encoder_report, parent=self)
        dialog.exec()
        self._save_timeline()  # gewähltes Profil merken

    def add_music_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Musik wählen", "", MUSIC_FILTER)
        if not path:
            return
        duration = None
        try:
            info = probe(find_tool("ffprobe"), Path(path))
            duration = info.duration if info else None
        except (FFmpegNotFound, OSError, ValueError):
            pass
        self.timeline_panel.set_music(MusicTrack(path, duration))

    def new_timeline(self) -> None:
        if self.timeline_panel.timeline.clips:
            answer = QMessageBox.question(self, "Neue Timeline", "Aktuelle Timeline verwerfen?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._replace_timeline(Timeline())

    def _replace_timeline(self, timeline: Timeline) -> None:
        self.timeline_panel.remember()
        self.timeline_panel.set_timeline(timeline, keep_history=True)
        self.timeline_panel.set_playhead(0)
        self._on_timeline_changed()

    def open_timeline_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Timeline öffnen", "", TIMELINE_FILTER)
        if not path:
            return
        try:
            timeline = self.resolve_timeline(Timeline.load(path))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Timeline öffnen", f"Datei konnte nicht gelesen werden:\n{exc}")
            return
        self._replace_timeline(timeline)

    def save_timeline_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Timeline speichern", "timeline.fpvcut.json", TIMELINE_FILTER)
        if path:
            try:
                self.timeline_panel.timeline.save(path)
            except OSError as exc:
                QMessageBox.warning(self, "Timeline speichern", str(exc))

    def _on_escape(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self.player.clear_marks()

    # --- Vollbild --------------------------------------------------------

    FADE_MS = 110  # kurzes Aus- und Einblenden beim Wechsel, wie bei anderen Playern

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self._fade_switch(self._enter_fullscreen)

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self._fade_switch(self._leave_fullscreen)

    def _set_chrome_visible(self, visible: bool) -> None:
        for widget in (self.menuBar(), self.statusBar(), self.side_tabs, self.info_panel, self.timeline_panel):
            widget.setVisible(visible)

    def _enter_fullscreen(self) -> None:
        self._state_before_fullscreen = self.windowState() & ~Qt.WindowState.WindowFullScreen
        self._set_chrome_visible(False)
        self.setWindowState(self._state_before_fullscreen | Qt.WindowState.WindowFullScreen)

    def _leave_fullscreen(self) -> None:
        self._set_chrome_visible(True)
        # Direkt in den vorherigen Zustand (z. B. maximiert) statt erst über "normal".
        self.setWindowState(getattr(self, "_state_before_fullscreen", Qt.WindowState.WindowNoState))

    def _fade_finished(self) -> None:
        self._fade = None
        self.setWindowOpacity(1.0)

    def _fade_switch(self, switch) -> None:
        """Fenster ausblenden, umschalten, wieder einblenden. Verdeckt das Zwischenbild beim Wechsel."""
        if self.FADE_MS <= 0 or QGuiApplication.platformName() in ("offscreen", "minimal"):
            switch()
            return
        if getattr(self, "_fade", None) is not None:
            return  # Wechsel läuft noch
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(self.FADE_MS)
        fade_out.setStartValue(self.windowOpacity())
        fade_out.setEndValue(0.0)
        fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        fade_in.setDuration(self.FADE_MS + 60)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        group = QSequentialAnimationGroup(self)
        group.addAnimation(fade_out)
        group.addPause(40)
        group.addAnimation(fade_in)
        # Umschalten in der Pause zwischen Aus- und Einblenden, solange das Fenster unsichtbar ist.
        group.currentAnimationChanged.connect(lambda anim: switch() if anim not in (fade_out, fade_in) else None)
        group.finished.connect(self._fade_finished)
        self._fade = group
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

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
        self._save_timeline()
        self._backup_favorites()
        self.player.shutdown()
        QThreadPool.globalInstance().waitForDone(5000)
        self.library.close()
        super().closeEvent(event)
