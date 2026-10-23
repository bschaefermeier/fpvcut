"""Laufwerke unter Windows: SD-Karte wiederfinden und sicher auswerfen.

Die Quelle eines Imports wird als Unterordner plus Erkennungsmerkmale des Laufwerks gemerkt
(Laufwerksbuchstabe, Bezeichnung, Seriennummer). Steckt die Karte das nächste Mal in einem anderen
Leser oder unter einem anderen Buchstaben, findet :func:`find_source` sie trotzdem, solange der
Unterordner darauf existiert.
"""

from __future__ import annotations

import ctypes
import string
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath

DRIVE_REMOVABLE = 2
IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class VolumeInfo:
    label: str
    serial: int


@dataclass
class ImportSource:
    """Gemerkter Importordner: Laufwerk und Pfad darauf (ohne Laufwerksbuchstaben)."""

    drive: str  # z. B. "E:\\"
    subfolder: str  # z. B. "DCIM\\100MEDIA"; leer = ganzes Laufwerk
    label: str = ""
    serial: int | None = None

    def path_on(self, drive: str) -> Path:
        return Path(drive) / self.subfolder

    @property
    def path(self) -> Path:
        return self.path_on(self.drive)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ImportSource | None:
        try:
            serial = data.get("serial")
            return cls(str(data["drive"]), str(data.get("subfolder", "")), str(data.get("label", "")),
                       int(serial) if serial is not None else None)
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def for_folder(cls, folder: str | Path) -> ImportSource:
        win = PureWindowsPath(folder)
        drive = win.anchor or str(Path(folder).anchor)
        subfolder = str(PureWindowsPath(*win.parts[1:])) if len(win.parts) > 1 else ""
        info = volume_info(drive)
        return cls(drive, subfolder, info.label if info else "", info.serial if info else None)


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def volume_info(drive: str) -> VolumeInfo | None:
    """Bezeichnung und Seriennummer des Datenträgers, ``None`` ohne Datenträger oder unter Linux/macOS."""
    if not IS_WINDOWS:
        return None
    label = ctypes.create_unicode_buffer(261)
    fs_name = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    ok = _kernel32().GetVolumeInformationW(
        ctypes.c_wchar_p(drive), label, len(label), ctypes.byref(serial), None, None, fs_name, len(fs_name))
    return VolumeInfo(label.value, serial.value) if ok else None


def mounted_drives() -> list[str]:
    """Alle Laufwerke, z. B. ``["C:\\", "E:\\"]``."""
    if not IS_WINDOWS:
        return []
    mask = _kernel32().GetLogicalDrives()
    return [f"{letter}:\\" for i, letter in enumerate(string.ascii_uppercase) if mask & (1 << i)]


def is_removable(drive: str) -> bool:
    return IS_WINDOWS and _kernel32().GetDriveTypeW(ctypes.c_wchar_p(drive)) == DRIVE_REMOVABLE


def find_source(
    source: ImportSource,
    drives: Callable[[], list[str]] = mounted_drives,
    info: Callable[[str], VolumeInfo | None] = volume_info,
    removable: Callable[[str], bool] = is_removable,
) -> Path | None:
    """Wo der gemerkte Importordner gerade liegt, ``None`` wenn die Karte nicht steckt.

    Vorrang hat dieselbe Karte (Seriennummer), dann eine Karte mit gleicher Bezeichnung, dann der
    gemerkte Laufwerksbuchstabe; Festplatten kommen nur über den gemerkten Buchstaben in Frage.
    """
    remembered = source.drive.upper()
    best: tuple[int, str] | None = None
    for drive in drives():
        is_remembered = drive.upper() == remembered
        if not (is_remembered or removable(drive)):
            continue
        volume = info(drive)
        if volume is None or not source.path_on(drive).is_dir():
            continue  # kein Datenträger im Leser oder Ordner fehlt
        if volume and source.serial is not None and volume.serial == source.serial:
            rank = 0
        elif volume and source.label and volume.label == source.label:
            rank = 1
        elif is_remembered:
            rank = 2
        else:
            rank = 3  # irgendein Wechseldatenträger mit passendem Ordner, z. B. eine zweite Karte
        if best is None or rank < best[0]:
            best = (rank, drive)
    return source.path_on(best[1]) if best else None


# --- Auswerfen -------------------------------------------------------------

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_FSCTL_LOCK_VOLUME = 0x00090018
_FSCTL_DISMOUNT_VOLUME = 0x00090020
_IOCTL_STORAGE_MEDIA_REMOVAL = 0x002D4804
_IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808


def eject(drive: str, lock_attempts: int = 20) -> None:
    """Datenträger sperren, abmelden und auswerfen (wie „Auswerfen“ im Explorer).

    Wirft :class:`OSError`, wenn das nicht geht, meist weil noch ein Programm Dateien darauf offen hat.
    """
    if not IS_WINDOWS:
        raise OSError("Ejecting is only supported on Windows")
    k32 = _kernel32()
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    k32.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                    ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    letter = drive.rstrip("\\/")
    handle = k32.CreateFileW(f"\\\\.\\{letter}", _GENERIC_READ | _GENERIC_WRITE,
                             _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())

    def control(code: int, data: bytes = b"") -> bool:
        returned = ctypes.c_uint32()
        buffer = ctypes.create_string_buffer(data, len(data)) if data else None
        return bool(k32.DeviceIoControl(handle, code, buffer, len(data), None, 0, ctypes.byref(returned), None))

    try:
        for _ in range(lock_attempts):
            if control(_FSCTL_LOCK_VOLUME):
                break
            time.sleep(0.25)
        else:
            raise ctypes.WinError(ctypes.get_last_error())
        if not control(_FSCTL_DISMOUNT_VOLUME):
            raise ctypes.WinError(ctypes.get_last_error())
        control(_IOCTL_STORAGE_MEDIA_REMOVAL, b"\x00")  # Entnahme erlauben
        # Manche Kartenleser können nicht auswerfen; abgemeldet ist die Karte trotzdem sicher.
        control(_IOCTL_STORAGE_EJECT_MEDIA)
    finally:
        k32.CloseHandle(handle)
