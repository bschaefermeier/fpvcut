"""Bilder eines Clips lesen, durch Lehrer oder Schüler schicken und in Quellgröße zurückgeben.

Gerechnet wird wie im Training in halber Auflösung (BoxPro+: Bild 1200 × 720 ab x = 40, also
592 × 352). Das Ergebnis wird wieder auf die Bildfläche der Quelle vergrößert und mit schwarzen
Rändern auf ihr volles Format gebracht, damit es in Vorschau und Render genau an die Stelle des
Originals passt. Bild ``k`` eines Clips liegt bei ``src_in + k / fps``; die zwei Nachbarbilder
davor und danach kommen aus der Quelle (am Dateianfang/-ende wird das Randbild wiederholt).
"""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS
from fpvcut.restore.networks import TEACHER_WINDOW, load_student, load_teacher

CONTEXT = 2  # Nachbarbilder auf jeder Seite (beide Modelle sehen 5 Bilder)
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


class Models:
    """Lädt Lehrer und Schüler erst bei Bedarf (einmal) und rechnet nacheinander auf der Grafikkarte."""

    def __init__(self, student: Path | None, teacher: Path | None) -> None:
        self.paths = {"student": student, "teacher": teacher}
        self._loaded: dict[str, torch.nn.Module] = {}
        self._load_lock = threading.Lock()
        self.run_lock = threading.Lock()  # Vorschau und Render teilen sich die Karte
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def get(self, kind: str) -> torch.nn.Module:
        with self._load_lock:
            if kind not in self._loaded:
                path = self.paths[kind]
                if path is None:
                    raise FileNotFoundError(kind)
                model = load_student(path) if kind == "student" else load_teacher(path)
                self._loaded[kind] = model.to(self.device)
            return self._loaded[kind]

    def release(self, kind: str) -> None:
        """Modell aus dem Grafikspeicher nehmen (der Lehrer braucht fast 4 GB)."""
        with self._load_lock:
            if self._loaded.pop(kind, None) is not None and self.device.type == "cuda":
                torch.cuda.empty_cache()

    def run(self, model: torch.nn.Module, window: list[torch.Tensor], remove_osd: bool) -> torch.Tensor:
        x = torch.stack(window).unsqueeze(0)
        with self.run_lock, torch.inference_mode(), torch.autocast(self.device.type, dtype=torch.bfloat16):
            return model(x, 1.0 if remove_osd else 0.0)[0].float().clamp_(0, 1)


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


def _sequence(ffmpeg, spec: ClipSpec, models: Models, start: int, stop: int,
              stopped: threading.Event | None) -> Iterator[torch.Tensor]:
    """Bilder ``start - CONTEXT`` … ``stop - 1 + CONTEXT`` des Clips auf der Grafikkarte, Ränder aufgefüllt."""
    want = stop - start + 2 * CONTEXT
    reader = FrameReader(ffmpeg, spec, start - CONTEXT, want)
    sent, last = 0, None
    try:
        for frame in reader:
            if stopped is not None and stopped.is_set():
                return
            tensor = torch.from_numpy(frame.copy()).to(models.device, non_blocking=True)
            last = tensor.permute(2, 0, 1).float().div_(255)
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
             stopped: threading.Event | None = None) -> Iterator[tuple[int, torch.Tensor]]:
    """Gereinigte Bilder ``start`` … ``stop - 1`` des Clips: ``(Index, Bild 3×H×W in 0…1)`` in Rechengröße.

    Schüler: ein Durchlauf je Bild. Lehrer: liefert je Fenster alle 5 Bilder; verwendet werden die
    mittleren ``stride`` (1…5), danach rückt das Fenster um ``stride`` weiter (am Ende auch äußere).
    """
    stop = spec.frames if stop is None else min(stop, spec.frames)
    if start >= stop:
        return
    model = models.get(kind)
    frames = _sequence(ffmpeg, spec, models, start, stop, stopped)
    if kind == "student":
        window: deque[torch.Tensor] = deque(maxlen=2 * CONTEXT + 1)
        index = start
        for frame in frames:
            window.append(frame)
            if len(window) == window.maxlen:
                yield index, models.run(model, list(window), spec.remove_osd)
                index += 1
        return
    stride = max(1, min(stride, TEACHER_WINDOW))
    total = stop - start + 2 * CONTEXT  # Länge der aufgefüllten Folge
    first_use = CONTEXT - stride // 2  # erste verwendete Stelle im Fenster
    buffer: list[torch.Tensor] = []
    base = 0  # Folgenposition von buffer[0]
    pos = stride // 2  # Fensteranfang in der Folge; so liefert das erste Fenster Clip-Bild 0
    need, last_need = CONTEXT, total - 1 - CONTEXT  # Folgenpositionen der Clip-Bilder
    for frame in frames:
        buffer.append(frame)
        while need <= last_need:
            window_end = min(pos, total - TEACHER_WINDOW) + TEACHER_WINDOW
            if base + len(buffer) < window_end:
                break  # noch nicht genug Bilder gelesen
            final = pos + TEACHER_WINDOW > total
            begin = total - TEACHER_WINDOW if final else pos
            out = models.run(model, buffer[begin - base:begin - base + TEACHER_WINDOW], spec.remove_osd)
            use_to = last_need if final else min(pos + first_use + stride - 1, last_need)
            while need <= use_to:
                yield start + need - CONTEXT, out[need - begin]
                need += 1
            pos += stride
            drop = min(pos, total - TEACHER_WINDOW) - base
            if drop > 0:
                del buffer[:drop]
                base += drop


def to_source(frame: torch.Tensor, geometry: Geometry, scale: float = 1.0) -> torch.Tensor:
    """Gereinigtes Bild auf die Bildfläche der Quelle vergrößern und mit Schwarz auf ihr Format bringen.

    ``scale`` verkleinert das Ganze (Vorschau: 0,5). Gibt 3×H×W in 0…1 zurück, H und W gerade.
    """
    x, y, w, h = (round(v * scale) for v in geometry.crop)
    width, height = _even(round(geometry.width * scale)), _even(round(geometry.height * scale))
    w, h = min(w, width - x), min(h, height - y)
    resized = F.interpolate(frame.unsqueeze(0), size=(h, w), mode="bicubic", align_corners=False)[0].clamp_(0, 1)
    if (w, h) == (width, height):
        return resized
    canvas = torch.zeros((3, height, width), dtype=frame.dtype, device=frame.device)
    canvas[:, y:y + h, x:x + w] = resized
    return canvas


def _even(value: int) -> int:
    return max(2, value - value % 2)


def to_rgb24(frame: torch.Tensor) -> bytes:
    return frame.mul(255).add_(0.5).to(torch.uint8).permute(1, 2, 0).contiguous().cpu().numpy().tobytes()


def to_yuv420(frame: torch.Tensor) -> bytes:
    """BT.601 mit eingeschränktem Wertebereich (wie y4m es erwartet), Farbe halb aufgelöst."""
    r, g, b = frame[0], frame[1], frame[2]
    luma = 16 + 219 * (0.299 * r + 0.587 * g + 0.114 * b)
    small = F.avg_pool2d(frame.unsqueeze(0), 2)[0]
    r, g, b = small[0], small[1], small[2]
    u = 128 + 224 * (-0.168736 * r - 0.331264 * g + 0.5 * b)
    v = 128 + 224 * (0.5 * r - 0.418688 * g - 0.081312 * b)
    planes = torch.cat([luma.flatten(), u.flatten(), v.flatten()])
    return planes.add_(0.5).clamp_(0, 255).to(torch.uint8).cpu().numpy().tobytes()
