"""Einstiegspunkt: ``fpvcut [video]`` bzw. ``python -m fpvcut [video]``."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from fpvcut.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("FPVCut")
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        video = Path(sys.argv[1])
        # Warten, bis mpv im ersten Event-Loop-Durchlauf gestartet ist.
        QTimer.singleShot(200, lambda: window.open_video(video))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
