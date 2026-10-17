"""Timeline als mpv-EDL abspielen, ohne vorher zu rendern.

Die Videospur und die Musik werden als zwei Streams in eine EDL geschrieben; ein
``lavfi-complex``-Filter mischt Originalton und Musik mit Lautstärke und Blenden.
"""

from __future__ import annotations

from fpvcut.timeline.model import Timeline


def _quote(path: str) -> str:
    # %Länge% erlaubt beliebige Zeichen (Kommas, Semikolons) im Pfad; mpv zählt Bytes.
    return f"%{len(path.encode('utf-8'))}%{path}"


def build_edl(timeline: Timeline) -> str:
    """``edl://``-URL für mpv. Fehlende Clips müssen vorher geprüft werden."""
    parts = ["!new_stream"]
    for clip in timeline.clips:
        parts.append(f"{_quote(str(clip.path))},{clip.src_in:.3f},{clip.duration:.3f}")
    if timeline.music is not None and timeline.music_length() > 0:
        parts.append("!new_stream")
        parts.append(f"{_quote(timeline.music.path)},{timeline.music.src_in:.3f},{timeline.music_length():.3f}")
    return "edl://" + ";".join(parts)


def build_lavfi(timeline: Timeline) -> str:
    """Filtergraph für mpvs ``lavfi-complex``: Originalton und Musik mischen."""
    original = f"[aid1]volume={timeline.original_volume:.2f}"
    music = timeline.music
    length = timeline.music_length()
    if music is None or length <= 0:
        return f"[vid1]null[vo];{original}[ao]"
    filters = [f"volume={music.volume:.2f}"]
    if music.fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={min(music.fade_in, length):.2f}")
    if music.fade_out > 0:
        fade = min(music.fade_out, length)
        filters.append(f"afade=t=out:st={length - fade:.3f}:d={fade:.2f}")
    return (
        f"[vid1]null[vo];{original}[a1];[aid2]{','.join(filters)}[a2];"
        "[a1][a2]amix=inputs=2:normalize=0:duration=first[ao]"
    )
