"""Render-Profile: Startwerte für den Render-Dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP


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
        "original", QT_TRANSLATE_NOOP("profiles", "Original"), "hevc", 18, "320k",
        hint=QT_TRANSLATE_NOOP("profiles", "Like the source, H.265 in very high quality. For keeping or further editing."),
    ),
    Profile(
        "web", QT_TRANSLATE_NOOP("profiles", "Web"), "h264", 23, "192k",
        hint=QT_TRANSLATE_NOOP("profiles", "H.264 for YouTube, messengers and browsers: plays everywhere, much smaller."),
    ),
    Profile(
        "archiv", QT_TRANSLATE_NOOP("profiles", "Archive (10 bit)"), "hevc", 20, "256k", ten_bit=True,
        hint=QT_TRANSLATE_NOOP("profiles", "H.265 with 10 bit, good for D-Log/flat footage and later color grading."),
    ),
]


def profile_by_key(key: str) -> Profile:
    return next((p for p in PROFILES if p.key == key), PROFILES[1])
