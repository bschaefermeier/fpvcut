"""Lehrer (und Schüler aus dem .pt-Checkpoint) über PyTorch auf der Grafikkarte, in bf16.

Braucht ``uv sync --extra ki``. Der Schüler läuft normalerweise als ONNX (:mod:`onnx_runner`).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from fpvcut.restore.networks import load_student, load_teacher


class TorchRunner:
    def __init__(self, model: torch.nn.Module, all_frames: bool) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = model.to(self.device)
        self.all_frames = all_frames

    def run(self, window: list[np.ndarray], remove_osd: bool) -> np.ndarray:
        x = torch.from_numpy(np.stack(window)).to(self.device)
        x = x.permute(0, 3, 1, 2).float().div_(255).unsqueeze(0)
        with torch.inference_mode():
            with torch.autocast(self.device.type, dtype=torch.bfloat16):
                y = self.model(x, 1.0 if remove_osd else 0.0)[0]
            y = y.float().clamp_(0, 1).mul_(255).add_(0.5).to(torch.uint8)
            return y.movedim(-3, -1).contiguous().cpu().numpy()

    def close(self) -> None:
        del self.model
        if self.device.type == "cuda":
            torch.cuda.empty_cache()


def load(kind: str, path: Path) -> TorchRunner:
    if kind == "teacher":
        return TorchRunner(load_teacher(path), all_frames=True)
    return TorchRunner(load_student(path), all_frames=False)


def gpu_name() -> str | None:
    return torch.cuda.get_device_name() if torch.cuda.is_available() else None
