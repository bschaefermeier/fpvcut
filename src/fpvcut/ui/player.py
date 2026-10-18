"""Videoplayer: libmpv eingebettet in ein Qt-Widget."""

from __future__ import annotations

import locale
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedLayout,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from fpvcut.core.paths import vendor_dir
from fpvcut.ui.clip_bar import ClipBar


def _prepare_libmpv_search_path() -> None:
    """Macht ``libmpv-2.dll`` aus ``vendor/mpv`` oder ``FPVCUT_MPV_DIR`` auffindbar."""
    dirs = [os.environ.get("FPVCUT_MPV_DIR"), vendor_dir("mpv")]
    for d in dirs:
        if d and Path(d).is_dir():
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ.get('PATH', '')}"
            if sys.platform == "win32":
                os.add_dll_directory(str(d))


MAX_DOUBLE_CLICK = 0.3  # Sekunden
DEMUXER_OFFSET = 1.0  # Sekunden; bei hängendem Frame-zurück wird auf DEMUXER_OFFSET_STUCK erhöht
DEMUXER_OFFSET_STUCK = 5.0


def load_mpv():
    """Importiert python-mpv. Gibt ``(modul, None)`` oder ``(None, fehlermeldung)`` zurück."""
    _prepare_libmpv_search_path()
    try:
        import mpv  # noqa: PLC0415  (libmpv wird erst hier geladen)
    except (ImportError, OSError) as exc:
        return None, str(exc)
    return mpv, None


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--.---"
    minutes, secs = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes):02d}:{secs:06.3f}"


class PlayerWidget(QWidget):
    """Videofläche mit Transportleiste. Signale werden im Qt-Thread ausgelöst."""

    position_changed = Signal(float)
    duration_changed = Signal(float)
    double_clicked = Signal()
    marks_changed = Signal()
    nothing_loaded = Signal()  # Play gedrückt, aber nichts geladen
    _mpv_click = Signal()
    _mpv_double = Signal()
    _mpv_time = Signal(object)
    _mpv_duration = Signal(object)
    _mpv_pause = Signal(bool)

    SLIDER_STEPS = 10_000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._slider_dragging = False
        self._player = None
        self._loaded = False
        # Ersetzt Sprünge, z. B. durch Neuladen der Timeline-Vorschau ab der Zielposition.
        self.seek_handler: Callable[[float], None] | None = None

        self._video = QWidget(self)
        self._video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._video.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self._video.setStyleSheet("background: black;")
        self._video.setMinimumSize(320, 180)
        # Unter Windows deaktiviert mpv sein eingebettetes Fenster, Klicks landen dann hier bei Qt.
        self._video.installEventFilter(self)
        self._last_press = 0.0
        self._double_pending = False
        self._back_step_from: float | None = None  # Position vor dem letzten Frame-zurück
        self._back_steps = 0
        self._last_double = 0.0

        self._message = QLabel(self)
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)

        self._stack = QStackedLayout()
        self._stack.addWidget(self._video)
        self._stack.addWidget(self._message)

        self._play_button = QPushButton("▶", self)
        self._play_button.setFixedWidth(40)
        self._play_button.clicked.connect(self.toggle_pause)
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setRange(0, self.SLIDER_STEPS)
        self._slider.sliderPressed.connect(lambda: setattr(self, "_slider_dragging", True))
        self._slider.sliderReleased.connect(self._on_slider_released)
        # Kein Fokus, damit Leertaste und Pfeiltasten immer beim Fenster ankommen.
        self._play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._time_label = QLabel(f"{format_time(None)} / {format_time(None)}", self)

        self.in_point: float | None = None
        self.out_point: float | None = None
        self._clip_bar = ClipBar(self)
        self._clip_bar.seek_requested.connect(self.seek_absolute)
        self._clip_bar.set_inset(self.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength) // 2)

        controls = QGridLayout()
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(0)
        controls.addWidget(self._play_button, 0, 0, 2, 1)
        controls.addWidget(self._slider, 0, 1)
        controls.addWidget(self._clip_bar, 1, 1)
        controls.addWidget(self._time_label, 0, 2, 2, 1)
        controls.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._stack, 1)
        layout.addLayout(controls)

        self._mpv_click.connect(self._on_video_press)
        self._mpv_double.connect(self._on_video_double_click)
        self._mpv_time.connect(self._on_time)
        self._mpv_duration.connect(self._on_duration)
        self._mpv_pause.connect(lambda paused: self._play_button.setText("▶" if paused else "⏸"))

        # mpv erst starten, wenn das Fenster eine native Handle-ID hat.
        QTimer.singleShot(0, self._init_mpv)

    @property
    def available(self) -> bool:
        return self._player is not None

    def _init_mpv(self) -> None:
        mpv, error = load_mpv()
        if mpv is None:
            self._show_message(
                "libmpv wurde nicht gefunden.\n\n"
                "Bitte libmpv-2.dll nach vendor/mpv legen (siehe README).\n\n"
                f"Details: {error}"
            )
            return
        # libmpv verlangt einen C-Locale für Zahlen, Qt setzt sonst den System-Locale.
        locale.setlocale(locale.LC_NUMERIC, "C")
        try:
            self._player = mpv.MPV(
                wid=str(int(self._video.winId())),
                hwdec="auto-safe",
                vo="gpu",
                keep_open="yes",
                osc="no",
                input_default_bindings="no",
                input_vo_keyboard="no",
                input_doubleclick_time=int(self._double_click_interval() * 1000),
                # Manche Dateien (z. B. DVR-Aufnahmen) springen beim Suchen auf einen Keyframe *nach*
                # dem Ziel; dann bleibt Frame-zurück dort hängen. Etwas früher suchen behebt das.
                hr_seek_demuxer_offset=DEMUXER_OFFSET,
            )
        except Exception as exc:  # noqa: BLE001  (mpv meldet Fehler als diverse Typen)
            self._show_message(f"mpv konnte nicht gestartet werden:\n{exc}")
            return
        self._player.observe_property("time-pos", lambda _n, v: self._mpv_time.emit(v))
        self._player.observe_property("duration", lambda _n, v: self._mpv_duration.emit(v))
        self._player.observe_property("pause", lambda _n, v: self._mpv_pause.emit(bool(v)))
        # Unter Linux/X11 bekommt mpv die Klicks selbst; daher zusätzlich als mpv-Bindings.
        self._player.register_key_binding("MBTN_LEFT", self._on_mpv_key(self._mpv_click))
        self._player.register_key_binding("MBTN_LEFT_DBL", self._on_mpv_key(self._mpv_double))

    @staticmethod
    def _on_mpv_key(signal):
        """Reagiert einmal pro Klick (aus dem mpv-Thread).

        mpv meldet ``d`` (gedrückt), ``u`` (losgelassen) oder ``p`` (beides auf einmal,
        z. B. beim Doppelklick).
        """

        def handler(state: str, *_args) -> None:
            if state[:1] in ("d", "p"):
                signal.emit()

        return handler

    # --- Mausklicks aufs Video ------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt-Name)
        kind = event.type()
        mouse = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease)
        if watched is self._video and kind in mouse and event.button() == Qt.MouseButton.LeftButton:
            if kind == QEvent.Type.MouseButtonPress:
                self._on_video_press()
            elif kind == QEvent.Type.MouseButtonDblClick:
                if time.monotonic() - self._last_press < self._double_click_interval():
                    self._double_pending = True  # Vollbild erst beim Loslassen, wie bei anderen Playern
                else:
                    self._on_video_press()  # für Windows ein Doppelklick, für uns zwei einzelne Klicks
            elif self._double_pending:
                self._double_pending = False
                self._on_video_double_click()
            return True
        return super().eventFilter(watched, event)

    def _on_video_press(self) -> None:
        """Ein Klick schaltet Play/Pause. Ein zweiter Klick kurz danach gehört zum Doppelklick.

        Je nach System melden Qt, mpv oder beide denselben Klick; die Zeitfenster sorgen dafür,
        dass er trotzdem nur einmal zählt.
        """
        now = time.monotonic()
        if now - self._last_press >= self._double_click_interval():
            self.toggle_pause()
        self._last_press = now

    def _on_video_double_click(self) -> None:
        now = time.monotonic()
        if now - self._last_double < self._double_click_interval():
            return
        self._last_double = now
        self.toggle_pause()  # den ersten Klick des Doppelklicks rückgängig machen
        self.double_clicked.emit()

    @staticmethod
    def _double_click_interval() -> float:
        """Höchstens 0,3 s wie bei mpv und YouTube; Windows erlaubt 0,5 s, das löst zu leicht Vollbild aus."""
        return min(QApplication.doubleClickInterval() / 1000, MAX_DOUBLE_CLICK)

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)

    # --- Steuerung -------------------------------------------------------

    def open(self, path: str | Path, start: float | None = None, end: float | None = None) -> None:
        """Video öffnen; mit ``start``/``end`` direkt den Ausschnitt in Schleife abspielen."""
        self.clear_marks()
        self.set_clips([])
        self.seek_handler = None
        if start is not None:
            self.in_point, self.out_point = start, end
            self._marks_updated()
        if self._player is None:
            return
        self._loaded = True
        if start is None:
            self._player.play(str(path))
        else:
            # Als Datei-Optionen, damit mpv gleich an der richtigen Stelle beginnt.
            options = {"start": f"{start:.3f}"}
            if end is not None:
                options |= {"ab_loop_a": f"{start:.3f}", "ab_loop_b": f"{end:.3f}"}
            self._player.loadfile(str(path), **options)
        self._player.pause = False

    def open_timeline(self, edl: str, lavfi: str, start: float = 0.0, paused: bool = False) -> None:
        """Timeline als EDL abspielen; ``lavfi`` mischt Originalton und Musik."""
        self.clear_marks()
        self.set_clips([])
        if self._player is None:
            return
        self._loaded = True
        # Als Datei-Option gilt der Filter nur für die Timeline und verschwindet beim nächsten Video.
        # %Länge% schützt Kommas und Semikolons im Filtergraphen.
        self._player.loadfile(
            edl, start=f"{max(start, 0.0):.3f}", lavfi_complex=f"%{len(lavfi.encode())}%{lavfi}"
        )
        self._player.pause = paused

    def stop(self) -> None:
        self._loaded = False
        self.seek_handler = None
        if self._player is not None:
            self._player.command("stop")

    @property
    def paused(self) -> bool:
        return True if self._player is None else bool(self._player.pause)

    def seek_absolute(self, seconds: float) -> None:
        if self.seek_handler is not None:
            self.seek_handler(max(seconds, 0.0))
        elif self._player is not None:
            self._player.seek(seconds, reference="absolute", precision="exact")

    # --- In/Out-Punkte und Favoriten -------------------------------------

    def set_in(self) -> None:
        pos = self.position()
        if pos is None:
            return
        self.in_point = pos
        if self.out_point is not None and self.out_point <= pos:
            self.out_point = None
        self._marks_updated()

    def set_out(self) -> None:
        pos = self.position()
        if pos is None:
            return
        self.out_point = pos
        if self.in_point is not None and self.in_point >= pos:
            self.in_point = None
        self._marks_updated()

    def clear_marks(self) -> None:
        self.in_point = self.out_point = None
        self._set_loop(None, None)
        self._marks_updated()

    def has_marks(self) -> bool:
        return self.in_point is not None or self.out_point is not None

    def _marks_updated(self) -> None:
        self._clip_bar.set_marks(self.in_point, self.out_point)
        self.marks_changed.emit()

    def set_clips(self, clips: list[tuple[float, float | None]]) -> None:
        """Gespeicherte Favoriten des aktuellen Videos in der Leiste anzeigen."""
        self._clip_bar.set_clips(clips)

    def play_range(self, start: float, end: float | None) -> None:
        """Ausschnitt in Schleife abspielen, bis die Auswahl aufgehoben wird (Esc)."""
        if self._player is None:
            return
        self.in_point, self.out_point = start, end
        self._marks_updated()
        self._set_loop(start, end)
        self.seek_absolute(start)
        self._player.pause = False

    def _set_loop(self, start: float | None, end: float | None) -> None:
        if self._player is None:
            return
        self._player["ab-loop-a"] = "no" if start is None or end is None else start
        self._player["ab-loop-b"] = "no" if start is None or end is None else end

    def toggle_pause(self) -> None:
        if not self._loaded:
            self.nothing_loaded.emit()
            return
        if self._player is not None:
            self._player.pause = not self._player.pause

    def seek_relative(self, seconds: float) -> None:
        if self.seek_handler is not None:
            if (pos := self.position()) is not None:
                self.seek_absolute(pos + seconds)
        elif self._player is not None:
            self._player.seek(seconds, reference="relative", precision="exact")

    def step_frame(self, forward: bool = True) -> None:
        if not forward and self.seek_handler is not None:
            if (pos := self.position()) is not None:
                fps = self._player.container_fps or 30.0
                self.seek_absolute(pos - 1.0 / fps)
        elif self._player is not None:
            if not forward:
                self._back_step_from = self.position()
                self._back_steps += 1
                count = self._back_steps
                QTimer.singleShot(400, lambda: self._check_back_step(count))
            self._player.command("frame-step" if forward else "frame-back-step")

    def _check_back_step(self, count: int) -> None:
        """Hat Frame-zurück nichts bewirkt, mit größerem Vorlauf noch einmal versuchen."""
        if count != self._back_steps:  # schon wieder gedrückt (Taste gehalten): nur den letzten prüfen
            return
        start, self._back_step_from = self._back_step_from, None
        if self._player is None or start is None or self.position() is None:
            return
        if abs(self.position() - start) < 1e-4 and start > 0.05:
            if self._player["hr-seek-demuxer-offset"] < DEMUXER_OFFSET_STUCK:
                self._player["hr-seek-demuxer-offset"] = DEMUXER_OFFSET_STUCK
                self._player.command("frame-back-step")

    def position(self) -> float | None:
        return self._player.time_pos if self._player is not None else None

    def shutdown(self) -> None:
        if self._player is not None:
            self._player.terminate()
            self._player = None

    # --- Rückmeldungen von mpv ------------------------------------------

    def _on_time(self, value: float | None) -> None:
        if value is None:
            return
        if not self._slider_dragging and self._duration > 0:
            self._slider.setValue(int(value / self._duration * self.SLIDER_STEPS))
        self._time_label.setText(f"{format_time(value)} / {format_time(self._duration)}")
        self.position_changed.emit(value)

    def _on_duration(self, value: float | None) -> None:
        self._duration = value or 0.0
        self._clip_bar.set_duration(self._duration)
        self.duration_changed.emit(self._duration)

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        if self._player is not None and self._duration > 0:
            self.seek_absolute(self._slider.value() / self.SLIDER_STEPS * self._duration)
