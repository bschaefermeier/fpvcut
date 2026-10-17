"""Inhaltsbasierte Datei-ID, damit Favoriten Umbenennen und Verschieben überleben.

Statt die ganze Datei zu hashen (bei mehreren GB auf einer HDD sehr langsam), fließen die
Dateigröße und je ein Block vom Anfang, aus der Mitte und vom Ende ein.
"""

from __future__ import annotations

import os
from pathlib import Path

import xxhash

CHUNK_SIZE = 4 * 1024 * 1024


def fingerprint(path: str | os.PathLike[str], chunk_size: int = CHUNK_SIZE) -> str:
    size = os.path.getsize(path)
    h = xxhash.xxh3_128()
    h.update(size.to_bytes(8, "little"))
    with Path(path).open("rb") as f:
        if size <= 3 * chunk_size:
            h.update(f.read())
        else:
            for offset in (0, (size - chunk_size) // 2, size - chunk_size):
                f.seek(offset)
                h.update(f.read(chunk_size))
    return h.hexdigest()
