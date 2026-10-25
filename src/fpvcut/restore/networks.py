"""Die beiden Reinigungsmodelle aus fpv-restoration: „hohe Qualität“ (Swin-UNet) und „normal“ (kleines U-Net).

In fpv-restoration heißen sie Lehrer und Schüler: Das normale Modell ist per Destillation aus dem
großen entstanden. Beide bekommen mehrere aufeinanderfolgende Bilder (B, T, 3, H, W) in 0…1 und
einen OSD-Schalter (0 = OSD erhalten, 1 = entfernen). Das große Modell gibt alle T = 5 Bilder
gereinigt aus, das normale nur das mittlere. Übernommen aus ``fpv_restoration/student.py`` und
``swin_common.py``; die Checkpoints müssen zu diesem Aufbau passen. Braucht PyTorch
(``uv sync --extra ki``).
"""

from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn

NORMAL_CONFIG = {"frames": 5, "widths": [32, 64, 96, 128], "blocks": 2}
HIGH_QUALITY_WINDOW = 5


class ResBlock(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.body = nn.Sequential(nn.Conv2d(channels, channels, 3, padding=1), nn.ReLU(inplace=True),
                                  nn.Conv2d(channels, channels, 3, padding=1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.body(x)


class NormalUNet(nn.Module):
    """Nachbarbilder als Farbkanäle übereinander plus OSD-Schalter; Ausgabe: Korrektur fürs mittlere Bild.

    Das Bild wird dreimal halbiert, Breite und Höhe müssen durch 8 teilbar sein.
    """

    def __init__(self, frames: int = 5, widths: list[int] = NORMAL_CONFIG["widths"], blocks: int = 2) -> None:
        super().__init__()
        self.frames = frames
        w = list(widths)
        self.head = nn.Conv2d(3 * frames + 1, w[0], 3, padding=1)
        self.enc = nn.ModuleList(nn.Sequential(*(ResBlock(c) for _ in range(blocks))) for c in w[:-1])
        self.down = nn.ModuleList(nn.Conv2d(a, b, 3, stride=2, padding=1) for a, b in zip(w, w[1:]))
        self.bottom = nn.Sequential(*(ResBlock(w[-1]) for _ in range(blocks)))
        self.up = nn.ModuleList(nn.Sequential(nn.Conv2d(b, a * 4, 1), nn.PixelShuffle(2)) for a, b in zip(w, w[1:]))
        self.dec = nn.ModuleList(nn.Sequential(*(ResBlock(c) for _ in range(blocks))) for c in w[:-1])
        self.tail = nn.Conv2d(w[0], 3, 3, padding=1)

    def forward(self, x: torch.Tensor, remove_osd: float = 0.0) -> torch.Tensor:
        """``x``: (B, T, 3, H, W) mit T ≥ ``frames`` (genommen werden die mittleren). Ausgabe (B, 3, H, W)."""
        first = (x.shape[1] - self.frames) // 2
        x = x[:, first:first + self.frames]
        mid = x[:, self.frames // 2]
        flag = torch.full((x.shape[0], 1, x.shape[3], x.shape[4]), float(remove_osd), dtype=x.dtype, device=x.device)
        h = self.head(torch.cat([x.flatten(1, 2), flag], dim=1))
        skips = []
        for enc, down in zip(self.enc, self.down):
            h = enc(h)
            skips.append(h)
            h = down(h)
        h = self.bottom(h)
        for up, dec, skip in zip(reversed(self.up), reversed(self.dec), reversed(skips)):
            h = dec(up(h) + skip)
        return mid + self.tail(h)


class HighQualitySwin(nn.Module):
    """Swin-UNet mit OSD-Schalter als viertem Eingangskanal. Ausgabe wie die Eingabe: alle Bilder."""

    frames = HIGH_QUALITY_WINDOW

    def __init__(self) -> None:
        super().__init__()
        from fpvcut.restore.swin import VideoSwinEncoderDecoder  # noqa: PLC0415  (braucht einops)

        base = VideoSwinEncoderDecoder(use_checkpoint=False, depths=[2, 2, 6, 2], embed_dim=96)
        old = base.conv_input
        base.conv_input = nn.Conv3d(4, old.out_channels, old.kernel_size, old.stride, old.padding)
        self.base = base

    def forward(self, x: torch.Tensor, remove_osd: float = 0.0) -> torch.Tensor:
        flag = torch.full((x.shape[0], x.shape[1], 1, x.shape[3], x.shape[4]), float(remove_osd),
                          dtype=x.dtype, device=x.device)
        feats, residual = self.base.forward_encoding(torch.cat([x, flag], dim=2))
        return x + self.base.forward_decoding(feats, residual)


def _state(path: Path) -> dict:
    state = torch.load(path, map_location="cpu", weights_only=True)
    return state if isinstance(state, dict) else {}


def load_normal(path: Path) -> NormalUNet:
    """Normales Modell aus einem Checkpoint von ``distill.py`` (der Aufbau steht mit darin)."""
    state = _state(path)
    if "model" not in state:
        raise ValueError("kein Checkpoint des normalen Modells")
    model = NormalUNet(**state.get("config", NORMAL_CONFIG))
    model.load_state_dict(state["model"])
    return model.eval()


def load_high_quality(path: Path) -> HighQualitySwin:
    """Modell hoher Qualität aus einem Checkpoint von ``train_swin.py``, mit OSD-Schalter trainiert."""
    state = _state(path)
    state = state.get("model", state)
    if "base.conv_input.weight" not in state:
        raise ValueError("kein Swin-Checkpoint mit OSD-Schalter")
    model = HighQualitySwin()
    model.load_state_dict(state)
    return model.eval()
