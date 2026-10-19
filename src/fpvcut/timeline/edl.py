"""Timeline als mpv-EDL abspielen, ohne vorher zu rendern.

Die EDL hat zwei Streams: den vorab gemischten Ton (siehe :mod:`fpvcut.timeline.preview_audio`)
und die Videospur aus den Clips. Der Ton steht vorn, damit er immer ``aid1`` ist; die
Tonspuren der Clips selbst folgen mit der Videospur und bleiben ungenutzt.

Das Bild läuft bewusst nicht durch ``lavfi-complex``: Wechselt zwischen zwei Clips das
Videoformat (Codec, Auflösung, Bildrate), baut mpv den ganzen Filtergraphen neu auf, und die
Wiedergabe bleibt an dieser Stelle stehen. Die Farbkorrektur läuft deshalb als normaler
Videofilter (``vf``), den mpv bei einem Formatwechsel problemlos neu startet.
"""

from __future__ import annotations

from pathlib import Path

from fpvcut.timeline.grade import grade_filters
from fpvcut.timeline.model import Timeline


PREVIEW_SCALE = "scale=w=-2:h='min(ih,1080)':flags=bilinear:eval=frame"


def _quote(path: str) -> str:
    # %Länge% erlaubt beliebige Zeichen (Kommas, Semikolons) im Pfad; mpv zählt Bytes.
    return f"%{len(path.encode('utf-8'))}%{path}"


def build_edl(timeline: Timeline, audio: Path | str | None = None) -> str:
    """``edl://``-URL für mpv. Fehlende Clips müssen vorher geprüft werden."""
    parts = []
    if audio is not None:
        parts += ["!new_stream", f"{_quote(str(audio))},0.000,{timeline.duration:.3f}"]
    parts.append("!new_stream")
    for clip in timeline.clips:
        parts.append(f"{_quote(str(clip.path))},{clip.src_in:.3f},{clip.duration:.3f}")
    return "edl://" + ";".join(parts)


def build_vf(timeline: Timeline) -> str:
    """Videofilter für mpvs ``vf``-Option mit der Farbkorrektur aller Clips, leer ohne Korrektur."""
    video = []
    for clip, begin in zip(timeline.clips, timeline.starts()):
        # Zeitstempel der EDL sind Timeline-Zeit: Korrektur nur im Zeitraum dieses Clips.
        video += grade_filters(clip.grade, enable=f"gte(t,{begin:.3f})*lt(t,{begin + clip.duration:.3f})")
    # Die Filter laufen auf der CPU; 4K-Bilder vorher auf höchstens 1080 Zeilen verkleinern, das
    # macht sie etwa dreimal so schnell. Für die Vorschau reicht das, der Export nutzt volle Größe.
    # ``eval=frame``: mpv baut den Filter bei einem Wechsel der Auflösung nicht neu auf; so passt
    # sich die Größe pro Bild an, statt Clips anderer Auflösung zu verzerren (oder abzustürzen).
    return f"lavfi=[{PREVIEW_SCALE},{','.join(video)}]" if video else ""
