"""Farbkorrektur eines Timeline-Clips und ihre Übersetzung in ffmpeg-Filter.

Dazu gehört auch der Schalter für die KI-Bildreinigung; sie ist kein ffmpeg-Filter, sondern
ersetzt vorher das Bild des Clips (siehe :mod:`fpvcut.restore`).

Dieselben Filter laufen in der Vorschau (mpv ``vf``, per ``enable`` auf den
Zeitraum des Clips beschränkt) und beim Rendern (in der Filterkette des Clips). So sieht
der Export aus wie die Vorschau.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

NEUTRAL_KELVIN = 6500.0

# Regler: Name → (Minimum, Maximum, neutraler Wert)
RANGES = {
    "brightness": (-0.3, 0.3, 0.0),
    "contrast": (0.5, 1.5, 1.0),
    "saturation": (0.0, 2.0, 1.0),
    "gamma": (0.5, 2.0, 1.0),
    "temperature": (3000.0, 10000.0, NEUTRAL_KELVIN),
    "shadows": (-1.0, 1.0, 0.0),  # dunkle Töne aufhellen (+) oder absenken (−)
    "highlights": (-1.0, 1.0, 0.0),  # helle Töne aufhellen (+) oder zurückholen (−)
    "vibrance": (-1.0, 1.0, 0.0),  # Dynamik: hebt blasse Farben stärker an als kräftige
    "sharpness": (-1.0, 1.5, 0.0),  # Stärke der Unschärfemaske: negativ weichzeichnen
}

# Schatten/Lichter verbiegen die Helligkeitskurve höchstens um diesen Anteil des Bereichs;
# so bleibt sie auch bei vollem Ausschlag monoton (keine Tonwertumkehr).
TONE_AMOUNT = 0.12


@dataclass
class Grade:
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    temperature: float = NEUTRAL_KELVIN
    shadows: float = 0.0
    highlights: float = 0.0
    vibrance: float = 0.0
    sharpness: float = 0.0
    lut: str | None = None  # .cube-Datei, z. B. für D-Log oder Flat-Profile
    # KI-Bildreinigung vor allen Farbfiltern (siehe fpvcut.restore), kein ffmpeg-Filter
    restore: bool = False
    remove_osd: bool = False  # dabei das OSD entfernen statt erhalten

    @classmethod
    def from_dict(cls, data: dict | None) -> Grade:
        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict | None:
        """``None`` für eine neutrale Korrektur, damit die Projektdatei schlank bleibt."""
        return None if self.is_neutral else asdict(self)

    @property
    def is_neutral(self) -> bool:
        return self == Grade()


def _escape_path(path: str) -> str:
    """Pfad für eine Filteroption in ``'…'``: ``/`` statt ``\\``, Doppelpunkt maskiert.

    Ein Apostroph beendet das Zitat, wird maskiert eingefügt und das Zitat neu geöffnet.
    """
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "'\\\\\\''")


def _tone_curve(shadows: float, highlights: float) -> str:
    """``lutyuv``-Ausdruck für die Helligkeit: Schatten wirken um 1/3, Lichter um 2/3 des Bereichs."""
    x = "clip((val-minval)/(maxval-minval),0,1)"
    bumps = []
    if abs(shadows) > 1e-4:
        bumps.append(f"{shadows * 6.75:.4f}*{x}*(1-{x})*(1-{x})")
    if abs(highlights) > 1e-4:
        bumps.append(f"{highlights * 6.75:.4f}*{x}*{x}*(1-{x})")
    # Ergebnis auf den vollen Wertebereich begrenzen (255/235 von maxval), sonst läuft er über.
    return f"lutyuv=y='clip(val+(maxval-minval)*{TONE_AMOUNT}*({'+'.join(bumps)}),0,maxval*255/235)'"


def grade_filters(grade: Grade | dict | None, enable: str | None = None) -> list[str]:
    """ffmpeg-Filter für eine Korrektur; mit ``enable`` nur in diesem Zeitraum aktiv."""
    if not isinstance(grade, Grade):
        grade = Grade.from_dict(grade)
    suffix = f":enable='{enable}'" if enable else ""
    result = []
    if grade.lut:  # LUT zuerst: sie wandelt Log-Material in normale Farben, danach wird justiert
        result.append(f"lut3d=file='{_escape_path(grade.lut)}':interp=tetrahedral{suffix}")
    if abs(grade.temperature - NEUTRAL_KELVIN) >= 1:
        result.append(f"colortemperature=temperature={grade.temperature:.0f}:pl=1{suffix}")
    if abs(grade.vibrance) > 1e-4:  # neben der Farbtemperatur: beide arbeiten in RGB
        result.append(f"vibrance=intensity={grade.vibrance:.3f}{suffix}")
    eq = {k: getattr(grade, k) for k in ("brightness", "contrast", "saturation", "gamma")}
    if any(abs(v - RANGES[k][2]) > 1e-4 for k, v in eq.items()):
        result.append("eq=" + ":".join(f"{k}={v:.3f}" for k, v in eq.items()) + suffix)
    if abs(grade.shadows) > 1e-4 or abs(grade.highlights) > 1e-4:
        result.append(_tone_curve(grade.shadows, grade.highlights) + suffix)
    if abs(grade.sharpness) > 1e-4:  # zuletzt, damit sie auf den fertigen Farben arbeitet
        result.append(f"unsharp=lx=5:ly=5:la={grade.sharpness:.3f}{suffix}")
    return result
