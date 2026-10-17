import sqlite3

from fpvcut.core.library import MIGRATIONS, Library
from fpvcut.core.scanner import scan_library
from tests.test_scanner import fake_probe, write


def make_lib(tmp_path):
    root = tmp_path / "FPV"
    write(root / "28_08_26_Wiese" / "a.mp4", b"aaa")
    lib = Library(tmp_path / "lib.sqlite")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    return lib, root, lib.entries()[0].media_id


def test_add_and_list_clips_with_tags(tmp_path):
    lib, _, media_id = make_lib(tmp_path)
    lib.add_clip(media_id, 12_000, 15_500, ["Flip", "Gap"], "sauber")
    lib.add_clip(media_id, 0, None, ["crash"])
    lib.add_clip(media_id, 2_000, 4_000, ["CRASH", "flip"])  # vorhandene Schreibweise gewinnt

    clips = lib.clips_for(media_id)
    assert [(c.in_ms, c.out_ms) for c in clips] == [(0, None), (2000, 4000), (12000, 15500)]
    assert clips[0].is_whole_video and clips[0].tags == ["crash"]
    assert clips[1].tags == ["crash", "Flip"]
    assert clips[2].note == "sauber"
    assert lib.all_tags() == ["crash", "Flip", "Gap"]  # nach Häufigkeit
    assert lib.entries()[0].clip_count == 3
    lib.close()


def test_update_and_delete_clean_up_unused_tags(tmp_path):
    lib, _, media_id = make_lib(tmp_path)
    clip_id = lib.add_clip(media_id, 0, 1000, ["Crash", "Powerloop"])
    lib.update_clip(clip_id, ["Crash"], "neu")
    assert lib.all_tags() == ["Crash"]
    lib.delete_clip(clip_id)
    assert lib.clips_for(media_id) == [] and lib.all_tags() == []
    lib.close()


def test_favorites_survive_folder_rename(tmp_path):
    lib, root, media_id = make_lib(tmp_path)
    lib.add_clip(media_id, 1000, 2000, ["Crash"])
    (root / "28_08_26_Wiese").rename(root / "2026_08_28_Wiese")
    scan_library(lib, fake_probe)
    [entry] = lib.entries()
    assert entry.rel_path.startswith("2026_08_28_Wiese/")
    assert [c.tags for c in lib.clips_for(entry.media_id)] == [["Crash"]]
    lib.close()


def test_migrates_existing_database(tmp_path):
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.close()
    lib = Library(db)
    assert lib.conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert lib.all_tags() == []
    lib.close()
