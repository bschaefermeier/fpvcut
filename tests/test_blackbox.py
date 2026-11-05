from datetime import date, datetime

import pytest

from fpvcut.core import blackbox
from fpvcut.core.blackbox import collect_logs, has_logs, log_start, recording_day
from tests.test_scanner import write


def log(start: str = "2026-10-03T14:23:11.123+01:00") -> bytes:
    return (b"H Product:Blackbox flight data recorder by Nicholas Sherlock\n"
            b"H Firmware revision:Betaflight 4.5.1\n"
            + f"H Log start datetime:{start}\n".encode() + b"I" * 200)


@pytest.fixture
def flash(tmp_path):
    """Flugcontroller mit Flash-Speicher im Massenspeicher-Modus."""
    fc = tmp_path / "fc"
    write(fc / "BTFL_ALL.BBL", log() * 2)
    write(fc / "BTFL_001.BBL", log())
    write(fc / "BTFL_002.BBL", log("2026-10-03T15:01:00.000+01:00"))
    write(fc / "README.TXT", b"nicht importieren")
    return fc


def test_collect_logs_skips_combined_log_next_to_single_logs(flash):
    assert [p.name for p in collect_logs(flash)] == ["BTFL_001.BBL", "BTFL_002.BBL"]


def test_collect_logs_from_sd_card_in_subfolder(tmp_path):
    fc = tmp_path / "fc"
    write(fc / "LOGS" / "LOG00001.BFL", log())
    write(fc / "LOGS" / "LOG00002.BFL", b"")  # leer: Aufzeichnung ohne Daten
    write(fc / "BTFL_ALL.BBL", log())  # allein, also doch nehmen
    assert [p.relative_to(fc).as_posix() for p in collect_logs(fc)] == ["BTFL_ALL.BBL", "LOGS/LOG00001.BFL"]
    assert has_logs(fc) and has_logs(fc / "LOGS")
    assert not has_logs(tmp_path / "nichts")


def test_has_logs_ignores_camera_card(tmp_path):
    card = tmp_path / "card"
    write(card / "DCIM" / "100MEDIA" / "DJI_0001.MP4", b"a")
    assert not has_logs(card)


def test_log_start_reads_header(flash):
    assert log_start(flash / "BTFL_001.BBL") == datetime(2026, 10, 3, 14, 23, 11)


def test_log_start_ignores_unset_clock(tmp_path):
    write(tmp_path / "a.BFL", log("0000-01-01T00:00:00.000+00:00"))
    write(tmp_path / "b.BFL", log("1970-01-01T00:00:12.000+00:00"))
    write(tmp_path / "c.BFL", b"kein Kopf")
    assert [log_start(tmp_path / n) for n in ("a.BFL", "b.BFL", "c.BFL")] == [None, None, None]


def test_recording_day_only_when_unique(flash, tmp_path):
    assert recording_day(collect_logs(flash)) == date(2026, 10, 3)
    write(tmp_path / "x.BFL", log("2026-10-04T09:00:00.000+01:00"))
    assert recording_day([*collect_logs(flash), tmp_path / "x.BFL"]) is None


# --- Dialog -----------------------------------------------------------------

def test_log_import_goes_into_existing_flight_day(monkeypatch, tmp_path, flash):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QDate, QThreadPool

    from fpvcut.core import drives
    from fpvcut.core.probe import MediaInfo
    from fpvcut.ui import player
    from fpvcut.ui.import_dialog import ImportSource
    from fpvcut.ui.main_window import MainWindow

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    monkeypatch.setattr(drives, "eject", lambda drive: None)
    monkeypatch.setattr(drives, "find_source", lambda source, accept=None: (
        source.path if source.path.is_dir() and (accept is None or accept(source.path)) else None))
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    library_root = tmp_path / "FPV"
    day_dir = library_root / "03_10_26_Wiese"  # Flugtag außerhalb des Schemas, Videos schon importiert
    write(day_dir / "DJI_0001.MP4", b"v")
    window.library.add_root(library_root)
    from fpvcut.core.scanner import scan_library
    scan_library(window.library, lambda path: MediaInfo())

    dialog = window.log_import_dialog()
    assert dialog.logs and dialog.source is None and not dialog._delete.isChecked()
    dialog.settings["source"] = ImportSource.for_folder(flash).to_dict()
    dialog.set_source(flash)
    assert len(dialog.files) == 2 and "2 Blackbox-Logs" in dialog._source_label.text()
    assert "Aufgenommen am 03.10.2026" in dialog._date_hint.text()
    dialog._use_recording_day()
    assert dialog._date.date() == QDate(2026, 10, 3)
    assert dialog._spot.text() == "Wiese"  # Spot vom vorhandenen Flugtag übernommen
    assert dialog.target_dir() == day_dir / blackbox.LOG_FOLDER
    assert "Flugtag vorhanden" in dialog._target_label.text()
    dialog._eject.setChecked(False)
    assert dialog.start(confirm=False)
    QThreadPool.globalInstance().waitForDone(10000)
    QtWidgets.QApplication.processEvents()
    assert dialog.result.complete and dialog.result.deleted == 0
    assert sorted(p.name for p in (day_dir / "Blackbox").iterdir()) == ["BTFL_001.BBL", "BTFL_002.BBL"]
    assert (flash / "BTFL_001.BBL").exists()  # Häkchen fürs Löschen war aus
    dialog.accept()

    # Ein anderer Tag ohne Flugtag-Ordner: neuer Ordner im Schema, eingegebener Spot bleibt.
    dialog = window.log_import_dialog()
    dialog._date.setDate(QDate(2026, 11, 7))
    assert dialog._spot.text() == ""
    dialog._spot.setText("Acker")
    assert dialog.target_dir() == library_root / "2026-11-07_Acker" / "Blackbox"
    dialog._date.setDate(QDate(2026, 10, 3))
    assert dialog._spot.text() == "Acker"
    dialog.reject()
    window.close()
