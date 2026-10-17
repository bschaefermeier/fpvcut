"""Videoplayer: libmpv eingebettet in ein Qt-Widget."""

from __future__ import annotations

import locale
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)


def _prepare_libmpv_search_path() -> None:
    """Macht ``libmpv-2.dll`` aus ``vendor/mpv`` oder ``FPVCUT_MPV_DIR`` auffindbar."""
    dirs = [os.environ.get("FPVCUT_MPV_DIR"), Path(__file__).resolve().parents[3] / "vendor" / "mpv"]
    for d in dirs:
        if d and Path(d).is_dir():
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ.get('PATH', '')}"
            if sys.platform == "win32":
                os.add_dll_directory(str(d))


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
    _mpv_time = Signal(object)
    _mpv_duration = Signal(object)
    _mpv_pause = Signal(bool)

    SLIDER_STEPS = 10_000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._slider_dragging = False
        self._player = None

        self._video = QWidget(self)
        self._video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._video.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self._video.setStyleSheet("background: black;")
        self._video.setMinimumSize(320, 180)

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

        controls = QHBoxLayout()
        controls.addWidget(self._play_button)
        controls.addWidget(self._slider, 1)
        controls.addWidget(self._time_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._stack, 1)
        layout.addLayout(controls)

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
            )
        except Exception as exc:  # noqa: BLE001  (mpv meldet Fehler als diverse Typen)
            self._show_message(f"mpv konnte nicht gestartet werden:\n{exc}")
            return
        self._player.observe_property("time-pos", lambda _n, v: self._mpv_time.emit(v))
        self._player.observe_property("duration", lambda _n, v: self._mpv_duration.emit(v))
        self._player.observe_property("pause", lambda _n, v: self._mpv_pause.emit(bool(v)))

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)

    # --- Steuerung -------------------------------------------------------

    def open(self, path: str | Path) -> None:
        if self._player is None:
            return
        self._player.play(str(path))
        self._player.pause = False

    def toggle_pause(self) -> None:
        if self._player is not None:
            self._player.pause = not self._player.pause

    def seek_relative(self, seconds: float) -> None:
        if self._player is not None:
            self._player.seek(seconds, reference="relative", precision="exact")

    def step_frame(self, forward: bool = True) -> None:
        if self._player is not None:
            self._player.command("frame-step" if forward else "frame-back-step")

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
        self.duration_changed.emit(self._duration)

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        if self._player is not None and self._duration > 0:
            target = self._slider.value() / self.SLIDER_STEPS * self._duration
            self._player.seek(target, reference="absolute", precision="exact")
