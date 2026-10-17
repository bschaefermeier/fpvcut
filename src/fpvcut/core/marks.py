"""In/Out-Punkte in einen Favoriten-Ausschnitt übersetzen."""

from __future__ import annotations

MIN_CLIP_S = 0.1


def resolve_range(
    in_s: float | None, out_s: float | None, position_s: float | None
) -> tuple[int, int | None]:
    """Gibt ``(in_ms, out_ms)`` zurück; ``out_ms`` ``None`` heißt "bis zum Ende".

    - weder In noch Out: ganzes Video
    - nur In: bis zur aktuellen Position, falls die dahinter liegt, sonst bis zum Ende
    - nur Out: vom Anfang bis Out
    """
    if in_s is None and out_s is None:
        return 0, None
    if out_s is None:
        if position_s is not None and position_s >= in_s + MIN_CLIP_S:
            out_s = position_s
        else:
            return round(in_s * 1000), None
    if in_s is None:
        in_s = 0.0
    if out_s < in_s:
        in_s, out_s = out_s, in_s
    return round(in_s * 1000), round(out_s * 1000)
