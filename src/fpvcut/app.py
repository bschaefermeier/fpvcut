"""Einstiegspunkt: ``fpvcut [video]`` bzw. ``python -m fpvcut [video]``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from fpvcut.ui.app_icon import app_icon, set_windows_app_id
from fpvcut.ui.main_window import MainWindow


def self_test(report: Path) -> int:
    """Prüft, ob libmpv, ffmpeg, ffprobe und das Icon gefunden werden (für den .exe-Build).

    Die gepackte .exe hat keine Konsole, deshalb landet das Ergebnis in ``report``.
    """
    from fpvcut import __version__
    from fpvcut.core.ffmpeg_tools import FFmpegNotFound, ffmpeg_version, find_tool
    from fpvcut.ui.app_icon import ICON_SVG
    from fpvcut.ui.player import load_mpv

    lines, ok = [f"FPVCut {__version__}"], True
    mpv, error = load_mpv()
    lines.append(f"libmpv: {'OK' if mpv else 'FEHLER ' + str(error)}")
    ok &= mpv is not None
    for name in ("ffmpeg", "ffprobe"):
        try:
            tool = find_tool(name)
            lines.append(f"{name}: {tool}" + (f" ({ffmpeg_version(tool)})" if name == "ffmpeg" else ""))
        except (FFmpegNotFound, OSError, subprocess.SubprocessError) as exc:
            lines.append(f"{name}: FEHLER {exc}")
            ok = False
    lines.append(f"Icon: {'OK' if ICON_SVG.is_file() else 'FEHLER fehlt ' + str(ICON_SVG)}")
    ok &= ICON_SVG.is_file()
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--selbsttest":
        sys.exit(self_test(Path(sys.argv[2])))
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
