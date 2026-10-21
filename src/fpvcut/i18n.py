"""Sprache der Oberfläche: Englisch im Code, weitere Sprachen als Qt-Übersetzungen.

Die Texte stehen auf Englisch im Code (``self.tr(...)`` bzw. ``translate(...)``). Beim Start lädt
:func:`install` die Übersetzung zur gewählten Sprache; „auto“ folgt der Systemsprache und fällt auf
Englisch zurück. Die Wahl im Menü gilt ab dem nächsten Start.

Übersetzungen aktualisieren: ``uv run python packaging/update_translations.py`` (siehe README).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QDate, QLibraryInfo, QLocale, QSettings, QTranslator

I18N_DIR = Path(__file__).resolve().parent / "resources" / "i18n"
# Sprachcode → Name in der Sprache selbst (so steht er auch im Menü)
LANGUAGES = {"en": "English", "de": "Deutsch"}
AUTO = "auto"
_SETTING = "language"

translate = QCoreApplication.translate
_installed: list[QTranslator] = []  # Referenzen halten, sonst räumt Python sie weg


def _settings() -> QSettings:
    return QSettings("FPVCut", "FPVCut")


def chosen_language() -> str:
    """Gespeicherte Wahl: ein Sprachcode oder ``auto``."""
    value = _settings().value(_SETTING, AUTO)
    return value if value in LANGUAGES or value == AUTO else AUTO


def set_chosen_language(language: str) -> None:
    _settings().setValue(_SETTING, language)


def resolve(language: str, system: QLocale | None = None) -> str:
    """``auto`` → Systemsprache, wenn es dafür eine Übersetzung gibt, sonst Englisch."""
    if language in LANGUAGES:
        return language
    for name in (system or QLocale.system()).uiLanguages():
        code = name.replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return "en"


def install(app: QCoreApplication, language: str | None = None) -> str:
    """Übersetzungen laden (eigene und die von Qt für Standarddialoge); gibt die Sprache zurück."""
    for translator in _installed:
        app.removeTranslator(translator)
    _installed.clear()
    code = resolve(language or chosen_language())
    # Auch Englisch hat eine Datei: sie liefert die Mehrzahlformen („1 clip“, „2 clips“).
    sources = [(f"fpvcut_{code}", I18N_DIR)]
    if code != "en":
        sources.append((f"qtbase_{code}", Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))))
    for name, folder in sources:
        translator = QTranslator(app)
        if translator.load(name, str(folder)):
            app.installTranslator(translator)
            _installed.append(translator)
    QLocale.setDefault(QLocale(code))
    return code


def format_date(day: date) -> str:
    """Datum im Format der Sprache, mit vierstelligem Jahr (z. B. 21.10.2026 bzw. 10/21/2026)."""
    locale = QLocale()
    pattern = locale.dateFormat(QLocale.FormatType.ShortFormat)
    if "yyyy" not in pattern:
        pattern = pattern.replace("yy", "yyyy")
    return locale.toString(QDate(day.year, day.month, day.day), pattern)
