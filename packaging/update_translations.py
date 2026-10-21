"""Übersetzungen mit dem Code abgleichen und die .qm-Dateien neu erzeugen.

Aufruf: ``uv run python packaging/update_translations.py``

Neue Texte landen als „unfinished“ in ``fpvcut_<sprache>.ts``; nach dem Übersetzen (z. B. mit
``uv run pyside6-linguist``) das Skript noch einmal starten. Die englische Datei enthält nur die
Mehrzahlformen, die Texte selbst stehen auf Englisch im Code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "src" / "fpvcut" / "resources" / "i18n"
TOOLS = Path(sys.executable).parent


def sources() -> list[str]:
    return sorted(str(p) for p in (ROOT / "src").rglob("*.py"))


def main() -> None:
    for ts in sorted(I18N.glob("fpvcut_*.ts")):
        extra = ["-pluralonly"] if ts.stem == "fpvcut_en" else []
        subprocess.run([str(TOOLS / "pyside6-lupdate"), *sources(), *extra, "-ts", str(ts)], check=True)
        subprocess.run([str(TOOLS / "pyside6-lrelease"), str(ts)], check=True)


if __name__ == "__main__":
    main()
