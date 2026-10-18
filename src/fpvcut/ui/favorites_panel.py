"""Favoriten-Browser: alle Favoriten der Bibliothek, filterbar nach Tags und Text."""

from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core.clip_filter import clip_duration, filter_clips
from fpvcut.core.library import Clip, LibraryEntry
from fpvcut.ui.flow_layout import TagArea
from fpvcut.ui.info_panel import clip_range_text
from fpvcut.ui.library_panel import format_duration
from fpvcut.ui.mime import MIME_CLIPS

ITEM_ROLE = Qt.ItemDataRole.UserRole


class _FavoritesTree(QTreeWidget):
    """Ausgewählte Favoriten lassen sich in die Timeline ziehen."""

    def mimeTypes(self) -> list[str]:  # noqa: N802  (Qt-Name)
        return [MIME_CLIPS]

    def mimeData(self, items) -> QMimeData:  # noqa: N802
        ids = [item.data(0, ITEM_ROLE)[0].id for item in items if not item.data(0, ITEM_ROLE)[1].missing]
        data = QMimeData()
        data.setData(MIME_CLIPS, json.dumps(ids).encode())
        return data


class FavoritesPanel(QWidget):
    clip_activated = Signal(object, object)  # Clip, LibraryEntry
    clip_edit_requested = Signal(object)  # Clip
    clip_delete_requested = Signal(object)  # Clip
    add_to_timeline_requested = Signal(list)  # Favoriten-IDs

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[Clip, LibraryEntry]] = []

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Suche in Dateiname, Flugtag, Notiz …")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _text: self._rebuild())

        # Tags als umschaltbare Knöpfe, die wie Text umbrechen. Das Feld wächst bis acht Zeilen mit,
        # danach wird gescrollt; über den Trenner darunter lässt es sich größer oder kleiner ziehen.
        self._tags = TagArea(max_rows=8, auto_height=False, parent=self)
        self._tags_sized_by_user = False

        self._mode = QComboBox(self)
        self._mode.addItems(["mind. ein Tag", "alle Tags"])
        self._mode.setToolTip("Bei mehreren gewählten Tags: reicht einer, oder müssen alle passen?")
        self._mode.currentIndexChanged.connect(lambda _i: self._rebuild())
        reset = QPushButton("Filter zurücksetzen", self)
        reset.clicked.connect(self.reset_filter)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Tags:", self))
        filter_row.addWidget(self._mode)
        filter_row.addStretch(1)
        filter_row.addWidget(reset)

        self._summary = QLabel(self)

        self._tree = _FavoritesTree(self)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._tree.setHeaderLabels(["Favorit", "Länge", "Tags"])
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(True)
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 120)
        self._tree.itemActivated.connect(self._on_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_menu)
        delete = QShortcut(QKeySequence.StandardKey.Delete, self._tree)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._delete_current)

        self._placeholder = QLabel(
            "Noch keine Favoriten.\nIm Player mit I/O einen Ausschnitt wählen und F drücken.", self
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lower = QWidget(self)
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addWidget(self._summary)
        lower_layout.addWidget(self._tree, 1)
        lower_layout.addWidget(self._placeholder, 1)

        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.addWidget(self._tags)
        self._splitter.addWidget(lower)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        self._splitter.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._search)
        layout.addLayout(filter_row)
        layout.addWidget(self._splitter, 1)

    # --- Daten -----------------------------------------------------------

    def set_data(self, items: list[tuple[Clip, LibraryEntry]], tag_counts: list[tuple[str, int]]) -> None:
        self._items = items
        self._tags.set_tags([(name, f"{name} ({count})") for name, count in tag_counts],
                            checked=set(self.selected_tags()))
        for button in self._tags.buttons.values():
            button.toggled.connect(lambda _checked: self._rebuild())
        self._fit_tags()
        self._rebuild()

    @property
    def _tag_buttons(self) -> dict[str, QToolButton]:
        return self._tags.buttons

    def _fit_tags(self) -> None:
        """Tag-Feld so hoch wie nötig (höchstens acht Zeilen), solange es niemand von Hand gezogen hat."""
        if self._tags_sized_by_user or not self._tag_buttons:
            return
        total = self._splitter.height() - self._splitter.handleWidth()
        if total <= 0:
            return
        width = self._splitter.width() - self._tags.verticalScrollBar().sizeHint().width()
        height = min(self._tags.fitting_height(max(width, 1)), max(total - 80, self._tags.row_height()))
        self._splitter.setSizes([height, max(total - height, 0)])

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        self._tags_sized_by_user = True

    def eventFilter(self, watched, event) -> bool:  # noqa: N802  (Qt-Name)
        # Erst wenn der Splitter selbst seine Größe hat (z. B. beim ersten Öffnen des Reiters), passt die Rechnung.
        if watched is self._splitter and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._fit_tags()
        return super().eventFilter(watched, event)

    def selected_tags(self) -> list[str]:
        return [name for name, button in self._tag_buttons.items() if button.isChecked()]

    def reset_filter(self) -> None:
        self._search.clear()
        for button in self._tag_buttons.values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
        self._rebuild()

    def visible_items(self) -> list[tuple[Clip, LibraryEntry]]:
        return filter_clips(
            self._items, self.selected_tags(), self._mode.currentIndex() == 1, self._search.text().strip()
        )

    def _rebuild(self) -> None:
        current = self._tree.currentItem()
        current_id = current.data(0, ITEM_ROLE)[0].id if current else None
        self._tree.clear()
        visible = self.visible_items()
        for clip, entry in visible:
            start = "ganzes Video" if clip.is_whole_video else f"ab {format_duration(clip.in_s)}"
            title = f"{entry.path.name}  ·  {start}"
            item = QTreeWidgetItem(
                [title, format_duration(clip_duration(clip, entry)), ", ".join(clip.tags)]
            )
            item.setData(0, ITEM_ROLE, (clip, entry))
            tooltip = [clip_range_text(clip.in_s, clip.out_s), entry.flight_day.label, str(entry.path)]
            if clip.note:
                tooltip.append(f"Notiz: {clip.note}")
            item.setToolTip(0, "\n".join(tooltip))
            item.setToolTip(2, ", ".join(clip.tags))
            if entry.missing:
                item.setText(0, f"{title} (Datei fehlt)")
                for col in range(3):
                    item.setForeground(col, QBrush(QColor("gray")))
            self._tree.addTopLevelItem(item)
            if clip.id == current_id:
                self._tree.setCurrentItem(item)

        total = sum(clip_duration(c, e) or 0 for c, e in visible)
        filtered = len(visible) != len(self._items)
        count = f"{len(visible)} von {len(self._items)}" if filtered else str(len(visible))
        self._summary.setText(f"{count} Favoriten · zusammen {format_duration(total)}")
        empty = not self._items
        self._tree.setVisible(not empty)
        self._summary.setVisible(not empty)
        self._placeholder.setVisible(empty)

    # --- Interaktion -----------------------------------------------------

    def selected_clip_ids(self) -> list[int]:
        """Ausgewählte Favoriten in Anzeigereihenfolge, ohne fehlende Dateien."""
        result = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            clip, entry = item.data(0, ITEM_ROLE)
            if item.isSelected() and not entry.missing:
                result.append(clip.id)
        return result

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        clip, entry = item.data(0, ITEM_ROLE)
        if not entry.missing:
            self.clip_activated.emit(clip, entry)

    def _delete_current(self) -> None:
        item = self._tree.currentItem()
        if item is not None:
            self.clip_delete_requested.emit(item.data(0, ITEM_ROLE)[0])

    def _show_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        clip, entry = item.data(0, ITEM_ROLE)
        menu = QMenu(self)
        play = menu.addAction("Abspielen (Schleife)", lambda: self.clip_activated.emit(clip, entry))
        play.setEnabled(not entry.missing)
        if not item.isSelected():
            self._tree.setCurrentItem(item)
        ids = self.selected_clip_ids()
        add = menu.addAction(
            "Zur Timeline hinzufügen (E)" if len(ids) < 2 else f"{len(ids)} Favoriten zur Timeline hinzufügen (E)",
            lambda: self.add_to_timeline_requested.emit(ids),
        )
        add.setEnabled(bool(ids))
        menu.addAction("Tags und Notiz bearbeiten …", lambda: self.clip_edit_requested.emit(clip))
        menu.addSeparator()
        menu.addAction("Favorit löschen", lambda: self.clip_delete_requested.emit(clip))
        menu.exec(self._tree.viewport().mapToGlobal(pos))
