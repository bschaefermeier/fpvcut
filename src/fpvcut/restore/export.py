"""Checkpoint des normalen Modells (PyTorch) nach ONNX umwandeln, damit FPVCut es ohne PyTorch rechnet.

Das ONNX-Modell enthält auch das Umrechnen der Bilder: Eingabe sind die 5 Nachbarbilder als
``uint8`` (1, 5, H, W, 3) wie ffmpeg sie liefert und der OSD-Schalter (1,). Ausgabe ist das
gereinigte mittlere Bild als ``uint8`` (H, W, 3) und für die Vorschau dasselbe als YUV-4:2:0-Ebenen
``y``, ``u``, ``v`` (so rechnet die Grafikkarte auch das um). H und W sind frei (durch 8 teilbar).
Gerechnet wird in FP16, die Datei ist dadurch auch nur halb so groß. Braucht ``uv sync --extra ki``::

    uv run python -m fpvcut.restore.export checkpoint.pt --out models\restore_normal.onnx

vergleicht das Ergebnis außerdem mit dem PyTorch-Modell.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from fpvcut.restore.networks import load_normal

OPSET = 18


class _Packed(nn.Module):
    """Normales Modell mit Umrechnung uint8 ↔ 0…1 und FP16 innen; Ausgabe RGB und YUV-Ebenen."""

    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model.half()

    def forward(self, frames: torch.Tensor, remove_osd: torch.Tensor) -> torch.Tensor:
        x = frames.permute(0, 1, 4, 2, 3).to(torch.float16) / 255
        mid = x[:, x.shape[1] // 2]
        s = self.model
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
        rgb = (mid + s.tail(h)).clamp(0, 1)[0].float() * 255  # (3, H, W) in 0…255
        restored = (rgb.permute(1, 2, 0) + 0.5).to(torch.uint8)
        # Dazu gleich YUV 4:2:0 (BT.601, eingeschränkter Bereich) für die Vorschau, auf der Grafikkarte
        r, g, b = rgb[0], rgb[1], rgb[2]
        luma = 16 + (65.481 * r + 128.553 * g + 24.966 * b) / 255
        small = torch.nn.functional.avg_pool2d(rgb[None], 2)[0]
        r, g, b = small[0], small[1], small[2]
        u = 128 + (-37.797 * r - 74.203 * g + 112.0 * b) / 255
        v = 128 + (112.0 * r - 93.786 * g - 18.214 * b) / 255
        planes = [(p + 0.5).clamp(0, 255).to(torch.uint8) for p in (luma, u, v)]
        return restored, *planes


def export(checkpoint: Path, output: Path) -> None:
    model = load_normal(checkpoint)
    if model.frames != 5:
        raise ValueError("FPVCut erwartet ein Modell mit 5 Bildern")
    packed = _Packed(model).eval()
    frames = torch.randint(0, 256, (1, 5, 352, 592, 3), dtype=torch.uint8)
    flag = torch.zeros(1, dtype=torch.float32)
    torch.onnx.export(
        packed, (frames, flag), str(output), input_names=["frames", "remove_osd"], output_names=["restored", "y", "u", "v"],
        dynamic_axes={"frames": {2: "height", 3: "width"}, "restored": {0: "height", 1: "width"},
                      "y": {0: "height", 1: "width"}, "u": {0: "h2", 1: "w2"}, "v": {0: "h2", 1: "w2"}},
        opset_version=OPSET, dynamo=False,
    )


def compare(checkpoint: Path, onnx_path: Path, frames: np.ndarray) -> float:
    """Größte Abweichung (0…255) zwischen ONNX (FP16) und PyTorch (FP32) auf ``frames``."""
    import onnxruntime  # noqa: PLC0415

    model = load_normal(checkpoint)
    with torch.inference_mode():
        x = torch.from_numpy(frames).permute(0, 1, 4, 2, 3).float() / 255
        ref = (model(x, 1.0)[0].clamp(0, 1).permute(1, 2, 0).numpy() * 255 + 0.5).astype(np.uint8)
    from fpvcut.restore.onnx_runner import providers  # noqa: PLC0415

    session = onnxruntime.InferenceSession(str(onnx_path), providers=providers())
    out = session.run(["restored"], {"frames": frames, "remove_osd": np.ones(1, np.float32)})[0]
    return float(np.abs(out.astype(int) - ref.astype(int)).max())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Normales Modell nach ONNX (FP16)")
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
