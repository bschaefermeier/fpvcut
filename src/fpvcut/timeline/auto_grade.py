"""Automatische Farbkorrektur („Zauberstab“): ein paar Bilder messen, daraus die Regler setzen.

Wie bei Foto-Apps entsteht kein eigener Filter, sondern Werte für die normalen Regler, die man
danach von Hand nachstellen kann. Gemessen wird über mehrere Bilder des Clips gemittelt, damit
die Korrektur zum ganzen Clip passt. Eine gewählte LUT wird vor dem Messen angewandt, denn erst
danach zeigt Log-Material seine eigentlichen Farben.
"""

from __future__ import annotations

import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS
from fpvcut.timeline.grade import NEUTRAL_KELVIN, RANGES, Grade, grade_filters

FRAMES = 5
MID_GRAY = 125.5 / 255  # Mitte des Videobereichs Y 16…235
WIDTH = 192  # klein messen: genügt für Histogramm und Farbstich, ffmpeg ist so schnell

# Verschiebung (V − U, 8-Bit-Stufen) eines mittleren Graus durch colortemperature, gemessen.
TEMPERATURE_SHIFT = [(3000.0, 54.0), (4500.0, 20.0), (6500.0, 0.0), (8000.0, -12.0), (10000.0, -17.0)]


@dataclass
class Stats:
    """Kennzahlen der gemessenen Bilder; Helligkeit als Y/255 wie im ``eq``-Filter."""

    low: float  # 0,5-%-Perzentil
    median: float
    high: float  # 99,5-%-Perzentil
    clipped: float  # Anteil fast weißer Pixel
    u: float  # mittlere Farbabweichung von Grau (U−128, V−128)
    v: float
    chroma: float  # mittlere Farbigkeit


def stats_from_frames(frames: list[bytes]) -> Stats:
    """Wertet Rohbilder im Format yuv444p (8 Bit) aus."""
    hist = [0] * 256
    u_sum = v_sum = chroma_sum = 0.0
    count = 0
    for raw in frames:
        n = len(raw) // 3
        ys, us, vs = raw[:n], raw[n:2 * n], raw[2 * n:3 * n]
        for y in ys:
            hist[y] += 1
        for u, v in zip(us, vs):
            du, dv = u - 128, v - 128
            u_sum += du
            v_sum += dv
            chroma_sum += math.hypot(du, dv)
        count += n
    if not count:
        raise ValueError("keine Bilder gemessen")

    def percentile(p: float) -> float:
        limit, total = p * count, 0
        for value, amount in enumerate(hist):
            total += amount
            if total >= limit:
                return value / 255
        return 1.0

    return Stats(
        low=percentile(0.005), median=percentile(0.5), high=percentile(0.995),
        clipped=sum(hist[232:]) / count, u=u_sum / count, v=v_sum / count, chroma=chroma_sum / count,
    )


def _clamp(name: str, value: float, low: float | None = None, high: float | None = None) -> float:
    lo, hi, _ = RANGES[name]
    return min(max(value, lo if low is None else low), hi if high is None else high)


def _kelvin_for_shift(shift: float) -> float:
    """Farbtemperatur, die ein Grau um ``shift`` (V − U) verschiebt; zwischen Messpunkten linear."""
    points = TEMPERATURE_SHIFT
    if shift >= points[0][1]:
        return points[0][0]
    for (k1, s1), (k2, s2) in zip(points, points[1:]):
        if s2 <= shift <= s1:
            return k1 + (k2 - k1) * (s1 - shift) / (s1 - s2)
    return points[-1][0]


def suggest(stats: Stats, base: Grade | None = None) -> Grade:
    """Korrektur aus den Kennzahlen; LUT, Schärfe und KI-Reinigung von ``base`` bleiben, der Rest wird neu gesetzt."""
    base = base or Grade()
    grade = Grade(lut=base.lut, sharpness=base.sharpness, restore=base.restore, remove_osd=base.remove_osd)

    # Tonwerte spreizen: dunkelste Stellen fast schwarz, hellste fast weiß (Y 20…231, innerhalb
    # des Videobereichs). eq rechnet ((x − 0,5) · Kontrast + 0,5 + Helligkeit) ^ (1/Gamma).
    span = max(stats.high - stats.low, 0.05)
    contrast = _clamp("contrast", (211 / 255) / span, 0.8)
    middle = (stats.low + stats.high) / 2
    brightness = _clamp("brightness", MID_GRAY - (contrast * (middle - 0.5) + 0.5), -0.25, 0.25)
    grade.contrast, grade.brightness = round(contrast, 3), round(brightness, 3)

    # Mitten Richtung Mittelgrau ziehen, nur halb, damit dunkle oder helle Stimmungen erhalten bleiben.
    median = min(max(contrast * (stats.median - 0.5) + 0.5 + brightness, 0.05), 0.95)
    gamma = math.log(median) / math.log(MID_GRAY)
    grade.gamma = round(_clamp("gamma", 1 + (gamma - 1) * 0.5, 0.85, 1.3), 3)

    # Lichter etwas zurückholen, sobald mehr als 1 % fast weiß ist. Nur maßvoll: wirklich
    # ausgefressenes Weiß enthält keine Zeichnung mehr und würde sonst grau.
    if stats.clipped > 0.01:
        grade.highlights = round(-min(0.4, stats.clipped * 4), 2)
    # Viel sehr Dunkles: Schatten etwas aufhellen.
    if stats.low < 30 / 255 and median < 0.35:
        grade.shadows = round(min(0.5, (0.35 - median) * 3), 2)

    # Weißabgleich nach „Gray World“: der Bildschnitt soll neutral sein. Nur zu 60 %, denn ein
    # blauer Himmel oder ein Sonnenuntergang ist kein Farbstich.
    cast = stats.v - stats.u
    if abs(cast) >= 2:
        kelvin = _kelvin_for_shift(-0.6 * cast)
        grade.temperature = round(min(max(kelvin, 4500.0), 9000.0) / 50) * 50
    else:
        grade.temperature = NEUTRAL_KELVIN

    # Blasse Bilder über die Dynamik beleben (schont kräftige Farben und Haut).
    target = 22.0
    if stats.chroma < target:
        grade.vibrance = round(min(0.6, (target - stats.chroma) / target * 1.2), 2)
    return grade


def frame_times(src_in: float, src_out: float, count: int = FRAMES) -> list[float]:
    """Gleichmäßig verteilte Zeitpunkte im Clip, nicht ganz am Rand (Schnitte, Schwarzbilder)."""
    duration = max(src_out - src_in, 0.0)
    return [src_in + duration * (i + 0.5) / count for i in range(count)]


def grab_frame(ffmpeg: Path | str, path: Path | str, t: float, lut: str | None = None) -> bytes:
    """Ein verkleinertes Bild als yuv444p, mit LUT wie in Vorschau und Export."""
    vf = ",".join([f"scale={WIDTH}:-2:flags=area", *grade_filters(Grade(lut=lut)), "format=yuv444p"])
    result = subprocess.run(
        [str(ffmpeg), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-an",
         "-vf", vf, "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"],
        capture_output=True, check=True, timeout=60, creationflags=CREATE_FLAGS,
    )
    return result.stdout


def measure(ffmpeg: Path | str, path: Path | str, src_in: float, src_out: float, lut: str | None = None) -> Stats:
    """Misst einen Clip; die Bilder werden parallel geholt."""
    times = frame_times(src_in, src_out)
    with ThreadPoolExecutor(max_workers=len(times)) as pool:
        frames = [f for f in pool.map(lambda t: grab_frame(ffmpeg, path, t, lut), times) if f]
    return stats_from_frames(frames)
