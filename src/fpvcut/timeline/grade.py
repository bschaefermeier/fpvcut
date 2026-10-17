"""Farbkorrektur eines Timeline-Clips und ihre Übersetzung in ffmpeg-Filter.

Dieselben Filter laufen in der Vorschau (mpv ``lavfi-complex``, per ``enable`` auf den
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
}


@dataclass
class Grade:
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    temperature: float = NEUTRAL_KELVIN
    lut: str | None = None  # .cube-Datei, z. B. für D-Log oder Flat-Profile

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
    eq = {k: getattr(grade, k) for k in ("brightness", "contrast", "saturation", "gamma")}
    if any(abs(v - RANGES[k][2]) > 1e-4 for k, v in eq.items()):
        result.append("eq=" + ":".join(f"{k}={v:.3f}" for k, v in eq.items()) + suffix)
    return result
