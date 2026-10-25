"""Schüler-Checkpoint (PyTorch) nach ONNX umwandeln, damit FPVCut ihn ohne PyTorch rechnen kann.

Das ONNX-Modell enthält auch das Umrechnen der Bilder: Eingabe sind die 5 Nachbarbilder als
``uint8`` (1, 5, H, W, 3) wie ffmpeg sie liefert und der OSD-Schalter (1,), Ausgabe das gereinigte
mittlere Bild als ``uint8`` (H, W, 3). H und W sind frei (durch 8 teilbar). Gerechnet wird in FP16,
die Datei ist dadurch auch nur halb so groß. Braucht ``uv sync --extra ki``::

    uv run python -m fpvcut.restore.export ..\\fpv-restoration\\checkpoints\\schueler_2h.pt

legt ``schueler_2h.onnx`` daneben und vergleicht es mit dem PyTorch-Modell.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from fpvcut.restore.networks import load_student

OPSET = 18


class _Packed(nn.Module):
    """Schüler mit Umrechnung uint8 ↔ 0…1 und FP16 innen."""

    def __init__(self, student: nn.Module) -> None:
        super().__init__()
        self.student = student.half()

    def forward(self, frames: torch.Tensor, remove_osd: torch.Tensor) -> torch.Tensor:
        x = frames.permute(0, 1, 4, 2, 3).to(torch.float16) / 255
        mid = x[:, x.shape[1] // 2]
        s = self.student
        flag = (remove_osd.to(torch.float16).reshape(1, 1, 1, 1) * torch.ones_like(mid[:, :1]))
        h = s.head(torch.cat([x.flatten(1, 2), flag], dim=1))
        skips = []
        for enc, down in zip(s.enc, s.down):
            h = enc(h)
            skips.append(h)
            h = down(h)
        h = s.bottom(h)
        for up, dec, skip in zip(reversed(s.up), reversed(s.dec), reversed(skips)):
            h = dec(up(h) + skip)
        y = (mid + s.tail(h)).clamp(0, 1)[0]
        return (y.permute(1, 2, 0).float() * 255 + 0.5).to(torch.uint8)


def export(checkpoint: Path, output: Path) -> None:
    student = load_student(checkpoint)
    if student.frames != 5:
        raise ValueError("FPVCut erwartet einen Schüler mit 5 Bildern")
    packed = _Packed(student).eval()
    frames = torch.randint(0, 256, (1, 5, 352, 592, 3), dtype=torch.uint8)
    flag = torch.zeros(1, dtype=torch.float32)
    torch.onnx.export(
        packed, (frames, flag), str(output), input_names=["frames", "remove_osd"], output_names=["restored"],
        dynamic_axes={"frames": {2: "height", 3: "width"}, "restored": {0: "height", 1: "width"}},
        opset_version=OPSET, dynamo=False,
    )


def compare(checkpoint: Path, onnx_path: Path, frames: np.ndarray) -> float:
    """Größte Abweichung (0…255) zwischen ONNX (FP16) und PyTorch (FP32) auf ``frames``."""
    import onnxruntime  # noqa: PLC0415

    student = load_student(checkpoint)
    with torch.inference_mode():
        x = torch.from_numpy(frames).permute(0, 1, 4, 2, 3).float() / 255
        ref = (student(x, 1.0)[0].clamp(0, 1).permute(1, 2, 0).numpy() * 255 + 0.5).astype(np.uint8)
    from fpvcut.restore.onnx_runner import providers  # noqa: PLC0415

    session = onnxruntime.InferenceSession(str(onnx_path), providers=providers())
    out = session.run(None, {"frames": frames, "remove_osd": np.ones(1, np.float32)})[0]
    return float(np.abs(out.astype(int) - ref.astype(int)).max())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Schüler-Checkpoint nach ONNX (FP16)")
    p.add_argument("checkpoint", type=Path)
    p.add_argument("--out", type=Path, help="Standard: gleicher Name mit .onnx")
    args = p.parse_args()
    output = args.out or args.checkpoint.with_suffix(".onnx")
    export(args.checkpoint, output)
    rng = np.random.default_rng(0)
    smooth = rng.integers(0, 256, (1, 5, 44, 74, 3)).astype(np.uint8).repeat(8, 2).repeat(8, 3)
    print(f"{output} ({output.stat().st_size / 1e6:.1f} MB), größte Abweichung zu PyTorch: "
          f"{compare(args.checkpoint, output, smooth):.0f}/255")


if __name__ == "__main__":
    main()
