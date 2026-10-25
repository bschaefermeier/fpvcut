"""Gereinigte Fassung eines Clips als Zwischendatei fürs Rendern.

Vor dem eigentlichen ffmpeg-Lauf wird jeder Clip mit KI-Reinigung einmal durch das normale Modell oder das hoher Qualität
geschickt und in Quellgröße (mit den schwarzen Rändern der Quelle) fast verlustfrei gespeichert.
Der Render nimmt dann das Bild aus dieser Datei und den Ton aus dem Original; die Farbkorrektur
läuft dort wie bei allen Clips, also nach der Reinigung.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS
from fpvcut.restore.engine import ClipSpec, Models, restored


class Cancelled(Exception):
    pass


def intermediate_encoder(gpu: bool) -> list[str]:
    """Kaum sichtbare Verluste, schnell: NVENC mit fester Quantisierung, sonst x264."""
    if gpu:
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "constqp", "-qp", "12"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "10"]


def restore_clip(ffmpeg: Path | str, spec: ClipSpec, models: Models, output: Path, *, kind: str = "high_quality",
                 stride: int = 1, gpu_encoder: bool = False, progress: Callable[[int], None] | None = None,
                 stopped: threading.Event | None = None) -> None:
    """``spec`` gereinigt nach ``output`` schreiben; ``progress`` bekommt die Zahl fertiger Bilder."""
    geometry = spec.geometry
    work_w, work_h = geometry.work_size
    x, y, w, h = geometry.crop
    width, height = geometry.width - geometry.width % 2, geometry.height - geometry.height % 2
    # Zurück auf die Bildfläche der Quelle vergrößern und ihre schwarzen Ränder wieder ansetzen
    vf = f"scale={w}:{h}:flags=bicubic,pad={width}:{height}:{x}:{y}:black"
    writer = subprocess.Popen(
        [str(ffmpeg), "-hide_banner", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{work_w}x{work_h}", "-r", f"{spec.fps:.6g}", "-i", "-", "-vf", vf,
         *intermediate_encoder(gpu_encoder), "-pix_fmt", "yuv420p", str(output)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_FLAGS,
    )
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(writer.stderr.read()), daemon=True)
    reader.start()
    done = 0
    try:
        for _index, frame in restored(ffmpeg, spec, models, kind, stride, stopped=stopped):
            if stopped is not None and stopped.is_set():
                raise Cancelled
            writer.stdin.write(frame.tobytes())
            done += 1
            if progress is not None:
                progress(done)
        if stopped is not None and stopped.is_set():
            raise Cancelled
        writer.stdin.close()
        code = writer.wait()
    except (Cancelled, OSError):
        writer.kill()
        writer.wait()
        output.unlink(missing_ok=True)
        if stopped is not None and stopped.is_set():
            raise Cancelled from None
        raise
    reader.join(5)
    if code != 0:
        output.unlink(missing_ok=True)
        message = b"".join(errors).decode(errors="replace").strip().splitlines()[-3:]
        raise OSError("\n".join(message) or f"ffmpeg {code}")
