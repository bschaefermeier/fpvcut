from datetime import date

import pytest

from fpvcut.core.folder_names import flight_day_for, parse_folder_name


@pytest.mark.parametrize(
    ("name", "expected_date", "spot"),
    [
        ("2026_08_28_Flugspot", date(2026, 8, 28), "Flugspot"),
        ("2026-08-28 Bikepark Ost", date(2026, 8, 28), "Bikepark Ost"),
        ("28_08_26_Flugspot", date(2026, 8, 28), "Flugspot"),
        ("28.08.26_Flugspot", date(2026, 8, 28), "Flugspot"),
        ("Flugspot_28_08_26", date(2026, 8, 28), "Flugspot"),
        ("Alter_Steinbruch_03_07_25", date(2025, 7, 3), "Alter_Steinbruch"),
        ("2026_08_28", date(2026, 8, 28), ""),
        ("2026-10-17_Flugspot", date(2026, 10, 17), "Flugspot"),
        ("Sonstiges", None, "Sonstiges"),
        ("31_02_26_Flugspot", None, "31_02_26_Flugspot"),  # ungültiges Datum
    ],
)
def test_parse_folder_name(name, expected_date, spot):
    day = parse_folder_name(name)
    assert day.date == expected_date
    assert day.spot == spot


def test_canonical_name_sorts_by_date():
    names = ["28_08_26_Wiese", "Wald_03_07_25", "2026_01_15_Halle"]
    canonical = sorted(parse_folder_name(n).canonical_name for n in names)
    assert canonical == ["2025-07-03_Wald", "2026-01-15_Halle", "2026-08-28_Wiese"]


def test_flight_day_for_uses_nearest_dated_folder():
    assert flight_day_for("2026/28_08_26_Wiese/DJI_0001.mp4").date == date(2026, 8, 28)
    assert flight_day_for("Wiese_28_08_26/raw/clip.mp4").date == date(2026, 8, 28)
    assert flight_day_for("Sonstiges/clip.mp4").label == "Sonstiges"
    assert flight_day_for("clip.mp4").label == "Ohne Ordner"
