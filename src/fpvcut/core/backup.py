"""Favoriten, Tags und Gesichtet-Status als JSON sichern und wieder einlesen.

Alles hängt am Fingerprint, nicht am Pfad: Eine Sicherung lässt sich deshalb auch in eine
frische Bibliothek einlesen, in der die Videos noch gar nicht gescannt sind. Die Videos
werden dann mit ihren Metadaten angelegt; der nächste Scan findet sie per Fingerprint
wieder und ergänzt nur den Fundort.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fpvcut.core.library import Library

FORMAT = "fpvcut-favoriten"
VERSION = 1
KEEP_DAILY = 30  # so viele Tagessicherungen bleiben liegen
_MEDIA_FIELDS = ("size", "duration", "width", "height", "fps", "vcodec", "bit_depth", "acodec", "probe_json",
                 "first_seen", "reviewed_at")


@dataclass
class ImportResult:
    media_added: int = 0  # Videos, die die Bibliothek noch nicht kannte
    clips_added: int = 0
    clips_skipped: int = 0  # schon vorhanden (gleicher Ausschnitt)
    reviewed: int = 0


def export_data(library: Library) -> dict:
    """Alle Videos mit Favoriten oder Gesichtet-Status, samt Metadaten und letztem Fundort."""
    conn = library.conn
    rows = conn.execute(
        """SELECT m.*, (SELECT r.path || '/' || p.rel_path FROM media_path p JOIN root_folder r ON r.id = p.root_id
                        WHERE p.media_id = m.id ORDER BY p.missing, p.last_seen DESC LIMIT 1) AS last_path
           FROM media_file m
           WHERE m.reviewed_at IS NOT NULL OR EXISTS (SELECT 1 FROM clip c WHERE c.media_id = m.id)
           ORDER BY m.id"""
    ).fetchall()
    media = []
    for row in rows:
        clips = []
        for clip in conn.execute("SELECT * FROM clip WHERE media_id = ? ORDER BY in_ms, id", (row["id"],)):
            tags = [t[0] for t in conn.execute(
                "SELECT t.name FROM clip_tag ct JOIN tag t ON t.id = ct.tag_id WHERE ct.clip_id = ? ORDER BY t.name",
                (clip["id"],))]
            clips.append({"in_ms": clip["in_ms"], "out_ms": clip["out_ms"], "rating": clip["rating"],
                          "note": clip["note"], "created_at": clip["created_at"], "tags": tags})
        media.append({"fingerprint": row["fingerprint"], "last_path": row["last_path"],
                      **{f: row[f] for f in _MEDIA_FIELDS}, "clips": clips})
    return {"format": FORMAT, "version": VERSION, "exported_at": time.time(), "media": media}


def export_to(library: Library, path: Path) -> int:
    """Sicherung schreiben (atomar). Gibt die Zahl der Favoriten zurück."""
    data = export_data(library)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return sum(len(m["clips"]) for m in data["media"])


def import_data(library: Library, data: dict) -> ImportResult:
    """Sicherung in die Bibliothek übernehmen; Vorhandenes bleibt, Doppeltes wird übersprungen."""
    if data.get("format") != FORMAT:
        raise ValueError("Das ist keine FPVCut-Sicherung der Ausschnitte.")
    if data.get("version", 0) > VERSION:
        raise ValueError("Die Sicherung stammt aus einer neueren FPVCut-Version.")
    result = ImportResult()
    conn = library.conn
    with conn:
        for media in data["media"]:
            row = conn.execute("SELECT id, reviewed_at FROM media_file WHERE fingerprint = ?",
                               (media["fingerprint"],)).fetchone()
            if row is None:
                fields = ["fingerprint", *_MEDIA_FIELDS]
                values = [media["fingerprint"], *(media.get(f) for f in _MEDIA_FIELDS)]
                values[fields.index("first_seen")] = media.get("first_seen") or time.time()
                cur = conn.execute(
                    f"INSERT INTO media_file ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})", values)
                media_id = cur.lastrowid
                result.media_added += 1
                result.reviewed += media.get("reviewed_at") is not None
            else:
                media_id = row["id"]
                if row["reviewed_at"] is None and media.get("reviewed_at") is not None:
                    conn.execute("UPDATE media_file SET reviewed_at = ? WHERE id = ?", (media["reviewed_at"], media_id))
                    result.reviewed += 1
            for clip in media.get("clips", []):
                existing = conn.execute(
                    "SELECT id FROM clip WHERE media_id = ? AND in_ms = ? AND out_ms IS ?",
                    (media_id, clip["in_ms"], clip["out_ms"])).fetchone()
                if existing is not None:
                    clip_id = existing["id"]
                    result.clips_skipped += 1
                    if clip.get("rating"):  # Favorit-Markierung aus der Sicherung übernehmen
                        conn.execute("UPDATE clip SET rating = ? WHERE id = ? AND rating IS NULL",
                                     (clip["rating"], clip_id))
                else:
                    cur = conn.execute(
                        "INSERT INTO clip (media_id, in_ms, out_ms, rating, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (media_id, clip["in_ms"], clip["out_ms"], clip.get("rating"), clip.get("note", ""),
                         clip.get("created_at") or time.time()))
                    clip_id = cur.lastrowid
                    result.clips_added += 1
                for name in clip.get("tags", []):  # Tags werden ergänzt, nie entfernt
                    conn.execute("INSERT OR IGNORE INTO tag (name) VALUES (?)", (name,))
                    tag_id = conn.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()[0]
                    conn.execute("INSERT OR IGNORE INTO clip_tag (clip_id, tag_id) VALUES (?, ?)", (clip_id, tag_id))
    return result


def import_from(library: Library, path: Path) -> ImportResult:
    return import_data(library, json.loads(path.read_text(encoding="utf-8")))


def daily_backup(library: Library, folder: Path, now: datetime | None = None) -> Path | None:
    """Tagessicherung ``favoriten_JJJJ-MM-TT.json`` schreiben, ältere als die letzten 30 löschen.

    Eine leere Bibliothek überschreibt keine Sicherung, damit ein Neuanfang nichts kaputt macht.
    """
    now = now or datetime.now()
    if not library.conn.execute(
        "SELECT 1 FROM clip UNION ALL SELECT 1 FROM media_file WHERE reviewed_at IS NOT NULL LIMIT 1"
    ).fetchone():
        return None
    path = folder / f"favoriten_{now:%Y-%m-%d}.json"
    export_to(library, path)
    for old in sorted(folder.glob("favoriten_*.json"), reverse=True)[KEEP_DAILY:]:
        old.unlink(missing_ok=True)
    return path


def latest_backup(folder: Path) -> Path | None:
    backups = sorted(folder.glob("favoriten_*.json"))
    return backups[-1] if backups else None
