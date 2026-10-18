"""Bibliotheksansicht: Videos gruppiert nach Flugtag, neue Videos hervorgehoben."""

from __future__ import annotations

import json
from collections import defaultdict
from functools import cache

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core.folder_names import FlightDay
from fpvcut.core.library import LibraryEntry
from fpvcut.ui.player import format_time
from fpvcut.ui.mime import MIME_MEDIA

NEW_COLOR = QColor("#3daee9")
STAR_COLOR = QColor("#ffc400")  # wie die Favoriten-Balken unter der Zeitleiste
CLIP_COLOR = QColor("#9a9a9a")
STAR_ICON_SIZE = QSize(52, 16)


@cache
def star_icon(favorites: int, others: int = 0) -> QIcon:
    """Goldenes "★n" für Favoriten und graues "✂n" für die übrigen Ausschnitte links vom Namen.

    Ohne Ausschnitte ein leeres Icon, damit die Namen fluchten.
    """
    pixmap = QPixmap(STAR_ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    if favorites or others:
        painter = QPainter(pixmap)
        font = QFont()
        font.setBold(True)
        painter.setFont(font)
        rect = pixmap.rect()
        for count, symbol, color in ((favorites, "★", STAR_COLOR), (others, "✂", CLIP_COLOR)):
            if not count:
                continue
            text = f"{symbol}{count}"
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            rect.setLeft(rect.left() + painter.fontMetrics().horizontalAdvance(text) + 3)
        painter.end()
    return QIcon(pixmap)


def clip_count_text(entry: LibraryEntry) -> str:
    """Anzahl der Ausschnitte für Vorlesetext und Tooltip, z. B. "3 Ausschnitte, davon 1 Favorit"."""
    if not entry.clip_count:
        return ""
    text = f"{entry.clip_count} Ausschnitt" + ("e" if entry.clip_count != 1 else "")
    if entry.favorite_count:
        text += f", davon {entry.favorite_count} Favorit" + ("en" if entry.favorite_count != 1 else "")
    return text
ENTRY_ROLE = Qt.ItemDataRole.UserRole


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    return format_time(seconds).split(".")[0]


def format_video(entry: LibraryEntry) -> str:
    if not entry.width:
        return "–"
    fps = f"{entry.fps:g}" if entry.fps else "?"
    return f"{entry.height}p{fps}"


def entry_tooltip(entry: LibraryEntry) -> str:
    lines = [str(entry.path)]
    if entry.missing:
        lines.append("Datei fehlt (Ordner verschoben, gelöscht oder Laufwerk nicht angeschlossen)")
    if entry.width:
        lines.append(f"{entry.width}×{entry.height} · {entry.fps:g} fps · {entry.vcodec} {entry.bit_depth or ''} Bit")
    if entry.acodec:
        lines.append(f"Audio: {entry.acodec}")
    lines.append(f"{entry.size / 1_000_000:.1f} MB · Dauer {format_duration(entry.duration)}")
    if entry.clip_count:
        lines.append(clip_count_text(entry))
    return "\n".join(lines)


def group_sort_key(day: FlightDay) -> tuple:
    # Datierte Flugtage zuerst, neueste oben; danach alles ohne Datum alphabetisch.
    return (0, -day.date.toordinal(), day.spot.lower()) if day.date else (1, 0, day.folder_name.lower())


class _LibraryTree(QTreeWidget):
    """Videos (oder ganze Flugtage) lassen sich in die Timeline ziehen."""

    def mimeTypes(self) -> list[str]:  # noqa: N802  (Qt-Name)
        return [MIME_MEDIA]

    def mimeData(self, items) -> QMimeData:  # noqa: N802
        data = QMimeData()
        data.setData(MIME_MEDIA, json.dumps([e.media_id for e in entries_of(items) if not e.missing]).encode())
        return data


def entries_of(items) -> list[LibraryEntry]:
    """Videos der Zeilen; eine Flugtag-Zeile steht für alle ihre Videos. Fehlende Dateien fallen weg."""
    seen: dict[int, LibraryEntry] = {}
    for item in items:
        children = [item.child(i) for i in range(item.childCount())] or [item]
        for child in children:
            entry = child.data(0, ENTRY_ROLE)
            if entry is not None:
                seen.setdefault(entry.media_id, entry)
    return list(seen.values())


class LibraryPanel(QWidget):
    video_activated = Signal(object)  # LibraryEntry
    review_toggled = Signal(list, bool)  # media_ids, gesichtet
    add_to_timeline_requested = Signal(list)  # media_ids

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[LibraryEntry] = []

        self._only_new = QCheckBox("Nur neue", self)
        self._only_new.toggled.connect(lambda _checked: self._rebuild())
        self._summary = QLabel(self)
        header = QHBoxLayout()
        header.addWidget(self._only_new)
        header.addStretch(1)
        header.addWidget(self._summary)

        self._tree = _LibraryTree(self)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._tree.setHeaderLabels(["Video", "Dauer", "Format"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setStretchLastSection(False)
        # Dauer und Format nur so breit wie nötig, damit der Name möglichst viel Platz bekommt.
        for column in (1, 2):
            self._tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setUniformRowHeights(True)
        self._tree.setIconSize(STAR_ICON_SIZE)
        # Strg/Shift+Klick wählt mehrere Videos; ein Flugtag steht für alle seine Videos.
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Ein einfacher Klick öffnet das Video, Enter ebenso; Strg/Shift+Klick bleibt Mehrfachauswahl.
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemActivated.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)

        self._placeholder = QLabel(
            "Noch kein Bibliotheksordner.\nDatei → Bibliotheksordner hinzufügen …", self
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(header)
        layout.addWidget(self._tree, 1)
        layout.addWidget(self._placeholder, 1)
        self._update_placeholder()

    # --- Daten -----------------------------------------------------------

    def set_entries(self, entries: list[LibraryEntry]) -> None:
        self._entries = entries
        self._rebuild()

    def _rebuild(self) -> None:
        expanded, current, selected = self._view_state()
        first_load = self._tree.topLevelItemCount() == 0
        self._tree.clear()

        groups: dict[FlightDay, list[LibraryEntry]] = defaultdict(list)
        for entry in self._entries:
            if not self._only_new.isChecked() or entry.is_new:
                groups[entry.flight_day].append(entry)

        bold = QFont()
        bold.setBold(True)
        current_item = None
        selected_items = []
        for index, day in enumerate(sorted(groups, key=group_sort_key)):
            entries = groups[day]
            new_count = sum(e.is_new for e in entries)
            group = QTreeWidgetItem([day.label, format_duration(sum(e.duration or 0 for e in entries)), ""])
            group.setFont(0, bold)
            group.setToolTip(0, day.folder_name)
            if new_count:
                group.setText(2, f"{new_count} neu")
                group.setForeground(2, QBrush(NEW_COLOR))
            for entry in entries:
                item = self._make_item(entry, bold)
                group.addChild(item)
                if entry.media_id == current:
                    current_item = item
                if entry.media_id in selected:
                    selected_items.append(item)
            self._tree.addTopLevelItem(group)
            if day.folder_name in expanded or new_count or (first_load and index == 0):
                group.setExpanded(True)

        if current_item is not None:
            self._tree.setCurrentItem(current_item)
        for item in selected_items:
            item.setSelected(True)
        self._update_summary()
        self._update_placeholder()

    def _make_item(self, entry: LibraryEntry, bold: QFont) -> QTreeWidgetItem:
        name = entry.path.name
        item = QTreeWidgetItem([name, format_duration(entry.duration), format_video(entry)])
        item.setIcon(0, star_icon(entry.favorite_count, entry.clip_count - entry.favorite_count))
        if entry.clip_count:
            item.setData(0, Qt.ItemDataRole.AccessibleTextRole, f"{name}, {clip_count_text(entry)}")
        item.setData(0, ENTRY_ROLE, entry)
        item.setToolTip(0, entry_tooltip(entry))
        if entry.missing:
            item.setText(0, f"{name} (fehlt)")
            for col in range(3):
                item.setForeground(col, QBrush(QColor("gray")))
        elif entry.is_new:
            item.setText(0, f"● {name}")
            item.setFont(0, bold)
            item.setForeground(0, QBrush(NEW_COLOR))
        return item

    def _view_state(self) -> tuple[set[str], int | None, set[int]]:
        expanded = set()
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            if group.isExpanded():
                expanded.add(group.toolTip(0))
        current = self._tree.currentItem()
        entry = current.data(0, ENTRY_ROLE) if current else None
        selected = {e.media_id for e in self.selected_entries()}
        return expanded, entry.media_id if entry else None, selected

    def selected_entries(self) -> list[LibraryEntry]:
        """Ausgewählte Videos; ein ausgewählter Flugtag zählt mit all seinen Videos."""
        return entries_of(self._tree.selectedItems())

    def _update_summary(self) -> None:
        new = sum(e.is_new for e in self._entries)
        days = len({e.flight_day for e in self._entries})
        text = f"{len(self._entries)} Videos · {days} Flugtage"
        self._summary.setText(f"{text} · <b style='color:{NEW_COLOR.name()}'>{new} neu</b>" if new else text)

    def _update_placeholder(self) -> None:
        empty = not self._entries
        self._tree.setVisible(not empty)
        self._placeholder.setVisible(empty)

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder.setText(text)

    # --- Interaktion -----------------------------------------------------

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if QGuiApplication.keyboardModifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            return
        self._on_item_activated(item, column)

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        entry = item.data(0, ENTRY_ROLE)
        if entry is not None and not entry.missing:
            self.video_activated.emit(entry)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self._tree.setCurrentItem(item)  # Rechtsklick außerhalb der Auswahl wählt nur diese Zeile
        entries = self.selected_entries()
        if not entries:
            return
        new = [e.media_id for e in entries if e.is_new]
        seen = [e.media_id for e in entries if not e.is_new]

        def plural(ids: list[int]) -> str:
            return "Video" if len(ids) == 1 else f"{len(ids)} Videos"

        menu = QMenu(self)
        if new:
            menu.addAction(f"{plural(new)} als gesichtet markieren", lambda: self.review_toggled.emit(new, True))
        if seen:
            menu.addAction(f"{plural(seen)} als neu markieren", lambda: self.review_toggled.emit(seen, False))
        available = [e for e in entries if not e.missing]
        if available:
            ids = [e.media_id for e in available]
            menu.addSeparator()
            menu.addAction(
                f"{plural(ids)} zur Timeline hinzufügen (E)", lambda: self.add_to_timeline_requested.emit(ids)
            )
        if len({e.path.parent for e in available}) == 1:
            folder = available[0].path.parent
            menu.addSeparator()
            menu.addAction(
                "Ordner im Explorer öffnen", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            )
        menu.exec(self._tree.viewport().mapToGlobal(pos))

