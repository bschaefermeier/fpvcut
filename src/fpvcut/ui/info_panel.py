"""Seitenleiste zum aktuellen Video: Ausschnitte und Metadaten."""

from __future__ import annotations

import json

from PySide6.QtCore import QDateTime, QLocale, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from fpvcut.i18n import translate
from fpvcut.ui.mime import MIME_CLIPS
from fpvcut.ui.player import format_time
from fpvcut.ui.stars import star_icon

CLIP_ROLE = Qt.ItemDataRole.UserRole


def clip_range_text(clip_in: float, clip_out: float | None) -> str:
    if clip_in == 0 and clip_out is None:
        return translate("InfoPanel", "Whole video")
    end = translate("InfoPanel", "End") if clip_out is None else format_time(clip_out)
    length = "" if clip_out is None else f"  ({clip_out - clip_in:.1f} s)"
    return f"{format_time(clip_in)} – {end}{length}"


class _ClipList(QListWidget):
    """Ausgewählte Ausschnitte lassen sich in die Timeline ziehen, in der Reihenfolge der Liste."""

    def mimeTypes(self) -> list[str]:  # noqa: N802  (Qt-Name)
        return [MIME_CLIPS]

    def mimeData(self, items) -> QMimeData:  # noqa: N802
        ids = [item.data(CLIP_ROLE).id for item in sorted(items, key=self.row)]
        data = QMimeData()
        data.setData(MIME_CLIPS, json.dumps(ids).encode())
        return data


class InfoPanel(QTabWidget):
    clip_activated = Signal(object)  # Clip
    clip_edit_requested = Signal(object)  # Clip
    clip_delete_requested = Signal(object)  # Clip
    add_to_timeline_requested = Signal(list)  # Ausschnitt-IDs
    favorite_toggled = Signal(object, bool)  # Clip, soll Favorit sein

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        favorites = QWidget(self)
        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray;")
        self._clips = _ClipList(favorites)
        self._clips.setSpacing(2)
        self._clips.setAlternatingRowColors(True)
        self._clips.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._clips.setDragEnabled(True)
        self._clips.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
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
        self.addTab(favorites, self.tr("Clips"))

        meta = QWidget(self)
        self._meta_form = QFormLayout(meta)
        self._meta_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.addTab(meta, self.tr("Metadata"))

        self.set_entry(None, [])

    def set_entry(self, entry: LibraryEntry | None, clips: list[Clip]) -> None:
        self._clips.clear()
        for clip in clips:
            text = clip_range_text(clip.in_s, clip.out_s)
            if clip.tags:
                text += "\n" + "  ".join(f"#{t}" for t in clip.tags)
            if clip.note:
                text += f"\n{clip.note}"
            item = QListWidgetItem(star_icon(clip.favorite), text, self._clips)
            item.setData(CLIP_ROLE, clip)
            if clip.favorite:
                item.setToolTip(self.tr("Favorite"))
        if entry is None:
            self._hint.setText(self.tr("Open a video from the library to save clips."))
        else:
            self._hint.setText(
                self.tr("I = in point · O = out point · F = save clip · Shift+F = whole video · "
                        "Esc = clear selection. Double-click a clip to play it in a loop, "
                        "drag it into the timeline (several with Ctrl/Shift), "
                        "right-click to mark it as a favorite.")
            )
        self._fill_metadata(entry)

    def _fill_metadata(self, entry: LibraryEntry | None) -> None:
        while self._meta_form.rowCount():
            self._meta_form.removeRow(0)
        if entry is None:
            self._meta_form.addRow(QLabel(self.tr("No video from the library open.")))
            return
        day = entry.flight_day
        rows = [
            (self.tr("File"), entry.path.name),
            (self.tr("Folder"), str(entry.path.parent)),
            (self.tr("Flight day"), day.label),
            (self.tr("Duration"), format_time(entry.duration) if entry.duration else "–"),
            (self.tr("Resolution"), f"{entry.width} × {entry.height}" if entry.width else "–"),
            (self.tr("Frame rate"), f"{entry.fps:g} fps" if entry.fps else "–"),
            (self.tr("Video"), self.tr("{codec}, {bits} bit").format(codec=entry.vcodec or "–", bits=entry.bit_depth or "?")),
            (self.tr("Audio"), entry.acodec or self.tr("no sound")),
            (self.tr("Size"), f"{entry.size / 1_000_000:.1f} MB"),
            (self.tr("Bit rate"), f"{entry.size * 8 / entry.duration / 1_000_000:.1f} Mbit/s" if entry.duration else "–"),
            (self.tr("Added"), QLocale().toString(QDateTime.fromSecsSinceEpoch(int(entry.first_seen)),
                                                  QLocale.FormatType.ShortFormat)),
            (self.tr("Fingerprint"), entry.fingerprint[:16] + "…"),
        ]
        for label, value in rows:
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._meta_form.addRow(self.tr("{label}:").format(label=label), value_label)

    def current_clip(self) -> Clip | None:
        return self._current_clip()

    def selected_clips(self) -> list[Clip]:
        """Ausgewählte Ausschnitte in der Reihenfolge der Liste."""
        items = sorted(self._clips.selectedItems(), key=self._clips.row)
        return [item.data(CLIP_ROLE) for item in items]

    def _current_clip(self) -> Clip | None:
        item = self._clips.currentItem()
        return item.data(CLIP_ROLE) if item else None

    def _delete_current(self) -> None:
        if (clip := self._current_clip()) is not None:
            self.clip_delete_requested.emit(clip)

    def _show_clip_menu(self, pos: QPoint) -> None:
        item = self._clips.itemAt(pos)
        if item is not None:
            self.clip_menu(item).exec(self._clips.viewport().mapToGlobal(pos))

    def clip_menu(self, item: QListWidgetItem) -> QMenu:
        clip = item.data(CLIP_ROLE)
        # Rechtsklick in eine Mehrfachauswahl: „In die Timeline“ nimmt alle ausgewählten.
        chosen = self.selected_clips() if item.isSelected() else [clip]
        menu = QMenu(self)
        menu.addAction(self.tr("Play (loop)"), lambda: self.clip_activated.emit(clip))
        menu.addAction(self.tr("Add %n clip(s) to timeline (E)", "", len(chosen)),
                       lambda: self.add_to_timeline_requested.emit([c.id for c in chosen]))
        menu.addAction(self.tr("Remove favorite") if clip.favorite else self.tr("Mark as favorite"),
                       lambda: self.favorite_toggled.emit(clip, not clip.favorite))
        menu.addAction(self.tr("Edit tags and note …"), lambda: self.clip_edit_requested.emit(clip))
        menu.addSeparator()
        menu.addAction(self.tr("Delete clip"), lambda: self.clip_delete_requested.emit(clip))
        return menu
