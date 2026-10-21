"""Tests laufen mit der deutschen Übersetzung: so prüfen die Texte-Asserts zugleich die .ts-Datei.

Die englischen Originaltexte und die Sprachwahl prüft ``test_i18n.py``.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fpvcut import i18n  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def german_ui():
    app = QApplication.instance() or QApplication([])
    i18n.install(app, "de")
    yield app
