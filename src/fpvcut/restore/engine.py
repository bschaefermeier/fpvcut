"""Bilder eines Clips lesen und durch Lehrer oder Schüler schicken.

Gerechnet wird wie im Training in halber Auflösung (BoxPro+: Bild 1200 × 720 ab x = 40, also
592 × 352); geliefert werden gereinigte Bilder in dieser Rechengröße als ``uint8`` (H, W, 3).
Vorschau und Render bringen sie danach wieder aufs Format der Quelle (mit deren schwarzen
Rändern). Bild ``k`` eines Clips liegt bei ``src_in + k / fps``; die zwei Nachbarbilder davor und
danach kommen aus der Quelle (am Dateianfang/-ende wird das Randbild wiederholt).

Wer rechnet, steckt in einem „Runner“: der Schüler über ONNX Runtime (:mod:`onnx_runner`, ohne
PyTorch) oder PyTorch, der Lehrer über PyTorch (:mod:`torch_runner`). Dieses Modul selbst braucht
nur numpy.
"""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS

CONTEXT = 2  # Nachbarbilder auf jeder Seite (beide Modelle sehen 5 Bilder)
WINDOW = 2 * CONTEXT + 1
BOXPRO = (1280, 720)  # BoxPro+-Aufnahmen: Bild 1200 × 720 ab x = 40, links und rechts schwarz


@dataclass(frozen=True)
class Geometry:
    """Quellformat, gereinigter Bildausschnitt darin und Rechengröße (halb, durch 16 teilbar)."""

    width: int
    height: int
    crop: tuple[int, int, int, int]  # x, y, Breite, Höhe

    @classmethod
    def for_source(cls, width: int, height: int) -> Geometry:
        if (width, height) == BOXPRO:
            return cls(width, height, (40, 0, 1200, 720))
        return cls(width, height, (0, 0, width, height))

    @property
    def work_size(self) -> tuple[int, int]:
        _, _, w, h = self.crop
        return max(16, w // 2 // 16 * 16), max(16, h // 2 // 16 * 16)

    def work_padding(self) -> tuple[int, int, int, int]:
        """Schwarze Ränder (links, oben, rechts, unten), die das Bild in Rechengröße wieder aufs
        Seitenverhältnis der ganzen Quelle bringen; gerade Zahlen (für halb aufgelöste Farbe)."""
        x, y, w, h = self.crop
        pw, ph = self.work_size
        sx, sy = pw / w, ph / h

        def even(v: float) -> int:
            return round(v / 2) * 2

        return even(x * sx), even(y * sy), even((self.width - x - w) * sx), even((self.height - y - h) * sy)


@dataclass(frozen=True)
class ClipSpec:
    """Ein zu reinigender Ausschnitt; ``frames`` Bilder ab ``src_in``."""

    path: Path
    src_in: float
    duration: float
    fps: float
    geometry: Geometry
    remove_osd: bool = False

    @property
    def frames(self) -> int:
        return max(1, round(self.duration * self.fps))


class Runner(Protocol):
    """Ein geladenes Modell. ``all_frames``: liefert für alle 5 Eingabebilder ein Ergebnis (Lehrer)."""

    all_frames: bool

    def run(self, window: list[np.ndarray], remove_osd: bool) -> np.ndarray:
        """5 Bilder (H, W, 3) uint8 → (H, W, 3), beim Lehrer (5, H, W, 3)."""


class Models:
    """Lädt Lehrer und Schüler erst bei Bedarf (einmal); beide rechnen nacheinander, nie gleichzeitig."""

    def __init__(self, student: Path | None, teacher: Path | None) -> None:
        self.paths = {"student": student, "teacher": teacher}
        self._loaded: dict[str, Runner] = {}
        self._load_lock = threading.Lock()
        self.run_lock = threading.Lock()  # Vorschau und Render teilen sich die Karte

    def get(self, kind: str) -> Runner:
        with self._load_lock:
            if kind not in self._loaded:
                path = self.paths[kind]
                if path is None:
                    raise FileNotFoundError(kind)
                if path.suffix.lower() == ".onnx":
                    from fpvcut.restore.onnx_runner import OnnxStudent  # noqa: PLC0415

                    self._loaded[kind] = OnnxStudent(path)
                else:
                    from fpvcut.restore import torch_runner  # noqa: PLC0415  (lädt PyTorch)

                    self._loaded[kind] = torch_runner.load(kind, path)
            return self._loaded[kind]

    def release(self, kind: str) -> None:
        """Modell freigeben (der Lehrer belegt fast 4 GB Grafikspeicher)."""
        with self._load_lock:
            runner = self._loaded.pop(kind, None)
        if runner is not None and hasattr(runner, "close"):
            runner.close()

    def run(self, runner: Runner, window: list[np.ndarray], remove_osd: bool) -> np.ndarray:
        with self.run_lock:
            return runner.run(window, remove_osd)


class FrameReader:
    """Liest mit ffmpeg Bilder ab Quellbild ``first`` (darf negativ sein: dann wird aufgefüllt)."""

    def __init__(self, ffmpeg: Path | str, spec: ClipSpec, first: int, count: int) -> None:
        self.spec = spec
        before = round(spec.src_in * spec.fps) + first  # so viele Bilder hat die Quelle davor
        self.missing = max(0, -before)  # am Dateianfang fehlende Bilder
        start = max(spec.src_in + (first + self.missing - 0.5) / spec.fps, 0.0)
        x, y, w, h = spec.geometry.crop
        pw, ph = spec.geometry.work_size
        vf = f"crop={w}:{h}:{x}:{y},scale={pw}:{ph}:flags=area,format=rgb24"
        self._size = pw * ph * 3
        self._shape = (ph, pw, 3)
        self.process = subprocess.Popen(
            [str(ffmpeg), "-v", "error", "-nostdin", "-ss", f"{start:.4f}", "-i", str(spec.path), "-an", "-sn",
             "-vf", vf, "-frames:v", str(max(count - self.missing, 1)), "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self._size * 4, creationflags=CREATE_FLAGS,
        )

    def __iter__(self) -> Iterator[np.ndarray]:
        while len(data := self.process.stdout.read(self._size)) == self._size:
            yield np.frombuffer(data, np.uint8).reshape(self._shape)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.stdout.close()
        self.process.wait()


def _sequence(ffmpeg, spec: ClipSpec, start: int, stop: int,
              stopped: threading.Event | None) -> Iterator[np.ndarray]:
    """Bilder ``start - CONTEXT`` … ``stop - 1 + CONTEXT`` des Clips, Ränder aufgefüllt."""
    want = stop - start + 2 * CONTEXT
    reader = FrameReader(ffmpeg, spec, start - CONTEXT, want)
    sent, last = 0, None
    try:
        for last in reader:
            if stopped is not None and stopped.is_set():
                return
            for _ in range(reader.missing + 1 if sent == 0 else 1):
                if sent < want:
                    yield last
                    sent += 1
            if sent >= want:
                return
        if last is None:
            raise OSError(f"ffmpeg lieferte keine Bilder: {spec.path}")
        while sent < want:  # Dateiende: letztes Bild wiederholen
            yield last
            sent += 1
    finally:
        reader.close()


def restored(ffmpeg: Path | str, spec: ClipSpec, models: Models, kind: str = "student", stride: int = 1,
             start: int = 0, stop: int | None = None,
             stopped: threading.Event | None = None) -> Iterator[tuple[int, np.ndarray]]:
    """Gereinigte Bilder ``start`` … ``stop - 1`` des Clips: ``(Index, Bild H×W×3 uint8)`` in Rechengröße.

    Schüler: ein Durchlauf je Bild. Lehrer: liefert je Fenster alle 5 Bilder; verwendet werden die
    mittleren ``stride`` (1…5), danach rückt das Fenster um ``stride`` weiter (am Ende auch äußere).
    """
    stop = spec.frames if stop is None else min(stop, spec.frames)
    if start >= stop:
        return
    runner = models.get(kind)
    frames = _sequence(ffmpeg, spec, start, stop, stopped)
    if not runner.all_frames:
        window: deque[np.ndarray] = deque(maxlen=WINDOW)
        index = start
        for frame in frames:
            window.append(frame)
            if len(window) == WINDOW:
                yield index, models.run(runner, list(window), spec.remove_osd)
                index += 1
        return
    stride = max(1, min(stride, WINDOW))
    total = stop - start + 2 * CONTEXT  # Länge der aufgefüllten Folge
    first_use = CONTEXT - stride // 2  # erste verwendete Stelle im Fenster
    buffer: list[np.ndarray] = []
    base = 0  # Folgenposition von buffer[0]
    pos = stride // 2  # Fensteranfang in der Folge; so liefert das erste Fenster Clip-Bild 0
    need, last_need = CONTEXT, total - 1 - CONTEXT  # Folgenpositionen der Clip-Bilder
    for frame in frames:
        buffer.append(frame)
        while need <= last_need:
            window_end = min(pos, total - WINDOW) + WINDOW
            if base + len(buffer) < window_end:
                break  # noch nicht genug Bilder gelesen
            final = pos + WINDOW > total
            begin = total - WINDOW if final else pos
            out = models.run(runner, buffer[begin - base:begin - base + WINDOW], spec.remove_osd)
            use_to = last_need if final else min(pos + first_use + stride - 1, last_need)
            while need <= use_to:
                yield start + need - CONTEXT, out[need - begin]
                need += 1
            pos += stride
            drop = min(pos, total - WINDOW) - base
            if drop > 0:
                del buffer[:drop]
                base += drop


def to_yuv420(frame: np.ndarray, padding: tuple[int, int, int, int] = (0, 0, 0, 0)) -> bytes:
    """RGB (H, W, 3) uint8 → YUV 4:2:0 in BT.601 mit eingeschränktem Wertebereich (wie y4m es
    erwartet), mit schwarzen Rändern ``padding`` (links, oben, rechts, unten; gerade)."""
    rgb = frame.astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    luma = 16 + (65.481 * r + 128.553 * g + 24.966 * b) / 255
    h, w = frame.shape[0] // 2 * 2, frame.shape[1] // 2 * 2
    small = rgb[:h, :w].reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    u = 128 + (-37.797 * r - 74.203 * g + 112.0 * b) / 255
    v = 128 + (112.0 * r - 93.786 * g - 18.214 * b) / 255
    left, top, right, bottom = padding
    planes = [
        np.pad(luma, ((top, bottom), (left, right)), constant_values=16),
        np.pad(u, ((top // 2, bottom // 2), (left // 2, right // 2)), constant_values=128),
        np.pad(v, ((top // 2, bottom // 2), (left // 2, right // 2)), constant_values=128),
    ]
    return b"".join(np.clip(p + 0.5, 0, 255).astype(np.uint8).tobytes() for p in planes)
