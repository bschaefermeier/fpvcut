"""Ausschnitte nach Favorit, Tags und Freitext filtern und sortieren."""

from __future__ import annotations

from datetime import date

from fpvcut.core.library import Clip, LibraryEntry


def clip_matches(
    clip: Clip, entry: LibraryEntry, tags: list[str], match_all: bool = False, text: str = "",
    favorites_only: bool = False,
) -> bool:
    if favorites_only and not clip.favorite:
        return False
    if tags:
        clip_tags = {t.lower() for t in clip.tags}
        wanted = [t.lower() for t in tags]
        found = [t in clip_tags for t in wanted]
        if not (all(found) if match_all else any(found)):
            return False
    if text:
        haystack = " ".join([entry.path.name, entry.flight_day.label, clip.note, *clip.tags]).lower()
        if not all(word in haystack for word in text.lower().split()):
            return False
    return True


def filter_clips(
    items: list[tuple[Clip, LibraryEntry]], tags: list[str], match_all: bool = False, text: str = "",
    favorites_only: bool = False,
) -> list[tuple[Clip, LibraryEntry]]:
    """Gefiltert und sortiert: neueste Flugtage zuerst, innerhalb eines Videos nach Zeit."""
    selected = [(c, e) for c, e in items if clip_matches(c, e, tags, match_all, text, favorites_only)]

    def key(item: tuple[Clip, LibraryEntry]):
        clip, entry = item
        day = entry.flight_day.date or date.min
        return (-day.toordinal(), entry.rel_path.lower(), clip.in_ms)

    return sorted(selected, key=key)


def clip_duration(clip: Clip, entry: LibraryEntry) -> float | None:
    end = clip.out_s if clip.out_s is not None else entry.duration
    return None if end is None else max(end - clip.in_s, 0.0)
