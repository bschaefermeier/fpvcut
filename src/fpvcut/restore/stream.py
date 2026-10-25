"""Live-Vorschau: das normale Modell reinigt Clips, während mpv sie abspielt.

Jeder gereinigte Clip ist in der Timeline-EDL eine eigene Quelle ``fpvki://<id>``. Dahinter
steht ein eigenes mpv-Stream-Protokoll, das ein y4m-Video (rohe YUV-Bilder, feste Größe je Bild)
liefert: Beim Lesen rechnet ein Hintergrund-Thread die nächsten Bilder voraus. Weil jedes Bild
gleich groß ist, kann mpv darin springen; ein Sprung startet das Lesen ab dem Zielbild neu. Die
Farbkorrektur läuft danach wie bei allen Clips als mpv-Videofilter, also auf dem gereinigten Bild.
Das Bild bleibt in Rechengröße (BoxPro+: 592 × 352 plus Ränder), mpv vergrößert es ohnehin.

Zuletzt gerechnete Bilder bleiben im Speicher. Beim Neuladen der Vorschau (z. B. nach jedem
Regler) liest mpv den Anfang jeder Quelle und die aktuelle Stelle noch einmal; das kommt dann
ohne Rechnen aus dem Speicher.
"""

from __future__ import annotations

import ctypes
import hashlib
import queue
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fpvcut.restore.engine import ClipSpec, Models, restored, to_yuv420

PROTOCOL = "fpvki"
CACHE_BYTES = 400 * 1024 * 1024
AHEAD = 12  # so viele Bilder rechnet ein Thread höchstens voraus
IDLE_STOP = 3.0  # Sekunden ohne Lesen, dann hält ein Thread an (z. B. nach dem Abtasten beim Öffnen)
FRAME_TAG = b"FRAME\n"


class FrameCache:
    """Zuletzt gerechnete Bilder (bytes mit y4m-Kopf), am längsten unbenutzte fliegen zuerst raus."""

    def __init__(self, limit: int = CACHE_BYTES) -> None:
        self.limit = limit
        self._data: OrderedDict[tuple[str, int], bytes] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key: tuple[str, int]) -> bytes | None:
        with self._lock:
            data = self._data.get(key)
            if data is not None:
                self._data.move_to_end(key)
            return data

    def put(self, key: tuple[str, int], data: bytes) -> None:
        with self._lock:
            if key in self._data:
                return
            self._data[key] = data
            self._size += len(data)
            while self._size > self.limit and self._data:
                _, old = self._data.popitem(last=False)
                self._size -= len(old)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._size = 0


class _Worker(threading.Thread):
    """Rechnet Bilder ab ``start`` in eine Warteschlange, höchstens ``AHEAD`` voraus."""

    def __init__(self, service: PreviewService, key: str, spec: ClipSpec, start: int) -> None:
        super().__init__(daemon=True, name=f"fpvki-{key[:8]}-{start}")
        self.service, self.key, self.spec, self.start_index = service, key, spec, start
        self.frames: queue.Queue = queue.Queue(AHEAD)
        self.stopped = threading.Event()
        self.next_index = start  # nächstes Bild, das aus der Warteschlange kommt
        self.padding = spec.geometry.work_padding()
        self.last_access = time.monotonic()

    def run(self) -> None:
        try:
            for index, frame in restored(self.service.ffmpeg, self.spec, self.service.models, "normal",
                                         start=self.start_index, stopped=self.stopped, yuv=True):
                data = FRAME_TAG + to_yuv420(frame, self.padding)
                self.service.cache.put((self.key, index), data)
                while not self.stopped.is_set():
                    try:
                        self.frames.put((index, data), timeout=0.2)
                        break
                    except queue.Full:
                        if time.monotonic() - self.last_access > IDLE_STOP:
                            self.stopped.set()
                if self.stopped.is_set():
                    return
        except Exception as exc:  # noqa: BLE001  (Fehler beim Lesen anzeigen statt den Thread still sterben lassen)
            self.service.report_error(exc)
        finally:
            self._put_end()

    def _put_end(self) -> None:
        try:
            self.frames.put_nowait(None)
        except queue.Full:
            pass

    def take(self, index: int, cancelled: threading.Event) -> bytes | None:
        """Bild ``index`` abholen (davor liegende werden übersprungen); None, wenn der Thread endet."""
        while True:
            self.last_access = time.monotonic()
            try:
                item = self.frames.get(timeout=0.1)
            except queue.Empty:
                if cancelled.is_set() or (self.stopped.is_set() and not self.is_alive()):
                    return None
                continue
            if item is None:
                return None
            got, data = item
            self.next_index = got + 1
            if got >= index:
                return data

    def stop(self) -> None:
        self.stopped.set()


class RestoreStream:
    """Eine geöffnete Quelle: y4m-Kopf, dann ``frames`` Bilder gleicher Größe."""

    def __init__(self, service: PreviewService, key: str, spec: ClipSpec) -> None:
        self.service, self.key, self.spec = service, key, spec
        geometry = spec.geometry
        # Vorschau in Rechengröße, mit Rändern im Seitenverhältnis der Quelle
        left, top, right, bottom = geometry.work_padding()
        work_w, work_h = geometry.work_size
        self.width, self.height = work_w + left + right, work_h + top + bottom
        num, den = _fraction(spec.fps)
        self.header = f"YUV4MPEG2 W{self.width} H{self.height} F{num}:{den} Ip A1:1 C420jpeg\n".encode()
        self.frame_size = len(FRAME_TAG) + self.width * self.height * 3 // 2
        self.size = len(self.header) + spec.frames * self.frame_size
        self.pos = 0
        self._worker: _Worker | None = None
        self._current: tuple[int, bytes] | None = None  # zuletzt gelesenes Bild (wird stückweise gelesen)
        self.cancelled = threading.Event()

    def read(self, size: int) -> bytes:
        if self.pos >= self.size:
            return b""
        if self.pos < len(self.header):
            data = self.header[self.pos:self.pos + size]
        else:
            index, offset = divmod(self.pos - len(self.header), self.frame_size)
            frame = self._frame(index)
            if frame is None:
                return b""
            data = frame[offset:offset + size]
        self.pos += len(data)
        return data

    def seek(self, pos: int) -> int:
        self.pos = max(0, min(pos, self.size))
        return self.pos

    def _frame(self, index: int) -> bytes | None:
        if self._current is not None and self._current[0] == index:
            return self._current[1]
        data = self.service.cache.get((self.key, index))
        if data is None:
            worker = self._worker
            # Läuft schon ein Thread, der gleich bei diesem Bild ankommt? Sonst ab hier neu starten.
            if worker is None or not worker.is_alive() or not worker.next_index <= index < worker.next_index + AHEAD:
                self._start(index)
            data = self._worker.take(index, self.cancelled)
            if data is None:
                return None
        else:
            worker = self._worker
            if worker is not None and worker.is_alive():
                worker.last_access = time.monotonic()
            elif index + 1 < self.spec.frames and self.service.cache.get((self.key, index + 1)) is None:
                self._start(index + 1)  # Bilder kommen aus dem Speicher: das nächste schon vorausrechnen
        self._current = (index, data)
        return data

    def _start(self, index: int) -> None:
        if self._worker is not None:
            self._worker.stop()
        self._worker = _Worker(self.service, self.key, self.spec, index)
        self._worker.start()

    def cancel(self) -> None:
        self.cancelled.set()

    def close(self) -> None:
        self.cancelled.set()
        if self._worker is not None:
            self._worker.stop()
            self._worker = None


def _fraction(fps: float) -> tuple[int, int]:
    """Bildrate als Bruch für den y4m-Kopf."""
    return (round(fps), 1) if abs(fps - round(fps)) < 1e-3 else (round(fps * 1000), 1000)


def spec_key(spec: ClipSpec) -> str:
    text = f"{spec.path}|{spec.src_in:.4f}|{spec.duration:.4f}|{spec.fps:.4f}|{spec.geometry}|{spec.remove_osd}"
    return hashlib.sha1(text.encode()).hexdigest()[:16]


class PreviewService:
    """Verwaltet die ``fpvki://``-Quellen eines Players: welcher Clip hinter welcher Adresse steckt."""

    def __init__(self, ffmpeg: Path | str, models: Models) -> None:
        self.ffmpeg = ffmpeg
        self.models = models
        self.cache = FrameCache()
        self._specs: dict[str, ClipSpec] = {}
        self._streams: dict[int, tuple[RestoreStream, list]] = {}  # hält ctypes-Rückrufe am Leben
        self._registered: set[int] = set()
        self.last_error: str | None = None

    def url(self, spec: ClipSpec) -> str:
        key = spec_key(spec)
        self._specs[key] = spec
        return f"{PROTOCOL}://{key}"

    def report_error(self, exc: Exception) -> None:
        self.last_error = str(exc) or type(exc).__name__

    def open(self, uri: str) -> RestoreStream:
        key = uri.removeprefix(f"{PROTOCOL}://")
        if key not in self._specs:
            raise ValueError(uri)
        return RestoreStream(self, key, self._specs[key])

    def register(self, mpv_module, player) -> None:
        """Protokoll bei einem mpv-Player anmelden (einmal je Player).

        Eigene Anmeldung statt ``player.register_stream_protocol``: Dessen Lesefunktion kopiert
        Byte für Byte in Python, das ist für Videobilder viel zu langsam.
        """
        if id(player) in self._registered:
            return
        service = self

        @mpv_module.StreamOpenFn
        def open_backend(_userdata, uri, info):
            try:
                stream = service.open(uri.decode("utf-8"))
            except Exception:  # noqa: BLE001  (mpv erwartet nur einen Fehlercode)
                return mpv_module.ErrorCode.LOADING_FAILED

            def read(_userdata, buf, size):
                try:
                    data = stream.read(size)
                except Exception as exc:  # noqa: BLE001
                    service.report_error(exc)
                    return -1
                ctypes.memmove(buf, data, len(data))
                return len(data)

            def close(_userdata):
                stream.close()
                service._streams.pop(id(stream), None)

            callbacks = [
                mpv_module.StreamReadFn(read),
                mpv_module.StreamSeekFn(lambda _userdata, pos: stream.seek(pos)),
                mpv_module.StreamSizeFn(lambda _userdata: stream.size),
                mpv_module.StreamCloseFn(close),
                mpv_module.StreamCancelFn(lambda _userdata: stream.cancel()),
            ]
            contents = info.contents
            contents.cookie = None
            contents.read, contents.seek, contents.size, contents.close, contents.cancel = callbacks
            service._streams[id(stream)] = (stream, callbacks)
            return 0

        self._open_backend = open_backend  # muss so lange leben wie der Player
        mpv_module._mpv_stream_cb_add_ro(player.handle, PROTOCOL.encode(), ctypes.c_void_p(), open_backend)
        self._registered.add(id(player))
