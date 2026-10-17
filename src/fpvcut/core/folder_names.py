"""Flugdatum und Spot aus Ordnernamen lesen.

Unterstützte Schreibweisen (Trenner ``_``, ``-``, ``.`` oder Leerzeichen):

- ``2026_08_28_Flugspot``  (Jahr zuerst, empfohlen)
- ``28_08_26_Flugspot``    (Tag, Monat, zweistelliges Jahr)
- ``Flugspot_28_08_26``    (Spot zuerst)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath

_SEP = r"[_\-. ]"
_YEAR_FIRST = re.compile(rf"^(\d{{4}}){_SEP}(\d{{1,2}}){_SEP}(\d{{1,2}})(?:{_SEP}+(.*))?$")
_DAY_FIRST = re.compile(rf"^(\d{{1,2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{2}}|\d{{4}})(?:{_SEP}+(.*))?$")
_SPOT_FIRST = re.compile(rf"^(.*?){_SEP}+(\d{{1,2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{2}}|\d{{4}})$")


@dataclass(frozen=True)
class FlightDay:
    folder_name: str
    date: date | None
    spot: str

    @property
    def label(self) -> str:
        if self.date is None:
            return self.folder_name
        return f"{self.date:%d.%m.%Y} · {self.spot}" if self.spot else f"{self.date:%d.%m.%Y}"

    @property
    def canonical_name(self) -> str | None:
        """Name im empfohlenen Schema ``YYYY_MM_DD_Spot`` (für den späteren Umbenennungs-Helfer)."""
        if self.date is None:
            return None
        return f"{self.date:%Y_%m_%d}_{self.spot}" if self.spot else f"{self.date:%Y_%m_%d}"


def _make_date(year: str, month: str, day: str) -> date | None:
    y = int(year)
    if y < 100:
        y += 2000
    try:
        return date(y, int(month), int(day))
    except ValueError:
        return None


def parse_folder_name(name: str) -> FlightDay:
    name = name.strip()
    if m := _YEAR_FIRST.match(name):
        d = _make_date(m.group(1), m.group(2), m.group(3))
        if d:
            return FlightDay(name, d, (m.group(4) or "").strip())
    if m := _DAY_FIRST.match(name):
        d = _make_date(m.group(3), m.group(2), m.group(1))
        if d:
            return FlightDay(name, d, (m.group(4) or "").strip())
    if m := _SPOT_FIRST.match(name):
        d = _make_date(m.group(4), m.group(3), m.group(2))
        if d:
            return FlightDay(name, d, m.group(1).strip())
    return FlightDay(name, None, name)


def flight_day_for(rel_path: str) -> FlightDay:
    """Flugtag einer Datei relativ zum Bibliotheksordner.

    Nimmt den nächstgelegenen Elternordner mit erkennbarem Datum, sonst den obersten Unterordner.
    Dateien direkt im Bibliotheksordner landen unter "Ohne Ordner".
    """
    parents = PurePath(rel_path).parts[:-1]
    if not parents:
        return FlightDay("Ohne Ordner", None, "")
    for folder in reversed(parents):
        day = parse_folder_name(folder)
        if day.date is not None:
            return day
    return parse_folder_name(parents[0])
