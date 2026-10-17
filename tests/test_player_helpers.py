from fpvcut.ui.player import format_time


def test_format_time():
    assert format_time(None) == "--:--.---"
    assert format_time(0) == "00:00.000"
    assert format_time(83.5) == "01:23.500"


def test_mpv_click_handler_fires_once_per_click():
    from fpvcut.ui.player import PlayerWidget

    hits = []

    class FakeSignal:
        def emit(self):
            hits.append(1)

    handler = PlayerWidget._on_mpv_key(FakeSignal())
    handler("dm", "MBTN_LEFT", "", None, None)  # gedrückt
    handler("um", "MBTN_LEFT", "", None, None)  # losgelassen
    handler("p-", "MBTN_LEFT_DBL", "", None, None)  # Doppelklick
    assert len(hits) == 2


def test_resolve_range():
    from fpvcut.core.marks import resolve_range

    assert resolve_range(None, None, 12.0) == (0, None)  # ganzes Video
    assert resolve_range(5.0, None, 9.5) == (5000, 9500)  # In gesetzt, F an späterer Stelle
    assert resolve_range(5.0, None, 3.0) == (5000, None)  # Position davor: bis zum Ende
    assert resolve_range(None, 8.0, 2.0) == (0, 8000)
    assert resolve_range(9.0, 4.0, None) == (4000, 9000)  # vertauscht
