from fpvcut.ui.player import format_time


def test_format_time():
    assert format_time(None) == "--:--.---"
    assert format_time(0) == "00:00.000"
    assert format_time(83.5) == "01:23.500"
