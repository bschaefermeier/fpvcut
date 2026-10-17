from datetime import date

import pytest

from fpvcut.core.library import Library
from fpvcut.core.renamer import (
    CHECK, CONFLICT, NO_DATE, OK, SAME, apply_renames, plan_renames, refresh_status, undo_renames, write_log,
)
from fpvcut.core.scanner import scan_library
from tests.test_scanner import fake_probe, write

TODAY = date(2026, 10, 17)


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "db" / "library.sqlite")
    yield library
    library.close()


def plan(lib):
    return {i.rel_path: i for i in plan_renames([(r.id, r.path) for r in lib.roots()], today=TODAY)}


def test_proposals_and_unclear_cases(lib, tmp_path):
    root = tmp_path / "FPV"
    for folder in ["28_08_26_Wiese", "Wald_03_07_25", "2026_01_15_Halle", "2026/12_08_15_Feld",
                   "Sonstiges", "31_02_26_Kaputt", "2026_01_15_Halle/raw", "05_11_26_Zukunft"]:
        write(root / folder / "a.mp4", folder.encode())
    (root / "leer").mkdir()
    lib.add_root(root)
    items = plan(lib)
    assert items["28_08_26_Wiese"].new_name == "2026_08_28_Wiese"
    assert items["28_08_26_Wiese"].status == OK and items["28_08_26_Wiese"].checked
    assert items["Wald_03_07_25"].new_name == "2025_07_03_Wald"
    assert items["2026_01_15_Halle"].status == SAME and not items["2026_01_15_Halle"].checked
    # Unterordner eines Flugtags und Ordner ohne Videos tauchen nicht auf.
    assert "2026_01_15_Halle/raw" not in items and "leer" not in items and "2026" not in items
    # Unklar: zweideutig, ungültiges Datum, Zukunft. Nicht vorausgewählt.
    feld = items["2026/12_08_15_Feld"]
    assert feld.new_name == "2015_08_12_Feld" and feld.status == CHECK and "15.08.2012" in feld.note
    assert not feld.checked
    assert items["31_02_26_Kaputt"].status == NO_DATE and not items["31_02_26_Kaputt"].checked
    assert items["Sonstiges"].status == NO_DATE
    assert items["05_11_26_Zukunft"].status == CHECK and "Zukunft" in items["05_11_26_Zukunft"].note


def test_conflicts_and_manual_names(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "28_08_26_Wiese" / "a.mp4", b"a")
    write(root / "2026_08_28_Wiese" / "b.mp4", b"b")  # Zielname gibt es schon
    write(root / "Wiese_28_08_26" / "c.mp4", b"c")
    write(root / "Sonstiges" / "d.mp4", b"d")
    lib.add_root(root)
    items = plan(lib)
    assert items["28_08_26_Wiese"].status == CONFLICT and not items["28_08_26_Wiese"].checked
    assert items["Wiese_28_08_26"].status == CONFLICT
    items["Wiese_28_08_26"].new_name = "2026_08_28_Wiese_2"
    items["Sonstiges"].new_name = "Sonstiges?"
    refresh_status(list(items.values()))
    assert items["Wiese_28_08_26"].status == OK
    assert items["Sonstiges"].status == CONFLICT and "ungültig" in items["Sonstiges"].note
    items["Sonstiges"].new_name = "Diverses"
    refresh_status(list(items.values()))
    assert items["Sonstiges"].status == CHECK  # erlaubt, aber nicht im Schema


def test_apply_updates_library_and_undo(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "Alte_Flüge" / "28_08_26_Wiese" / "a.mp4", b"aaa")
    write(root / "Alte_Flüge" / "28_08_26_Wiese" / "raw" / "b.mp4", b"bbb")
    write(root / "28_08_26_Wiesen" / "c.mp4", b"ccc")  # Präfix-Falle für das Nachtragen
    lib.add_root(root)
    scan_library(lib, fake_probe)
    clip = lib.add_clip(lib.entries()[0].media_id, 0, 1000, ["Wiese"], "")  # Favorit bleibt erhalten
    items = list(plan(lib).values())
    result = apply_renames(items, lib.conn)
    assert not result.errors and len(result.done) == 2
    assert (root / "Alte_Flüge" / "2026_08_28_Wiese" / "raw" / "b.mp4").exists()
    paths = sorted(e.rel_path for e in lib.entries())
    assert paths == ["2026_08_28_Wiesen/c.mp4", "Alte_Flüge/2026_08_28_Wiese/a.mp4",
                     "Alte_Flüge/2026_08_28_Wiese/raw/b.mp4"]
    rescan = scan_library(lib, fake_probe)
    assert rescan.new == 0 and rescan.rehashed == 0 and rescan.missing == 0  # nichts neu zu hashen
    assert len(lib.all_clips()) == 1 and clip is not None
    write_log(result.done, tmp_path / "log.json")
    assert "2026_08_28_Wiese" in (tmp_path / "log.json").read_text(encoding="utf-8")

    undo = undo_renames(result.done, lib.conn)
    assert not undo.errors
    assert sorted(e.rel_path for e in lib.entries()) == ["28_08_26_Wiesen/c.mp4", "Alte_Flüge/28_08_26_Wiese/a.mp4",
                                                         "Alte_Flüge/28_08_26_Wiese/raw/b.mp4"]
    assert (root / "28_08_26_Wiesen" / "c.mp4").exists()


def test_nested_flight_days_rename_deepest_first(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "28_08_26_Ausflug" / "29_08_26_Berg" / "a.mp4", b"a")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    items = list(plan(lib).values())
    result = apply_renames(items, lib.conn)
    assert not result.errors and len(result.done) == 2
    assert (root / "2026_08_28_Ausflug" / "2026_08_29_Berg" / "a.mp4").exists()
    assert [e.rel_path for e in lib.entries()] == ["2026_08_28_Ausflug/2026_08_29_Berg/a.mp4"]
    undo_renames(result.done, lib.conn)
    assert (root / "28_08_26_Ausflug" / "29_08_26_Berg" / "a.mp4").exists()
    assert [e.rel_path for e in lib.entries()] == ["28_08_26_Ausflug/29_08_26_Berg/a.mp4"]
