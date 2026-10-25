"""KI-Bildreinigung für analoges FPV-Bild: zwei Modelle aus fpv-restoration, „normal“ und „hohe Qualität“.

Das normale Modell (klein, schnell; in fpv-restoration der Schüler) läuft live in der
Timeline-Vorschau, das hoher Qualität (Swin-UNet, der Lehrer; deutlich besser, aber langsam) auf
Wunsch beim Rendern. Beides vor der Farbkorrektur.

Das normale Modell liegt als ``models/restore_normal.onnx`` bei FPVCut (auch im Windows-Paket) und
läuft über ONNX Runtime. Das hoher Qualität ist zu groß fürs Repo (238 MB) und braucht PyTorch mit
CUDA (``uv sync --extra ki``). Fehlt etwas, fehlt nur die jeweilige Funktion. Dieses Modul lädt
keins von beiden, damit FPVCut ohne Verzögerung startet.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from PySide6.QtCore import QSettings

from fpvcut.core.paths import app_dir, is_frozen
from fpvcut.i18n import translate

KINDS = ("normal", "high_quality")
# Gesucht wird nach diesen Namen (zuerst die FPVCut-Namen, dann die aus fpv-restoration)
DEFAULT_NAMES = {
    "normal": ["restore_normal.onnx", "schueler_2h.onnx", "schueler_2h.pt"],
    "high_quality": ["restore_high_quality.pt", "lehrer_cluster.pt"],
}

_models = None  # engine.Models, einmal je Programmlauf


def _settings() -> QSettings:
    return QSettings("FPVCut", "FPVCut")


def default_dirs() -> list[Path]:
    """Hier wird nach den Checkpoints gesucht, wenn keiner eingestellt ist."""
    dirs = [Path(env)] if (env := os.environ.get("FPVCUT_MODELS")) else []
    dirs.append(app_dir("models"))  # mitgeliefert (Repo bzw. Windows-Paket)
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "FPVCut" / "modelle")
    if not is_frozen():  # aus dem Quellcode gestartet: fpv-restoration liegt oft gleich daneben
        dirs.append(Path(__file__).resolve().parents[3].parent / "fpv-restoration" / "checkpoints")
    return dirs


def model_path(kind: str) -> Path | None:
    """Eingestellter Checkpoint, sonst der erste passend benannte in :func:`default_dirs`."""
    chosen = _settings().value(f"restore/{kind}")
    if chosen:
        return Path(chosen) if Path(chosen).is_file() else None
    candidates = (d / name for d in default_dirs() for name in DEFAULT_NAMES[kind])
    return next((p for p in candidates if p.is_file()), None)


def set_model_path(kind: str, path: Path | None) -> None:
    global _models
    if path is None:
        _settings().remove(f"restore/{kind}")
    else:
        _settings().setValue(f"restore/{kind}", str(path))
    _models = None  # beim nächsten Gebrauch neu laden


def torch_installed() -> bool:
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("einops") is not None


def onnx_installed() -> bool:
    return importlib.util.find_spec("onnxruntime") is not None


def problem(kind: str = "normal") -> str | None:
    """Warum die Reinigung mit diesem Modell gerade nicht geht, sonst None."""
    path = model_path(kind)
    if path is None:
        name = translate("restore", "normal model") if kind == "normal" else translate("restore", "high-quality model")
        return translate("restore", "The {model} was not found (File → AI models …).").format(model=name)
    if path.suffix.lower() == ".onnx":
        if not onnx_installed():
            return translate("restore", "ONNX Runtime is not installed.")
    elif not torch_installed():
        return translate("restore", "PyTorch is not installed (uv sync --extra ki).")
    return None


def models():
    """Gemeinsame :class:`engine.Models` für Vorschau und Render."""
    global _models
    if _models is None:
        from fpvcut.restore.engine import Models  # noqa: PLC0415

        _models = Models(model_path("normal"), model_path("high_quality"))
    return _models
