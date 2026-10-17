# Änderungen

Versionen nach [Semantic Versioning](https://semver.org/lang/de/). Vorabversionen (`-rc1`, `-rc2`, …)
sind Release-Kandidaten zum Testen; ist die [Testcheckliste](docs/testcheckliste.md) ohne Fehler
durch, wird daraus die fertige Version.

## 1.0.0-rc1 (2026-10-17)

Erster Release-Kandidat mit allen Funktionen aus dem [Plan](docs/plan.md).

### Neu

- **Player:** eingebettetes mpv mit Frame-genauer Navigation (←/→, Shift+←/→, J/L), Klick =
  Play/Pause, Doppelklick oder F11 = Vollbild, Alt+F4 beendet die App
- **Systemcheck:** findet ffmpeg/ffprobe und prüft per Testencode, welche Encoder (NVENC, x264,
  x265, AV1) wirklich laufen
- **Bibliothek:** Ordner scannen, Videos nach Flugtag gruppiert, neue Videos markiert, Fingerprint
  erkennt umbenannte und verschobene Dateien wieder
- **Favoriten und Tags:** Ausschnitte mit I/O markieren, mit F als Favorit samt Tags und Notiz
  speichern, Markierungsleiste und Seitenleiste mit Metadaten
- **Favoriten-Browser:** alle Favoriten mit Tag- und Textfilter, Doppelklick spielt in Schleife
- **Timeline:** Clips per Drag & Drop oder E, verschieben, trimmen, teilen (S), Rückgängig,
  Mausrad-Zoom, Strg+←/→ an Anfang/Ende; Musikspur mit Lautstärke und Ausblenden; Vorschau ohne
  Rendern; automatisches Speichern
- **Rendern:** Profile Original, Web und Archiv, NVENC auf der GPU (sonst CPU), Fortschritt mit
  Restzeit
- **Umbenennungs-Helfer:** Flugtag-Ordner ins Schema `JJJJ-MM-TT_Spot`, mit Vorschau,
  Konfliktprüfung, Rückgängig und Protokoll
- **Favoriten sichern:** tägliche automatische Sicherung, Export/Import, Wiederherstellen-Angebot
  bei leerer Bibliothek
- **Farbkorrektur:** pro Clip Helligkeit, Kontrast, Sättigung, Gamma, Farbtemperatur und 3D-LUT,
  gleiche Filter in Vorschau und Render
- **Eigenes App-Icon** in Fenster und Taskleiste
- **Windows-Programm:** `FPVCut.exe` als ZIP zum Herunterladen, libmpv und ffmpeg sind dabei
- **Lizenz:** GPL-3.0-or-later; die Lizenztexte der mitgelieferten Bestandteile liegen im ZIP unter `lizenzen\`
