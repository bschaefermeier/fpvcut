"""Timeline als mpv-EDL abspielen, ohne vorher zu rendern.

Die Videospur und die Musik werden als zwei Streams in eine EDL geschrieben; ein
``lavfi-complex``-Filter mischt Originalton und Musik mit Lautstärke und Blenden.
"""

from __future__ import annotations

from fpvcut.timeline.model import Timeline

SAMPLE_RATE = 48000


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


def build_lavfi(timeline: Timeline, start: float = 0.0) -> str:
    """Filtergraph für mpvs ``lavfi-complex``: Originalton und Musik mischen.

    Clips ohne Tonspur hinterlassen Lücken im Originalton. ``aresample=async=1`` füllt sie
    anhand der Zeitstempel mit Stille, sonst rutscht der Ton der folgenden Clips nach vorn.
    ``first_pts`` muss dabei die Startposition sein, sonst fehlt die Stille, wenn die
    Wiedergabe in einem stummen Clip beginnt. Nach einem Sprung stimmt das nicht mehr,
    deshalb wird die Vorschau für jeden Sprung mit neuer Startposition neu geladen.
    Hat kein Clip Ton, ist die Musik die erste (und einzige) Audiospur. Hat ab ``start``
    kein Clip mehr Ton, bleibt der Originalton weg: mpv liefert sonst Ton aus einem
    früheren Clip.
    """
    original = timeline.has_original_audio
    original_ahead = any(
        clip.has_audio and begin + clip.duration > start + 0.01
        for clip, begin in zip(timeline.clips, timeline.starts())
    )
    music = timeline.music
    length = timeline.music_length()
    has_music = music is not None and length > 0
    # Beide Spuren an den Zeitstempeln ausrichten; mpv liefert nach dem Sprung etwas Vorlauf.
    align = f"aresample={SAMPLE_RATE}:async=1:first_pts={round(max(start, 0.0) * SAMPLE_RATE)}"
    parts = ["[vid1]null[vo]"]
    labels = []
    if original_ahead:
        parts.append(f"[aid1]{align},volume={timeline.original_volume:.2f}[a1]")
        labels.append("[a1]")
    if has_music:
        filters = [align, f"volume={music.volume:.2f}"]
        if music.fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={min(music.fade_in, length):.2f}")
        if music.fade_out > 0:
            fade = min(music.fade_out, length)
            filters.append(f"afade=t=out:st={length - fade:.3f}:d={fade:.2f}")
        parts.append(f"[aid{2 if original else 1}]{','.join(filters)}[a2]")
        labels.append("[a2]")
    if len(labels) == 2:
        parts.append("[a1][a2]amix=inputs=2:normalize=0:duration=longest[ao]")
    elif labels:
        parts[-1] = parts[-1][: -len(labels[0])] + "[ao]"
    return ";".join(parts)
