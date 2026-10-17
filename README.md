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
  (`2026-08-28_Spot`, `2026_08_28_Spot`, `28_08_26_Spot` oder `Spot_28_08_26`)
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
- Clips hinzufügen: Favoriten aus dem Favoriten-Reiter oder ganze Videos (auch ganze Flugtage) aus der
  Bibliothek in die Timeline ziehen (mehrere mit Strg/Shift), oder auswählen und E drücken. E nimmt auch einen mit I/O markierten Ausschnitt direkt
  aus dem Player, ohne ihn als Favorit zu speichern. Rechtsklick auf einen Favoriten geht ebenfalls
- Bearbeiten: Clip ziehen = Reihenfolge ändern, Kante ziehen = trimmen, S = am roten Abspielkopf
  teilen, Entf = ausgewählten Clip (oder die Musik) entfernen, Strg+Z / Strg+Y = rückgängig/wiederholen.
  Mausrad = zoomen (um die Mausposition), Shift+Mausrad = seitlich scrollen.
  Strg+←/→ = an den Anfang bzw. ans Ende der Timeline springen.
  Zwischen zwei Clips trimmt die Kante den ausgewählten (gelben) Clip. Über den Favoriten hinaus
  verlängerte Teile sind hell schraffiert
- Musik: "♪ Musik …" wählt eine Audiodatei. Regler für Originalton und Musik. "Ausblenden" macht
  die Musik in den letzten Sekunden der Timeline langsam leiser bis zur Stille (0 s = hartes Ende)
- Vorschau: "▶ Timeline abspielen" oder P spielt die Timeline direkt aus den Quelldateien ab
  (mpv-EDL, kein Rendern). Ist kein Video geöffnet, startet auch Leertaste/Play die Timeline.
  Doppelklick auf einen Clip spielt ab dort, ein Klick in die Timeline zeigt das Bild an dieser Stelle.
  Clips ohne Ton werden mit Stille aufgefüllt, damit der Ton synchron bleibt.
  Änderungen während der Vorschau werden sofort übernommen. Ein Video aus der Bibliothek öffnen
  verlässt die Vorschau
- Die Timeline wird automatisch gespeichert (`%APPDATA%\FPVCut\timeline.json`) und beim Start wieder
  geladen. Timeline → Speichern unter/Öffnen für weitere Projekte. Clips hängen am Fingerprint und
  finden umbenannte Videos wieder

Meilenstein 6 (Rendern):

- "Rendern …" in der Timeline-Leiste oder Strg+R
- Profile: **Original** (H.265, sehr hohe Qualität), **Web** (H.264, läuft überall, kleiner),
  **Archiv** (H.265 10 Bit). Auflösung, Bildrate und Qualität lassen sich im Dialog anpassen;
  "Wie Quelle" nimmt das Format, das in der Timeline am längsten vorkommt
- Encodiert mit NVENC auf der GPU, wenn der Systemcheck es gefunden hat, sonst auf der CPU
- Clips mit anderer Auflösung werden eingepasst (schwarze Ränder statt Verzerrung), andere
  Bildraten angeglichen, Clips ohne Ton bekommen Stille, die Musik wird wie in der Vorschau gemischt
- Fortschritt mit Restzeit, Abbrechen löscht die halbfertige Datei. Standardordner:
  `Videos\FPVCut`, danach der zuletzt benutzte

Meilenstein 7 (Umbenennungs-Helfer):

- Datei → "Ordner ins Schema umbenennen …" schlägt für alle Flugtag-Ordner den Namen
  `JJJJ-MM-TT_Spot` vor, z. B. `2026-10-17_Flugspot` (aus `28_08_26_Spot`, `Spot_28_08_26`,
  `2026_08_28_Spot`, `28.08.26 Spot` usw.)
- Vorschau alt → neu; neue Namen lassen sich per Doppelklick ändern. Eindeutige Fälle sind
  vorausgewählt. **Prüfen** (gelb): Datum in der Zukunft, sehr alt oder auch anders herum lesbar
  (z. B. `12_08_15`). **Konflikt** (rot): Zielname gibt es schon oder mehrere Ordner bekämen ihn.
  **Kein Datum**: Video-Ordner ohne erkennbares Datum, Name von Hand eintragen
- Unterordner eines Flugtags (z. B. `…/raw`) bleiben, wie sie sind
- Erst nach Bestätigung wird umbenannt; die Bibliothek übernimmt die neuen Pfade direkt (kein
  Neu-Scan), Favoriten und Timeline bleiben erhalten. "Rückgängig" nimmt die Umbenennung zurück,
  ein Protokoll alt → neu liegt im App-Datenordner unter `umbenannt\`

Meilenstein 8 (Farbkorrektur):

- Clip in der Timeline anklicken, rechts den Reiter **Farbe** öffnen: Helligkeit, Kontrast,
  Sättigung, Gamma und Farbtemperatur per Regler, dazu optional eine 3D-LUT (`.cube`, z. B. um
  D-Log- oder Flat-Aufnahmen in normale Farben umzuwandeln; die LUT wirkt vor den Reglern)
- Die Vorschau springt in den Clip und zeigt das Ergebnis sofort; ein Doppelklick auf einen Wert
  setzt ihn zurück. "Auf alle Clips übertragen" nimmt dieselbe Korrektur für die ganze Timeline
- Korrigierte Clips haben einen orangen Strich am unteren Rand. Rückgängig (Strg+Z) gilt auch hier
- Vorschau und Render nutzen dieselben ffmpeg-Filter (`lut3d`, `colortemperature`, `eq`), der
  Export sieht also aus wie die Vorschau

## Wo liegen meine Daten?

Bibliothek, Favoriten, Tags und Gesichtet-Status stehen in `%APPDATA%\FPVCut\library.sqlite`, die
Timeline in `timeline.json` daneben. Die Videos selbst werden nie verändert (außer beim Umbenennen
von Ordnern auf Wunsch). Der Ordner bleibt beim Neuinstallieren von FPVCut oder der `.venv` erhalten.

- **Automatische Sicherung:** Beim Start und beim Beenden schreibt FPVCut die Favoriten, Tags und den
  Gesichtet-Status nach `%APPDATA%\FPVCut\sicherungen\favoriten_JJJJ-MM-TT.json` (die letzten 30 Tage).
- **Von Hand:** Datei → "Favoriten exportieren …" speichert dasselbe an einen beliebigen Ort, z. B.
  auf die Videoplatte oder ein NAS. "Favoriten importieren …" liest eine Sicherung wieder ein; schon
  vorhandene Favoriten werden nicht verdoppelt.
- **Neuanfang:** Startet FPVCut mit einer leeren Bibliothek und findet eine Sicherung, bietet es die
  Wiederherstellung an. Weil alles am Fingerprint hängt, funktioniert das auch vor dem ersten Scan.

## Installation (Windows)

Unter [Releases](https://github.com/bschaefermeier/fpvcut/releases) das neueste
`FPVCut-…-windows.zip` herunterladen, irgendwohin entpacken (z. B. nach
`Dokumente\FPVCut`) und `FPVCut.exe` starten. libmpv und ffmpeg sind dabei, sonst muss nichts
installiert werden. Beim ersten Start warnt Windows SmartScreen evtl., weil die .exe nicht signiert
ist: "Weitere Informationen" → "Trotzdem ausführen".

Die Daten liegen wie bei der Entwicklerversion in `%APPDATA%\FPVCut`, beide Varianten teilen sie
sich. Ein Update ist: alten Programmordner löschen, neues ZIP entpacken.

Mitgeliefert werden ffmpeg von [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) und
libmpv von [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake), beide
unter GPL.

## Einrichtung zum Entwickeln (Windows)

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

   uv nimmt dabei sein eigenes Python (`python-preference = "only-managed"` in `pyproject.toml`),
   nicht das aus dem Microsoft Store. Mit dem Store-Python zeigt die Taskleiste das Python-Icon
   statt des FPVCut-Icons. Wer die `.venv` noch mit dem Store-Python angelegt hat, löscht sie
   einmal und ruft `uv sync` erneut auf.

Der Ordner `vendor/` ist in `.gitignore`, die DLLs landen also nicht im Repository.

## Entwicklung

```powershell
uv run pytest
```

**Neue Version veröffentlichen:** Version in `src/fpvcut/__init__.py` und `pyproject.toml` erhöhen,
Abschnitt oben in `CHANGELOG.md` ergänzen, mergen und einen Tag setzen (`v1.0.0-rc2`, `v1.0.0`).
Der Workflow `.github/workflows/windows-build.yml` baut dann auf GitHub die `FPVCut.exe`, prüft sie
mit `FPVCut.exe --selbsttest bericht.txt` und hängt das ZIP an das Release (Tags mit Bindestrich
werden als Vorabversion markiert). Unter "Actions" lässt er sich auch ohne Tag starten, das ZIP liegt
dann als Artefakt am Lauf.

Lokal bauen (libmpv und ffmpeg müssen in `vendor/` liegen):

```powershell
uv run --with pyinstaller pyinstaller --noconfirm packaging/fpvcut.spec   # Ergebnis: dist\FPVCut\
```

Das Icon `src/fpvcut/resources/fpvcut.ico` entsteht aus dem SVG mit
`uv run python packaging/make_icon.py`.

Aufbau:

```
src/fpvcut/
  core/      ohne UI, testbar: ffmpeg-Erkennung, ffprobe, Fingerprints, Ordnernamen, Datenbank, Scanner
  timeline/  Timeline-Modell, Projektdatei, EDL für die Vorschau
  render/    Render-Profile und ffmpeg-Befehl
  ui/        PySide6-Oberfläche (Hauptfenster, Bibliothek, Favoriten, Player, Timeline)
tests/
```
