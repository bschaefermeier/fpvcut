"""Normales Modell über ONNX Runtime: ohne PyTorch, auf der Grafikkarte per DirectML (jede DirectX-12-Karte).

Das ONNX-Modell entsteht mit :mod:`fpvcut.restore.export` aus dem Checkpoint von fpv-restoration
und nimmt die Bilder direkt als ``uint8`` (Umrechnung und FP16 stecken im Modell).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

PREFERRED = ["DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]


def providers() -> list[str]:
    import onnxruntime  # noqa: PLC0415

    available = set(onnxruntime.get_available_providers())
    return [p for p in PREFERRED if p in available]


class OnnxNormal:
    all_frames = False

    def __init__(self, path: Path) -> None:
        import onnxruntime  # noqa: PLC0415

        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3  # keine Hinweise, welche Formknoten auf dem Prozessor laufen
        self.session = onnxruntime.InferenceSession(str(path), options, providers=providers())
        self.provider = self.session.get_providers()[0]
        self._flags = {False: np.zeros(1, np.float32), True: np.ones(1, np.float32)}
        if "y" not in {o.name for o in self.session.get_outputs()}:
            self.run_yuv = None  # älteres Modell ohne YUV-Ausgabe: dann rechnet numpy um

    def run(self, window: list[np.ndarray], remove_osd: bool) -> np.ndarray:
        frames = np.stack(window)[None]
        return self.session.run(["restored"], {"frames": frames, "remove_osd": self._flags[bool(remove_osd)]})[0]

    def run_yuv(self, window: list[np.ndarray], remove_osd: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Dasselbe gleich als YUV-4:2:0-Ebenen (auf der Grafikkarte umgerechnet), für die Vorschau."""
        frames = np.stack(window)[None]
        y, u, v = self.session.run(["y", "u", "v"], {"frames": frames, "remove_osd": self._flags[bool(remove_osd)]})
        return y, u, v
