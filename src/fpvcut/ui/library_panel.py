"""Bibliotheksansicht: Videos gruppiert nach Flugtag, neue Videos hervorgehoben."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
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

NEW_COLOR = QColor("#3daee9")
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
    return "\n".join(lines)


def group_sort_key(day: FlightDay) -> tuple:
    # Datierte Flugtage zuerst, neueste oben; danach alles ohne Datum alphabetisch.
    return (0, -day.date.toordinal(), day.spot.lower()) if day.date else (1, 0, day.folder_name.lower())


class LibraryPanel(QWidget):
    video_activated = Signal(object)  # LibraryEntry
    review_toggled = Signal(int, bool)  # media_id, gesichtet

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

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Video", "Dauer", "Format"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setStretchLastSection(False)
        self._tree.setUniformRowHeights(True)
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
        expanded, selected = self._view_state()
        first_load = self._tree.topLevelItemCount() == 0
        self._tree.clear()

        groups: dict[FlightDay, list[LibraryEntry]] = defaultdict(list)
        for entry in self._entries:
            if not self._only_new.isChecked() or entry.is_new:
                groups[entry.flight_day].append(entry)

        bold = QFont()
        bold.setBold(True)
        selected_item = None
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
                if entry.media_id == selected:
                    selected_item = item
            self._tree.addTopLevelItem(group)
            if day.folder_name in expanded or new_count or (first_load and index == 0):
                group.setExpanded(True)

        if selected_item is not None:
            self._tree.setCurrentItem(selected_item)
        self._update_summary()
        self._update_placeholder()

    def _make_item(self, entry: LibraryEntry, bold: QFont) -> QTreeWidgetItem:
        name = entry.path.name
        item = QTreeWidgetItem([name, format_duration(entry.duration), format_video(entry)])
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

    def _view_state(self) -> tuple[set[str], int | None]:
        expanded = set()
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            if group.isExpanded():
                expanded.add(group.toolTip(0))
        current = self._tree.currentItem()
        entry = current.data(0, ENTRY_ROLE) if current else None
        return expanded, entry.media_id if entry else None

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

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        entry = item.data(0, ENTRY_ROLE)
        if entry is not None and not entry.missing:
            self.video_activated.emit(entry)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        entry = item.data(0, ENTRY_ROLE) if item else None
        if entry is None:
            return
        menu = QMenu(self)
        if entry.is_new:
            menu.addAction("Als gesichtet markieren", lambda: self.review_toggled.emit(entry.media_id, True))
        else:
            menu.addAction("Als neu markieren", lambda: self.review_toggled.emit(entry.media_id, False))
        open_folder = menu.addAction(
            "Ordner im Explorer öffnen",
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(entry.path.parent))),
        )
        open_folder.setEnabled(not entry.missing)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

