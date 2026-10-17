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
