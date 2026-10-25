"""KI-Bildreinigung für analoges FPV-Bild: Modelle aus fpv-restoration (Lehrer und Schüler).

Der Schüler (klein, schnell) läuft live in der Timeline-Vorschau, der Lehrer (Swin-UNet, deutlich
besser, aber langsam) auf Wunsch beim Rendern. Beides vor der Farbkorrektur. Braucht PyTorch mit
CUDA (``uv sync --extra ki``) und die beiden Checkpoints; ohne sie fehlt nur diese Funktion.

Dieses Modul lädt PyTorch nicht selbst, damit FPVCut ohne es startet; das passiert erst in
:mod:`engine` beim ersten Gebrauch.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from PySide6.QtCore import QSettings

from fpvcut.core.paths import is_frozen
from fpvcut.i18n import translate

KINDS = ("student", "teacher")
DEFAULT_NAMES = {"student": "schueler_2h.pt", "teacher": "lehrer_cluster.pt"}

_models = None  # engine.Models, einmal je Programmlauf


def _settings() -> QSettings:
    return QSettings("FPVCut", "FPVCut")


def default_dirs() -> list[Path]:
    """Hier wird nach den Checkpoints gesucht, wenn keiner eingestellt ist."""
    dirs = [Path(env)] if (env := os.environ.get("FPVCUT_MODELS")) else []
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
    return next((d / DEFAULT_NAMES[kind] for d in default_dirs() if (d / DEFAULT_NAMES[kind]).is_file()), None)


def set_model_path(kind: str, path: Path | None) -> None:
    global _models
    if path is None:
        _settings().remove(f"restore/{kind}")
    else:
        _settings().setValue(f"restore/{kind}", str(path))
    _models = None  # beim nächsten Gebrauch neu laden


def torch_installed() -> bool:
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("einops") is not None


def problem(kind: str = "student") -> str | None:
    """Warum die Reinigung mit diesem Modell gerade nicht geht, sonst None."""
    if not torch_installed():
        return translate("restore", "PyTorch is not installed (uv sync --extra ki).")
    if model_path(kind) is None:
        name = translate("restore", "student model") if kind == "student" else translate("restore", "teacher model")
        return translate("restore", "The {model} was not found (File → AI models …).").format(model=name)
    return None


def models():
    """Gemeinsame :class:`engine.Models` für Vorschau und Render (lädt PyTorch)."""
    global _models
    if _models is None:
        from fpvcut.restore.engine import Models  # noqa: PLC0415  (PyTorch erst jetzt laden)

        _models = Models(model_path("student"), model_path("teacher"))
    return _models


def gpu_name() -> str | None:
    """Name der Grafikkarte, None ohne CUDA (lädt PyTorch)."""
    import torch  # noqa: PLC0415

    return torch.cuda.get_device_name() if torch.cuda.is_available() else None
