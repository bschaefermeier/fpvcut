"""Import von der SD-Karte: kopieren, prüfen, auf der Karte löschen, Karte auswerfen.

Quelle (Laufwerk und Unterordner), Bibliotheksordner und die beiden Häkchen merkt sich der Dialog
in ``import.json`` neben der Datenbank; steckt die Karte, ist er beim nächsten Mal fertig ausgefüllt.
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core import drives
from fpvcut.core.drives import ImportSource
from fpvcut.core.importer import ImportResult, collect_files, folder_name, run_import, total_size
from fpvcut.core.library import Library
from fpvcut.core.scanner import VIDEO_EXTENSIONS
from fpvcut.i18n import format_date

POLL_MS = 2000


def format_size(size: int) -> str:
    return f"{size / 1e9:.1f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"


def load_settings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(path: Path, settings: dict) -> None:
    try:
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def remembered_source(settings: dict) -> ImportSource | None:
    data = settings.get("source")
    return ImportSource.from_dict(data) if isinstance(data, dict) else None


def locate_source(settings: dict) -> Path | None:
    """Wo der gemerkte Importordner gerade liegt (``None``: Karte steckt nicht)."""
    source = remembered_source(settings)
    return drives.find_source(source) if source else None


class _ImportSignals(QObject):
    progress = Signal(object, object, str)  # Bytes fertig, Bytes gesamt, Datei
    finished = Signal(object, str)  # ImportResult, Fehler beim Auswerfen ("" = keiner)


class _ImportTask(QRunnable):
    def __init__(self, files: list[Path], target: Path, delete: bool, eject_drive: str | None) -> None:
        super().__init__()
        self.files, self.target, self.delete, self.eject_drive = files, target, delete, eject_drive
        self.cancel = threading.Event()
        self.signals = _ImportSignals()

    def run(self) -> None:
        try:
            result = run_import(self.files, self.target, self.delete, self.signals.progress.emit,
                                self.cancel.is_set)
        except Exception as exc:  # noqa: BLE001
            result = ImportResult(errors=[str(exc)])
        eject_error = ""
        if self.eject_drive and result.complete:
            try:
                drives.eject(self.eject_drive)
            except OSError as exc:
                eject_error = str(exc)
        self.signals.finished.emit(result, eject_error)


class ImportDialog(QDialog):
    def __init__(
        self,
        library: Library,
        settings_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Import from SD card"))
        self.resize(720, 560)
        self.library = library
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.source: Path | None = None
        self.files: list[Path] = []
        self.result: ImportResult | None = None
        self._task: _ImportTask | None = None
        self._recording_day: date | None = None

        # Quelle
        self._source_label = QLabel(self)
        self._source_label.setWordWrap(True)
        choose = QPushButton(self.tr("Choose folder …"), self)
        choose.clicked.connect(self.choose_source_dialog)
        source_row = QHBoxLayout()
        source_row.addWidget(self._source_label, 1)
        source_row.addWidget(choose)
        self._file_list = QListWidget(self)

        # Ziel
        self._root = QComboBox(self)
        for root in library.roots():
            self._root.addItem(str(root.path), root.id)
        index = self._root.findData(self.settings.get("root_id"))
        if index >= 0:
            self._root.setCurrentIndex(index)
        self._date = QDateEdit(QDate.currentDate(), self)
        self._date.setCalendarPopup(True)
        self._date_hint = QPushButton(self)
        self._date_hint.setFlat(True)
        self._date_hint.hide()
        self._date_hint.clicked.connect(self._use_recording_day)
        date_row = QHBoxLayout()
        date_row.addWidget(self._date)
        date_row.addWidget(self._date_hint)
        date_row.addStretch(1)
        self._spot = QLineEdit(self)
        self._spot.setPlaceholderText(self.tr("e.g. Field"))
        spots = sorted({e.flight_day.spot for e in library.entries() if e.flight_day.date and e.flight_day.spot},
                       key=str.lower)
        completer = QCompleter(spots, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._spot.setCompleter(completer)
        self._target_label = QLabel(self)
        self._target_label.setWordWrap(True)
        form = QFormLayout()
        form.addRow(self.tr("Library folder"), self._root)
        form.addRow(self.tr("Flight day"), date_row)
        form.addRow(self.tr("Spot"), self._spot)
        form.addRow("", self._target_label)

        self._delete = QCheckBox(self.tr("Delete from the SD card after checking the copies"), self)
        self._delete.setChecked(bool(self.settings.get("delete", True)))
        self._eject = QCheckBox(self.tr("Eject the SD card afterwards"), self)
        self._eject.setChecked(bool(self.settings.get("eject", True)))

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1000)
        self._progress.hide()
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._start = QPushButton(self.tr("Import"), self)
        self._start.setDefault(True)
        self._start.clicked.connect(self.start)
        self._close = QPushButton(self.tr("Close"), self)
        self._close.clicked.connect(self._close_or_cancel)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._start)
        buttons.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("<b>From</b>"), self))
        layout.addLayout(source_row)
        layout.addWidget(self._file_list, 1)
        layout.addWidget(QLabel(self.tr("<b>To</b>"), self))
        layout.addLayout(form)
        layout.addWidget(self._delete)
        layout.addWidget(self._eject)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        for signal in (self._root.currentIndexChanged, self._date.dateChanged, self._spot.textChanged):
            signal.connect(self._update_target)
        # Karte noch nicht eingesteckt? Dann im Hintergrund nachsehen, bis sie da ist.
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_source)
        self.set_source(locate_source(self.settings))
        self._poll.start()
        self._spot.setFocus()

    # --- Quelle -----------------------------------------------------------

    def choose_source_dialog(self) -> None:
        start = str(self.source) if self.source else ""
        folder = QFileDialog.getExistingDirectory(self, self.tr("Folder with the videos on the SD card"), start)
        if folder:
            self.remember_source(Path(folder))

    def remember_source(self, folder: Path) -> None:
        """Ordner als Quelle nehmen und für das nächste Mal merken."""
        self.settings["source"] = ImportSource.for_folder(folder).to_dict()
        save_settings(self.settings_path, self.settings)
        self.set_source(folder)

    def set_source(self, folder: Path | None) -> None:
        self.source = folder
        self.files = collect_files(folder) if folder and folder.is_dir() else []
        self._file_list.clear()
        for f in self.files:
            self._file_list.addItem(f"{f.relative_to(folder).as_posix()}  ({format_size(f.stat().st_size)})")
        videos = [f for f in self.files if f.suffix.lower() in VIDEO_EXTENSIONS]
        if folder is None:
            remembered = remembered_source(self.settings)
            if remembered:
                text = self.tr("SD card not found ({path}). Insert it or choose the folder.").format(
                    path=remembered.path)
            else:
                text = self.tr("Choose the folder with the videos on the SD card once; "
                               "FPVCut remembers it.")
        else:
            others = len(self.files) - len(videos)
            text = self.tr("{path}: %n video(s)", "", len(videos)).format(path=folder)
            if others:
                text += self.tr(" + %n accompanying file(s)", "", others)
            if self.files:
                text += f", {format_size(total_size(self.files))}"
        self._source_label.setText(text)
        days = {date.fromtimestamp(f.stat().st_mtime) for f in videos}
        self._recording_day = days.pop() if len(days) == 1 else None
        self._update_target()

    def _poll_source(self) -> None:
        if self._task is None and self.source is None:
            found = locate_source(self.settings)
            if found:
                self.set_source(found)

    def _use_recording_day(self) -> None:
        if self._recording_day:
            d = self._recording_day
            self._date.setDate(QDate(d.year, d.month, d.day))

    # --- Ziel -------------------------------------------------------------

    def target_dir(self) -> Path | None:
        if self._root.currentIndex() < 0:
            return None
        d = self._date.date()
        return Path(self._root.currentText()) / folder_name(date(d.year(), d.month(), d.day()), self._spot.text())

    def _update_target(self) -> None:
        target = self.target_dir()
        if target is None:
            self._target_label.setText(self.tr("Add a library folder first (File → Add library folder)."))
        elif target.exists():
            self._target_label.setText(self.tr("→ {path} (exists, the videos are added)").format(path=target))
        else:
            self._target_label.setText(f"→ {target}")
        d = self._date.date()
        chosen = date(d.year(), d.month(), d.day())
        show_hint = self._recording_day is not None and self._recording_day != chosen
        if show_hint:
            self._date_hint.setText(self.tr("Recorded on {date}: use this date").format(
                date=format_date(self._recording_day)))
        self._date_hint.setVisible(show_hint)
        self._start.setEnabled(self._task is None and bool(self.files) and target is not None)

    # --- Import -----------------------------------------------------------

    def start(self, confirm: bool = True) -> bool:
        target = self.target_dir()
        if self._task or not self.files or target is None or self.source is None:
            return False
        size = total_size(self.files)
        try:
            free = shutil.disk_usage(target.parent).free
        except OSError:
            free = None
        if free is not None and free < size:
            QMessageBox.warning(self, self.tr("Import"), self.tr(
                "Not enough space: {needed} needed, {free} free.").format(
                needed=format_size(size), free=format_size(free)))
            return False
        if target == self.source or self.source in target.parents or target in self.source.parents:
            QMessageBox.warning(self, self.tr("Import"), self.tr(
                "The folder on the SD card and the target folder overlap. Choose a different folder."))
            return False
        if confirm and not self._spot.text().strip():
            answer = QMessageBox.question(
                self, self.tr("Import"), self.tr("No spot entered. Import into {name} anyway?").format(
                    name=target.name))
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.settings.update(root_id=self._root.currentData(), delete=self._delete.isChecked(),
                             eject=self._eject.isChecked())
        save_settings(self.settings_path, self.settings)

        drive = self.source.anchor if self._eject.isChecked() else None
        if drive and drive.upper() == target.anchor.upper():
            drive = None  # Quelle auf derselben Platte wie die Bibliothek: nichts auswerfen
        self._task = _ImportTask(list(self.files), target, self._delete.isChecked(), drive)
        self._task.signals.progress.connect(self._on_progress)
        self._task.signals.finished.connect(self._on_finished)
        self._set_running(True)
        self._status.setText(self.tr("Copying …"))
        QThreadPool.globalInstance().start(self._task)
        return True

    def _set_running(self, running: bool) -> None:
        for widget in (self._root, self._date, self._spot, self._delete, self._eject, self._date_hint):
            widget.setEnabled(not running)
        self._progress.setVisible(running)
        self._progress.setValue(0)
        self._close.setText(self.tr("Cancel") if running else self.tr("Close"))
        self._start.setEnabled(not running and bool(self.files))

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setValue(int(1000 * done / total) if total else 1000)
        self._status.setText(self.tr("Copying and checking {name} ({done} of {total})").format(
            name=name, done=format_size(done), total=format_size(total)))

    def _on_finished(self, result: ImportResult, eject_error: str) -> None:
        self._task = None
        self.result = result
        self._set_running(False)
        lines = [self.tr("%n file(s) copied and checked.", "", len(result.copied))]
        if result.already_there:
            lines.append(self.tr("%n file(s) were already in the folder.", "", len(result.already_there)))
        if result.deleted:
            lines.append(self.tr("%n file(s) deleted on the SD card.", "", result.deleted))
        if result.cancelled:
            lines.append(self.tr("Cancelled: nothing was deleted on the SD card."))
        if result.errors:
            lines.append(self.tr("Problems (these files stay on the card):") + "\n" + "\n".join(result.errors[:8]))
        if self._eject.isChecked():
            if eject_error:
                lines.append(self.tr("The SD card could not be ejected: {error}").format(error=eject_error))
            elif result.complete:
                lines.append(self.tr("The SD card was ejected and can be removed."))
            else:
                lines.append(self.tr("The SD card was not ejected because of the problems above."))
        self._status.setText("\n".join(lines))
        ejected = self._eject.isChecked() and result.complete and not eject_error
        self.set_source(None if ejected else self.source)

    def _close_or_cancel(self) -> None:
        if self._task:
            self._task.cancel.set()
        else:
            self.accept()

    def done(self, code: int) -> None:  # noqa: D401  (Qt-Name)
        if self._task:  # Esc oder Fenster schließen während des Kopierens: erst abbrechen
            self._task.cancel.set()
            return
        self._poll.stop()
        super().done(code)

    @property
    def imported(self) -> bool:
        return bool(self.result and (self.result.copied or self.result.already_there))

