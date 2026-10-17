# FPVCut

Schlanke Desktop-Software zum Sichten, Markieren und Schneiden von FPV-Videos.
Python + PySide6 als Oberfläche, libmpv als Player, ffmpeg (mit NVIDIA NVENC) zum Rendern.

Der Gesamtplan mit allen Meilensteinen liegt in [docs/plan.md](docs/plan.md).

## Stand

Meilenstein 1 (Grundgerüst):

- Fenster mit eingebettetem mpv-Player: Video öffnen (Strg+O), Leertaste = Play/Pause,
  ←/→ = ein Frame, Shift+←/→ = 1 s, J/L = 5 s, Zeitleiste zum Springen,
  Klick aufs Video = Play/Pause, Doppelklick oder F11 = Vollbild (Esc beendet)
- Systemcheck (Hilfe → Systemcheck, Status unten rechts): findet ffmpeg/ffprobe und prüft per
  Testencode, welche Encoder wirklich funktionieren (NVENC wird von ffmpeg auch ohne passende GPU
  gelistet, daher der Test)

Meilenstein 2 (Bibliothek):

- Datei → Bibliotheksordner hinzufügen (z. B. `E:\FPV_Videos`); beim Start und mit F5 wird neu gescannt
- Videos gruppiert nach Flugtag, neueste oben. Das Datum kommt aus dem Ordnernamen
  (`2026_08_28_Spot`, `28_08_26_Spot` oder `Spot_28_08_26`)
- Neue, noch nicht gesichtete Videos sind blau mit ● markiert; "Nur neue" blendet den Rest aus.
  Ein Video gilt als gesichtet, sobald es geöffnet wird. Per Rechtsklick lassen sich auch mehrere
  Videos (Strg/Shift+Klick) oder ganze Flugtage auf einmal markieren
- Jede Datei bekommt einen Fingerprint (Größe + je 4 MB von Anfang, Mitte und Ende). Umbenannte oder
  verschobene Ordner werden dadurch wiedererkannt, der Sichtungsstatus bleibt erhalten. Gelöschte
  Dateien werden als "fehlt" angezeigt, nicht vergessen
- Datenbank: `%APPDATA%\FPVCut\library.sqlite`

Meilenstein 3 (Sichten, Favoriten, Tags):

- I = In-Punkt, O = Out-Punkt, F = Ausschnitt als Favorit speichern, Shift+F = ganzes Video,
  Esc = Auswahl aufheben. Ohne Out-Punkt reicht der Ausschnitt bis zur aktuellen Position
- Beim Speichern Tags vergeben (mit Komma getrennt oder per Klick auf bekannte Tags) plus optionale Notiz
- Gelbe Balken unter der Zeitleiste zeigen gespeicherte Favoriten, blau die aktuelle Auswahl
- Seitenleiste rechts: Favoriten des Videos (Doppelklick = in Schleife abspielen, Rechtsklick =
  bearbeiten/löschen, Entf = löschen) und Metadaten (Auflösung, fps, Codec, Bitrate, Flugtag …)
- Videos mit Favoriten tragen in der Bibliothek ein ★ mit der Anzahl
- Favoriten hängen am Fingerprint und überleben Umbenennen und Verschieben

Meilenstein 4 (Favoriten-Browser):

- Reiter "Favoriten" neben der Bibliothek: alle Favoriten aller Videos, neueste Flugtage oben
- Tags anklicken filtert die Liste; bei mehreren Tags wählbar, ob einer reicht oder alle passen müssen
- Suchfeld durchsucht Dateiname, Flugtag, Notiz und Tags (mehrere Wörter müssen alle vorkommen)
- Unten steht, wie viele Favoriten passen und wie lang sie zusammen sind
- Doppelklick öffnet das Video und spielt den Favoriten direkt in Schleife ab; Rechtsklick =
  bearbeiten/löschen, Entf = löschen

Meilenstein 5 (Timeline):

- Timeline unter dem Player mit Videospur und Musikspur
- Clips hinzufügen: Favoriten aus dem Favoriten-Reiter in die Timeline ziehen (auch mehrere mit
  Strg/Shift), oder auswählen und E drücken. E nimmt auch einen mit I/O markierten Ausschnitt direkt
  aus dem Player, ohne ihn als Favorit zu speichern. Rechtsklick auf einen Favoriten geht ebenfalls
- Bearbeiten: Clip ziehen = Reihenfolge ändern, Kante ziehen = trimmen, S = am roten Abspielkopf
  teilen, Entf = ausgewählten Clip (oder die Musik) entfernen, Strg+Z / Strg+Y = rückgängig/wiederholen
- Musik: "♪ Musik …" wählt eine Audiodatei. Regler für Originalton und Musik, Ausblenden am Ende
- Vorschau: "▶ Timeline abspielen" oder P spielt die Timeline direkt aus den Quelldateien ab
  (mpv-EDL, kein Rendern). Doppelklick auf einen Clip spielt ab dort, Klick ins Lineal springt.
  Änderungen während der Vorschau werden sofort übernommen. Ein Video aus der Bibliothek öffnen
  verlässt die Vorschau
- Die Timeline wird automatisch gespeichert (`%APPDATA%\FPVCut\timeline.json`) und beim Start wieder
  geladen. Timeline → Speichern unter/Öffnen für weitere Projekte. Clips hängen am Fingerprint und
  finden umbenannte Videos wieder

## Einrichtung unter Windows

1. **uv** installieren (Paketmanager für Python):
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. **ffmpeg** mit NVENC: z. B. den "full"-Build von <https://www.gyan.dev/ffmpeg/builds/> oder
   `winget install Gyan.FFmpeg`. Entweder in den PATH, oder `ffmpeg.exe`/`ffprobe.exe` nach
   `vendor/ffmpeg/` legen.
3. **libmpv**: `mpv-dev-x86_64-…7z` von <https://github.com/shinchiro/mpv-winbuild-cmake/releases>
   herunterladen und `libmpv-2.dll` nach `vendor/mpv/` entpacken (alternativ Ordner per
   Umgebungsvariable `FPVCUT_MPV_DIR` angeben).
4. Starten:

   ```powershell
   uv sync
   uv run fpvcut                      # oder: uv run fpvcut E:\FPV_Videos\...\clip.mp4
   ```

Der Ordner `vendor/` ist in `.gitignore`, die DLLs landen also nicht im Repository.

## Entwicklung

```powershell
uv run pytest
```

Aufbau:

```
src/fpvcut/
  core/      ohne UI, testbar: ffmpeg-Erkennung, ffprobe, Fingerprints, Ordnernamen, Datenbank, Scanner
  timeline/  Timeline-Modell, Projektdatei, EDL für die Vorschau
  ui/        PySide6-Oberfläche (Hauptfenster, Bibliothek, Favoriten, Player, Timeline)
tests/
```
