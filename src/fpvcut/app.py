"""Einstiegspunkt: ``fpvcut [video]`` bzw. ``python -m fpvcut [video]``."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from fpvcut.ui.app_icon import app_icon, set_windows_app_id
from fpvcut.ui.main_window import MainWindow


def main() -> None:
    # Der eingebettete mpv-Player braucht ein natives Fenster. Ohne dieses Attribut macht Qt auch
    # die Nachbar-Widgets (z. B. die Bibliothek) nativ, was u. a. Kontextmenüs stört.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("FPVCut")
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        video = Path(sys.argv[1])
        # Warten, bis mpv im ersten Event-Loop-Durchlauf gestartet ist.
        QTimer.singleShot(200, lambda: window.open_video(video))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
