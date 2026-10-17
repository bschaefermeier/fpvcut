"""Render-Profile: Startwerte für den Render-Dialog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    codec: str  # "h264" oder "hevc"
    quality: int  # CQ (NVENC) bzw. CRF (CPU): kleiner = besser und größer
    audio_bitrate: str
    ten_bit: bool = False
    faststart: bool = True
    hint: str = ""


PROFILES = [
    Profile(
        "original", "Original", "hevc", 18, "320k",
        hint="Wie die Quelle, H.265 in sehr hoher Qualität. Zum Aufheben oder Weiterverarbeiten.",
    ),
    Profile(
        "web", "Web", "h264", 23, "192k",
        hint="H.264 für YouTube, Messenger und Browser: läuft überall, deutlich kleiner.",
    ),
    Profile(
        "archiv", "Archiv (10 Bit)", "hevc", 20, "256k", ten_bit=True,
        hint="H.265 mit 10 Bit, gut für D-Log/Flat-Material und spätere Farbkorrektur.",
    ),
]


def profile_by_key(key: str) -> Profile:
    return next((p for p in PROFILES if p.key == key), PROFILES[1])
