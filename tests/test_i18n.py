"""Sprachwahl und Übersetzungsdateien (die übrigen Tests laufen auf Deutsch, siehe conftest.py)."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QLocale, QSettings

from fpvcut import i18n

ROOT = Path(__file__).resolve().parents[1]
TS = i18n.I18N_DIR / "fpvcut_de.ts"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(i18n, "_settings", lambda: QSettings(ini, QSettings.Format.IniFormat))


@pytest.fixture
def english():
    app = QCoreApplication.instance()
    i18n.install(app, "en")
    yield
    i18n.install(app, "de")


def test_resolve_follows_system_language_and_falls_back_to_english():
    assert i18n.resolve("auto", QLocale(QLocale.Language.German, QLocale.Country.Austria)) == "de"
    assert i18n.resolve("auto", QLocale(QLocale.Language.English)) == "en"
    assert i18n.resolve("auto", QLocale(QLocale.Language.Japanese)) == "en"
    assert i18n.resolve("de", QLocale(QLocale.Language.English)) == "de"


def test_language_choice_is_saved(settings):
    assert i18n.chosen_language() == "auto"
    i18n.set_chosen_language("en")
    assert i18n.chosen_language() == "en"
    i18n.set_chosen_language("klingonisch")
    assert i18n.chosen_language() == "auto"


def test_english_texts_and_plurals(english):
    assert QCoreApplication.translate("TimelinePanel", "▶ Play timeline") == "▶ Play timeline"
    assert QCoreApplication.translate("TimelinePanel", "%n clip(s)", "", 1) == "1 clip"
    assert QCoreApplication.translate("TimelinePanel", "%n clip(s)", "", 3) == "3 clips"
    assert i18n.format_date(date(2026, 10, 21)) == "10/21/2026"


def test_german_texts_and_plurals():
    assert QCoreApplication.translate("TimelinePanel", "▶ Play timeline") == "▶ Timeline abspielen"
    assert QCoreApplication.translate("TimelinePanel", "%n clip(s)", "", 1) == "1 Clip"
    assert QCoreApplication.translate("TimelinePanel", "%n clip(s)", "", 3) == "3 Clips"
    assert i18n.format_date(date(2026, 10, 21)) == "21.10.2026"


def test_german_translation_is_complete():
    unfinished = [
        m.findtext("source") for m in ET.parse(TS).iter("message")
        if m.find("translation").get("type") in ("unfinished", "vanished", "obsolete")
    ]
    assert unfinished == []


@pytest.mark.skipif(not shutil.which("pyside6-lupdate", path=str(Path(sys.executable).parent)),
                    reason="pyside6-lupdate fehlt")
def test_translation_file_matches_code(tmp_path):
    """Neue oder geänderte Texte im Code brauchen eine Übersetzung (siehe docs/release.md)."""
    copy = tmp_path / TS.name
    shutil.copy(TS, copy)
    sources = sorted(str(p) for p in (ROOT / "src").rglob("*.py"))
    subprocess.run([str(Path(sys.executable).parent / "pyside6-lupdate"), *sources, "-ts", str(copy)],
                   check=True, capture_output=True)
    messages = list(ET.parse(copy).iter("message"))
    missing = [m.findtext("source") for m in messages if m.find("translation").get("type")]
    assert missing == []
    assert len(messages) == len(list(ET.parse(TS).iter("message")))
