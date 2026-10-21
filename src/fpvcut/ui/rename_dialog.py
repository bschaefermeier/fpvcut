"""Dialog zum Umbenennungs-Helfer: Vorschau alt → neu, unklare Fälle markiert, erst nach Bestätigung."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core.library import Library
from fpvcut.core.renamer import (
    CHECK, CONFLICT, NO_DATE, OK, SAME, RenameItem, RenameResult, apply_renames, plan_renames, refresh_status,
    undo_renames, write_log,
)

STATUS_TEXT = {
    OK: QT_TRANSLATE_NOOP("RenameDialog", "OK"), CHECK: QT_TRANSLATE_NOOP("RenameDialog", "Check"),
    CONFLICT: QT_TRANSLATE_NOOP("RenameDialog", "Conflict"), NO_DATE: QT_TRANSLATE_NOOP("RenameDialog", "No date"),
    SAME: QT_TRANSLATE_NOOP("RenameDialog", "Fits"),
}
STATUS_COLOR = {OK: "#3a9a4a", CHECK: "#d08a00", CONFLICT: "#d04040", NO_DATE: "#888888", SAME: "#888888"}
COL_CHECK, COL_OLD, COL_NEW, COL_NOTE = range(4)


class RenameDialog(QDialog):
    def __init__(
        self,
        library: Library,
        log_dir: Path,
        before_apply: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Rename folders to the scheme YYYY-MM-DD_Spot"))
        self.resize(900, 560)
        self.library = library
        self.log_dir = log_dir
        self.before_apply = before_apply
        self.changed = False  # wurde etwas umbenannt (auch wenn wieder rückgängig gemacht)?
        self._done: list[RenameItem] = []
        self._result_text = ""
        self._filling = False
        self.items = plan_renames([(r.id, r.path) for r in library.roots()])

        intro = QLabel(
            self.tr("Double-click a new name to change it. Unclear cases (yellow) are not "
                    "preselected, conflicts (red) need a different name first. "
                    "Clips and timeline are kept."), self)
        intro.setWordWrap(True)
        self._show_same = QCheckBox(self.tr("Also show folders that already fit"), self)
        self._show_same.toggled.connect(self._fill)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["", self.tr("Folder"), self.tr("New name"), self.tr("Note")])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_OLD, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_NEW, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self._on_item_changed)

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._apply = QPushButton(self)
        self._apply.setDefault(True)
        self._apply.clicked.connect(self.apply)
        self._undo = QPushButton(self.tr("Undo"), self)
        self._undo.clicked.connect(self.undo)
        self._undo.hide()
        close = QPushButton(self.tr("Close"), self)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self._undo)
        buttons.addStretch(1)
        buttons.addWidget(self._apply)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self._show_same)
        layout.addWidget(self.table, 1)
        layout.addWidget(self._summary)
        layout.addLayout(buttons)
        self._fill()

    # --- Tabelle ---------------------------------------------------------

    def visible_items(self) -> list[RenameItem]:
        show_same = self._show_same.isChecked()
        return [i for i in self.items if show_same or i.status != SAME]

    def _fill(self) -> None:
        self._filling = True
        rows = self.visible_items()
        self.table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            check = QTableWidgetItem()
            selectable = item.status in (OK, CHECK)
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled if selectable
                           else Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, self.items.index(item))
            old = QTableWidgetItem(item.rel_path)
            old.setFlags(Qt.ItemFlag.ItemIsEnabled)
            old.setToolTip(str(item.path))
            new = QTableWidgetItem(item.new_name)
            new.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
            status = self.tr(STATUS_TEXT[item.status])
            note = QTableWidgetItem(f"{status}: {item.note}" if item.note else status)
            note.setFlags(Qt.ItemFlag.ItemIsEnabled)
            note.setToolTip(note.text())
            note.setForeground(QBrush(QColor(STATUS_COLOR[item.status])))
            for col, cell in ((COL_CHECK, check), (COL_OLD, old), (COL_NEW, new), (COL_NOTE, note)):
                self.table.setItem(row, col, cell)
        self._filling = False
        self._update_summary()

    def _item_for_row(self, row: int) -> RenameItem:
        return self.items[self.table.item(row, COL_CHECK).data(Qt.ItemDataRole.UserRole)]

    def _on_item_changed(self, cell: QTableWidgetItem) -> None:
        if self._filling:
            return
        item = self._item_for_row(cell.row())
        if cell.column() == COL_CHECK:
            item.checked = cell.checkState() == Qt.CheckState.Checked
            self._update_summary()
        elif cell.column() == COL_NEW:
            item.new_name = cell.text().strip()
            refresh_status(self.items)
            item.checked = item.status in (OK, CHECK)  # wer einen Namen einträgt, will umbenennen
            self._fill()

    def set_new_name(self, rel_path: str, name: str) -> None:
        """Für Tests und Skripte: neuen Namen wie per Hand eintragen."""
        for row in range(self.table.rowCount()):
            if self._item_for_row(row).rel_path == rel_path:
                self.table.item(row, COL_NEW).setText(name)
                return
        raise KeyError(rel_path)

    def selected(self) -> list[RenameItem]:
        return [i for i in self.items if i.checked and i.status in (OK, CHECK)]

    def _update_summary(self) -> None:
        counts = {s: sum(1 for i in self.items if i.status == s) for s in STATUS_TEXT}
        if not self.items:
            text = self.tr("No flight day folders found. Are library folders set up and reachable?")
        else:
            parts = [self.tr("{count} clear").format(count=counts[OK])]
            for status, label in ((CHECK, self.tr("{count} to check")), (CONFLICT, self.tr("{count} with conflict")),
                                  (NO_DATE, self.tr("{count} without date")), (SAME, self.tr("{count} already fit"))):
                if counts[status]:
                    parts.append(label.format(count=counts[status]))
            text = self.tr("Folders: {parts}").format(parts=", ".join(parts))
        if self._done:
            text = self._result_text + "\n" + text
        self._summary.setText(text)
        n = len(self.selected())
        self._apply.setText(self.tr("Rename %n folder(s)", "", n))
        self._apply.setEnabled(n > 0)

    # --- Umbenennen ------------------------------------------------------

    def apply(self, confirm: bool = True) -> RenameResult | None:
        chosen = self.selected()
        if not chosen:
            return None
        if confirm:
            answer = QMessageBox.question(
                self, self.tr("Rename"),
                self.tr("Rename %n folder(s) now?\n\nAn open video will be closed for this.", "", len(chosen)))
            if answer != QMessageBox.StandardButton.Yes:
                return None
        if self.before_apply:
            self.before_apply()  # Windows sperrt Ordner mit geöffneten Dateien
        result = apply_renames(self.items, self.library.conn)
        self.changed = self.changed or bool(result.done)
        self._done = result.done
        if result.done:
            try:
                write_log(result.done, self.log_dir / f"umbenannt_{datetime.now():%Y-%m-%d_%H%M%S}.json")
            except OSError:
                pass
        self._result_text = self.tr("%n folder(s) renamed.", "", len(result.done))
        if result.errors:
            self._result_text += self.tr(" Not possible:") + "\n" + "\n".join(result.errors[:8])
        self._undo.setVisible(bool(result.done))
        self._replan()
        return result

    def undo(self) -> RenameResult | None:
        if not self._done:
            return None
        if self.before_apply:
            self.before_apply()
        result = undo_renames(self._done, self.library.conn)
        self.changed = self.changed or bool(result.done)
        self._done = []
        self._result_text = self.tr("%n rename(s) undone.", "", len(result.done))
        if result.errors:
            self._result_text += self.tr(" Not possible:") + "\n" + "\n".join(result.errors[:8])
        self._undo.hide()
        self._replan(keep_message=True)
        return result

    def _replan(self, keep_message: bool = False) -> None:
        self.items = plan_renames([(r.id, r.path) for r in self.library.roots()])
        self._fill()
        if keep_message:
            self._summary.setText(self._result_text + "\n" + self._summary.text())
