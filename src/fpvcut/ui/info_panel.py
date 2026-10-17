"""Seitenleiste zum aktuellen Video: Favoriten-Liste und Metadaten."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core.library import Clip, LibraryEntry
from fpvcut.ui.player import format_time

CLIP_ROLE = Qt.ItemDataRole.UserRole


def clip_range_text(clip_in: float, clip_out: float | None) -> str:
    if clip_in == 0 and clip_out is None:
        return "Ganzes Video"
    end = "Ende" if clip_out is None else format_time(clip_out)
    length = "" if clip_out is None else f"  ({clip_out - clip_in:.1f} s)"
    return f"{format_time(clip_in)} – {end}{length}"


class InfoPanel(QTabWidget):
    clip_activated = Signal(object)  # Clip
    clip_edit_requested = Signal(object)  # Clip
    clip_delete_requested = Signal(object)  # Clip
    add_to_timeline_requested = Signal(list)  # Favoriten-IDs

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        favorites = QWidget(self)
        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")
        self._clips = QListWidget(favorites)
        self._clips.setSpacing(2)
        self._clips.setAlternatingRowColors(True)
        self._clips.itemActivated.connect(lambda item: self.clip_activated.emit(item.data(CLIP_ROLE)))
        self._clips.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._clips.customContextMenuRequested.connect(self._show_clip_menu)
        delete = QShortcut(QKeySequence.StandardKey.Delete, self._clips)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._delete_current)
        fav_layout = QVBoxLayout(favorites)
        fav_layout.setContentsMargins(4, 4, 4, 4)
        fav_layout.addWidget(self._clips, 1)
        fav_layout.addWidget(self._hint)
        self.addTab(favorites, "Favoriten")

        meta = QWidget(self)
        self._meta_form = QFormLayout(meta)
        self._meta_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.addTab(meta, "Metadaten")

        self.set_entry(None, [])

    def set_entry(self, entry: LibraryEntry | None, clips: list[Clip]) -> None:
        self._clips.clear()
        for clip in clips:
            text = clip_range_text(clip.in_s, clip.out_s)
            if clip.tags:
                text += "\n" + "  ".join(f"#{t}" for t in clip.tags)
            if clip.note:
                text += f"\n{clip.note}"
            item = QListWidgetItem(text, self._clips)
            item.setData(CLIP_ROLE, clip)
        if entry is None:
            self._hint.setText("Öffne ein Video aus der Bibliothek, um Favoriten zu speichern.")
        else:
            self._hint.setText(
                "I = In-Punkt · O = Out-Punkt · F = Favorit speichern · Shift+F = ganzes Video · "
                "Esc = Auswahl aufheben. Doppelklick auf einen Favoriten spielt ihn in Schleife ab."
            )
        self._fill_metadata(entry)

    def _fill_metadata(self, entry: LibraryEntry | None) -> None:
        while self._meta_form.rowCount():
            self._meta_form.removeRow(0)
        if entry is None:
            self._meta_form.addRow(QLabel("Kein Video aus der Bibliothek geöffnet."))
            return
        day = entry.flight_day
        rows = [
            ("Datei", entry.path.name),
            ("Ordner", str(entry.path.parent)),
            ("Flugtag", day.label),
            ("Dauer", format_time(entry.duration) if entry.duration else "–"),
            ("Auflösung", f"{entry.width} × {entry.height}" if entry.width else "–"),
            ("Bildrate", f"{entry.fps:g} fps" if entry.fps else "–"),
            ("Video", f"{entry.vcodec or '–'}, {entry.bit_depth or '?'} Bit"),
            ("Audio", entry.acodec or "kein Ton"),
            ("Größe", f"{entry.size / 1_000_000:.1f} MB"),
            ("Bitrate", f"{entry.size * 8 / entry.duration / 1_000_000:.1f} Mbit/s" if entry.duration else "–"),
            ("Erfasst", datetime.fromtimestamp(entry.first_seen).strftime("%d.%m.%Y %H:%M")),
            ("Fingerprint", entry.fingerprint[:16] + "…"),
        ]
        for label, value in rows:
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._meta_form.addRow(f"{label}:", value_label)

    def current_clip(self) -> Clip | None:
        return self._current_clip()

    def _current_clip(self) -> Clip | None:
        item = self._clips.currentItem()
        return item.data(CLIP_ROLE) if item else None

    def _delete_current(self) -> None:
        if (clip := self._current_clip()) is not None:
            self.clip_delete_requested.emit(clip)

    def _show_clip_menu(self, pos: QPoint) -> None:
        item = self._clips.itemAt(pos)
        if item is None:
            return
        clip = item.data(CLIP_ROLE)
        menu = QMenu(self)
        menu.addAction("Abspielen (Schleife)", lambda: self.clip_activated.emit(clip))
        menu.addAction("Zur Timeline hinzufügen (E)", lambda: self.add_to_timeline_requested.emit([clip.id]))
        menu.addAction("Tags und Notiz bearbeiten …", lambda: self.clip_edit_requested.emit(clip))
        menu.addSeparator()
        menu.addAction("Favorit löschen", lambda: self.clip_delete_requested.emit(clip))
        menu.exec(self._clips.viewport().mapToGlobal(pos))
