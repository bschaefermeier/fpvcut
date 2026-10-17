# FPV-Schnitt: Umsetzungsplan (Entwurf zur Diskussion)

Stand: 17.10.2026 · Status: von Bastian freigegeben (PySide6, NVIDIA, Repo gewünscht)

## 1. Ziel in einem Satz

Eine schlanke Windows-Desktop-App, die die FPV-Sammlung indiziert, neue Flugtage hervorhebt, das Markieren und Taggen von Ausschnitten schnell macht und aus Favoriten über eine einfache Timeline ein fertiges Video (mit Musik, Profilen und GPU-Encoding) rendert. Die Bibliothek mit Favoriten und Tags ist der eigentliche Mehrwert gegenüber DaVinci Resolve und Co.

## 2. Technik-Empfehlung

### Empfohlener Stack

| Baustein | Wahl | Warum |
|---|---|---|
| Sprache | **Python 3.12+** | Deine Lieblingssprache, reicht für eine App, die die schwere Arbeit an ffmpeg/mpv abgibt |
| UI | **PySide6 (Qt 6)** | Echte Desktop-App: Drag & Drop, Tastenkürzel, eigene Timeline-Zeichnung (`QGraphicsView`), Docking-Panels |
| Wiedergabe | **libmpv** über `python-mpv`, eingebettet in ein Qt-Widget | Spielt praktisch jeden Codec (H.265, 10 Bit, hohe FPS) mit GPU-Decoding, framegenaues Springen, Geschwindigkeit, Audio. Kann über EDL eine Folge von Ausschnitten am Stück abspielen (= Timeline-Vorschau ohne Rendern) und Filter live anwenden (= Farbkorrektur-Vorschau) |
| Analyse/Render | **ffprobe / ffmpeg** als Subprozess | Metadaten, Thumbnails, Rendern; GPU-Encoder NVENC (NVIDIA), AMF (AMD) oder QSV (Intel) |
| Datenbank | **SQLite** (über `sqlite3` oder SQLModel) | Eine Datei, kein Server, robust, schnell bei zehntausenden Clips |
| Hashing | **xxHash** (`xxhash`) oder BLAKE3 | Sehr schnell, für Wiedererkennung ausreichend (siehe Abschnitt 4) |
| Projektdateien | JSON (pydantic-Modelle) | Timeline-Projekte lesbar, versionierbar |
| Paketierung | `uv` für die Entwicklung, später PyInstaller für eine .exe | |

### Warum nicht Streamlit

Streamlit ist super für Dashboards, passt aber schlecht zu einem Schnittprogramm:

- Jede Interaktion lässt das ganze Skript neu laufen. Ein Player, der beim Klick auf "Tag hinzufügen" neu lädt und die Position verliert, nervt beim Sichten sofort.
- Keine Timeline mit Drag & Drop, kein Trimmen an Clip-Kanten, kaum Tastenkürzel (I/O für In/Out, J/K/L, Pfeiltasten frameweise). Das müsste man alles als eigene JavaScript-Komponente bauen, dann ist man faktisch bei einem Web-Frontend.
- Video läuft über den Browser-Player: Dateien werden über den Streamlit-Server gestreamt, H.265 und 10 Bit laufen je nach Browser/GPU nicht, framegenaues Steuern ist nicht möglich.

### Betrachtete Alternativen

| Option | Pro | Contra |
|---|---|---|
| **PySide6 + mpv + ffmpeg** (Empfehlung) | Alles Python, beste Codec-Unterstützung, echtes Desktop-Gefühl | Qt hat eine Lernkurve; Timeline-Widget selbst bauen |
| Python-Backend (FastAPI) + Web-UI (Svelte/React) | Schöne UIs, viele fertige Timeline-Bausteine | Zwei Sprachen; Browser-Player kann H.265/10 Bit oft nicht, also Proxy-Dateien nötig |
| Tauri/Electron + TypeScript | Moderne UI, gute Paketierung | Kein Python; gleiches Codec-Problem im Webview |
| C# / WPF oder Avalonia | Sehr gute Windows-Integration | Neue Sprache für dich |
| Bestehende Tools (DaVinci Resolve, Kdenlive, Shotcut) | Können Schnitt und Farbe bereits | Keine auf FPV zugeschnittene Sammlung/Favoriten-Verwaltung; schwergewichtig |

Hybrid-Idee für später: Die App kann Favoriten auch als EDL/XML für DaVinci Resolve exportieren, falls du mal aufwendiger schneiden willst.

## 3. Ordnerschema `YYYY-MM-DD_Flugspot`

- **Ja, das sortiert korrekt chronologisch**, solange Jahr vierstellig und Monat/Tag immer zweistellig (mit führender Null) sind. Explorer sortiert dann alphabetisch = zeitlich.
- Mehrere Flüge am selben Tag sortieren danach alphabetisch nach Spot-Namen. Wer die Reihenfolge innerhalb des Tages braucht, hängt z. B. `_1`, `_2` an.
- Entschieden: Datum im ISO-Format mit Bindestrich (`2026-08-28_Flugspot`), Spot mit Unterstrich abgetrennt. Die alte Variante `2026_08_28_Flugspot` wird weiterhin erkannt.
- Die App erkennt alle drei Varianten (`DD_MM_YY_Spot`, `Spot_DD_MM_YY`, `YYYY_MM_DD_Spot`) per Regex und leitet daraus Flugdatum und Spot ab.
- **Umbenennungs-Helfer** (eigener Meilenstein): Die App schlägt für alle Ordner den neuen Namen vor, zeigt eine Vorschau (alt → neu), markiert unklare Fälle (z. B. ungültiges Datum) und benennt erst nach Bestätigung um. Dank Fingerprints (Abschnitt 4) gehen dabei keine Favoriten verloren.

## 4. Wiedererkennung von Dateien (Favoriten überleben Umbenennen/Verschieben)

**Grundidee:** Jede Videodatei bekommt eine inhaltsbasierte ID. Der Pfad ist nur ein zuletzt gesehener Fundort. Favoriten, Tags und Timeline-Clips hängen an der ID, nie am Pfad.

**Fingerprint statt Voll-Hash:** Einen kompletten SHA-256 über tausende Dateien à mehrere GB zu rechnen dauert auf einer HDD Stunden. Für die Wiedererkennung reicht:

```
fingerprint = xxh3_128( dateigröße + erste 4 MB + 4 MB aus der Mitte + letzte 4 MB )
```

Das kostet pro Datei nur Millisekunden, und eine Kollision zwischen zwei verschiedenen Videos ist praktisch ausgeschlossen (Größe plus Anfang, Mitte und Ende müssten identisch sein). Optional kann im Hintergrund ein Voll-Hash nachberechnet werden, um echte Duplikate sicher zu erkennen.

**Ablauf beim Scan (z. B. beim Start):**

1. Alle Videodateien im Wurzelordner auflisten (`os.scandir`, rekursiv).
2. Ist der Pfad bekannt und haben sich Größe und Änderungszeit nicht geändert, wird nichts neu berechnet.
3. Sonst Fingerprint berechnen:
   - Fingerprint bekannt, alter Pfad existiert nicht mehr → **verschoben/umbenannt**, Pfad aktualisieren.
   - Fingerprint bekannt, alter Pfad existiert noch → **Duplikat**, als zweiter Fundort speichern.
   - Fingerprint unbekannt → **neue Datei**, ffprobe-Metadaten und Thumbnail erzeugen, als "neu" markieren.
4. Bekannte Dateien, die nirgends mehr gefunden werden, gelten als **fehlend** (nicht gelöscht). Favoriten bleiben erhalten und tauchen wieder auf, sobald die Datei zurück ist, z. B. wenn eine externe Platte wieder angesteckt wird.

**Wo liegt die Datenbank?** Standard: `%APPDATA%\FPVCut\library.sqlite`. Zusätzlich exportiert die App Favoriten/Tags regelmäßig als JSON-Backup, damit nichts an einer einzigen Datei hängt.

## 5. Funktionen und Datenmodell

### Bibliothek und "Neu"-Erkennung

- Einen oder mehrere Wurzelordner hinzufügen (z. B. `E:\FPV_Videos`).
- Scan beim Start und auf Knopfdruck; optional Live-Überwachung mit `watchdog`.
- Ansicht gruppiert nach Flugtag (aus dem Ordnernamen), neueste oben. Neue, noch nicht gesichtete Videos bekommen ein Badge und einen eigenen Bereich "Neu seit letztem Start". Ein Video gilt als gesichtet, sobald du es angesehen oder abgehakt hast.
- Thumbnails/Filmstreifen werden per ffmpeg erzeugt und gecacht.

### Sichten, Markieren, Taggen

- Player mit Ton, Tastenkürzeln (Leertaste, J/K/L, Pfeil = 1 Frame, Shift+Pfeil = 1 s, I/O = In/Out-Punkt, F = Favorit speichern).
- Favorit = Ausschnitt (In/Out) oder ganzes Video, mit Tags (frei, mit Autovervollständigung), optional Sterne-Bewertung und Notiz.
- Metadaten-Panel: Auflösung, FPS, Codec, Bitrate, Dauer, Farbtiefe, Audio, Dateigröße, Pfad, Flugtag/Spot.
- Später: DJI-OSD-`.srt`-Dateien (Höhe, Geschwindigkeit, Signal) einlesen und anzeigen, falls deine Brille die schreibt.

### Favoriten-Browser

- Liste/Kachelansicht aller Favoriten, filterbar nach Tags (UND/ODER), Flugtag, Spot, Bewertung, Dauer.
- Hover- oder Klick-Vorschau des Ausschnitts.

### Timeline

- Eine Videospur, eine Musikspur (später mehr Spuren möglich).
- Favoriten per Drag & Drop hinein, Reihenfolge per Drag ändern.
- Trimmen an Anfang/Ende durch Ziehen der Clip-Kanten; Schneiden in der Mitte = Teilen (S) und Teilstück löschen.
- Lautstärke für Original-Ton und Musik, Ein-/Ausblenden.
- Vorschau: mpv spielt die Timeline als EDL direkt aus den Quelldateien ab, ohne vorher zu rendern.

### Rendern und Profile

ffmpeg baut aus der Timeline einen `filter_complex` (trim/atrim → scale/fps angleichen → concat → Musik mischen) und encodiert mit GPU, wenn verfügbar. Fortschritt wird aus der ffmpeg-Ausgabe gelesen und als Balken angezeigt.

Profile liegen als editierbare JSON/YAML-Dateien vor. Startvorschläge:

| Profil | Auflösung/FPS | Codec | Qualität |
|---|---|---|---|
| Original | wie Quelle | HEVC (NVENC) | sehr hoch (CQ ~16–18), Audio AAC 320k |
| Web | wie Quelle (z. B. 720p50), optional 1080p hochskaliert | H.264 (maximal kompatibel) | CQ ~23, AAC 192k, `faststart` |
| Archiv | wie Quelle | HEVC 10 Bit oder AV1 (RTX 40+) | hoch |

Hinweis: Nach Schnitten kann ffmpeg nicht verlustfrei kopieren (Schnitte liegen fast nie auf Keyframes), deshalb heißt "Original" hier "gleiche Auflösung/FPS, sehr hohe Qualität".

GPU: Beim Start prüft die App per `ffmpeg -encoders` und einem kurzen Testencode, welche Hardware-Encoder funktionieren, und bietet nur diese an. Decodieren ebenfalls per GPU (`-hwaccel cuda` / `d3d11va`), Fallback auf CPU (`libx264`/`libx265`).

### Farbkorrektur

- Jeder Timeline-Clip hat von Anfang an ein Feld `grade` (zunächst leer): Helligkeit, Kontrast, Sättigung, Gamma, Temperatur, optional eine LUT-Datei (`.cube`, z. B. für D-Log/Flat-Profile).
- Dieselben Parameter werden für die Vorschau als mpv-Filter und für den Render als ffmpeg-Filter (`eq`, `colortemperature`, `lut3d`) übersetzt. So sieht das Ergebnis aus wie die Vorschau.
- Später denkbar: Gyroflow-Stabilisierung, Geschwindigkeitsrampen, Übergänge, Hochkant-Export.

### Datenmodell (SQLite, vereinfacht)

```
media_file   (id, fingerprint, size, duration, width, height, fps, codec, bit_depth,
              audio, probed_json, first_seen, reviewed_at)
media_path   (media_id, root_id, rel_path, mtime, last_seen, missing)
root_folder  (id, path)
flight_day   (id, date, spot, folder_name)          -- aus Ordnernamen geparst
clip         (id, media_id, in_ms, out_ms, rating, note, created_at)   -- Favorit
tag          (id, name, color)
clip_tag     (clip_id, tag_id)
```

Timeline-Projekte als JSON:

```json
{
  "version": 1,
  "video_track": [
    {"media_fingerprint": "…", "src_in": 12.40, "src_out": 18.95, "volume": 0.3, "grade": null}
  ],
  "audio_track": [
    {"file": "C:/Musik/track.mp3", "start": 0.0, "src_in": 0.0, "src_out": 95.0, "volume": 1.0, "fade_out": 3.0}
  ],
  "render_profile": "web"
}
```

## 6. Architektur

```
fpvcut/
  core/        Datenbank, Scanner, Fingerprint, Ordnernamen-Parser, ffprobe   (ohne UI, testbar)
  timeline/    Timeline-Modell, EDL-Erzeugung für Vorschau
  render/      Profile, ffmpeg-Kommandobauer, GPU-Erkennung, Fortschritt
  ui/          PySide6: Bibliothek, Player, Favoriten-Browser, Timeline, Render-Dialog
tests/         pytest für core/timeline/render (mit kleinen Testvideos aus ffmpeg)
```

Langsame Arbeiten (Scan, Thumbnails, Render) laufen in Hintergrund-Threads, die UI bleibt bedienbar.

## 7. Meilensteine

1. **Grundgerüst:** Repo, `uv`-Projekt, PySide6-Fenster mit eingebettetem mpv, ffmpeg-/GPU-Check.
2. **Bibliothek:** Ordner hinzufügen, Scan mit Fingerprints, ffprobe, Flugtag-Ansicht, "Neu"-Hervorhebung.
3. **Sichten:** Player mit Tastenkürzeln, In/Out, Favoriten, Tags, Metadaten-Panel.
4. **Favoriten-Browser:** Filtern nach Tags/Flugtag, Vorschau.
5. **Timeline:** Drag & Drop, Trimmen, Teilen, Musikspur, EDL-Vorschau.
6. **Rendern:** Profile, NVENC/AMF/QSV, Fortschritt, Abbrechen.
7. **Umbenennungs-Helfer** für das neue Ordnerschema.
8. **Farbkorrektur** und weitere Ideen.

Nach Meilenstein 3 ist die App bereits zum Sichten und Markieren nutzbar. Das ist der Teil, den du nach jedem Flug brauchst.

## 8. Entscheidungen (17.10.2026)

- **GPU:** NVIDIA, also NVENC (`h264_nvenc`, `hevc_nvenc`, ab RTX 40 auch `av1_nvenc`) und `-hwaccel cuda`. CPU-Fallback bleibt.
- **Material:** meist 1280×720 mit 50 fps, später auch andere Formate. Profile übernehmen deshalb standardmäßig die Quell-Auflösung/FPS; gemischte Quellen werden beim Rendern auf das Zielformat skaliert. Bei 720p ist ein Proxy-Workflow unnötig.
- **UI:** PySide6-Desktop-App.
- **Repository:** auf GitHub, privat.
- **Ordnerschema:** `JJJJ-MM-TT_Spot`, z. B. `2026-10-17_Flugspot`.
