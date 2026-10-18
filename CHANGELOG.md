# Änderungen

Versionen nach [Semantic Versioning](https://semver.org/lang/de/). Vorabversionen (`-rc1`, `-rc2`, …)
sind Release-Kandidaten zum Testen; ist die [Testcheckliste](docs/testcheckliste.md) ohne Fehler
durch, wird daraus die fertige Version.

## 1.0.0-rc2 (2026-10-18)

### Neu

- **Ausschnitte und Favoriten:** Was bisher „Favorit“ hieß, heißt jetzt Ausschnitt. Einzelne
  Ausschnitte lassen sich zusätzlich als Favorit (★) markieren: im Speichern-Dialog, per Klick auf
  den Stern im Ausschnitte-Reiter oder über das Kontextmenü. Favoriten sind unter der Zeitleiste
  kräftiger eingefärbt, und der Ausschnitte-Reiter hat einen Filter „Nur Favoriten“
- **Bibliothek:** zeigt pro Video die Favoriten (★n) und die übrigen Ausschnitte (✂n) getrennt; ein
  einfacher Klick öffnet das Video
- **Mehrfachauswahl in der Timeline:** Strg+Klick nimmt Clips dazu oder heraus, Umschalt+Klick
  wählt alle Clips bis zum angeklickten, Strg+A alle. Ausgewählte Clips lassen sich gemeinsam
  löschen und als Block verschieben. In der Farbkorrektur zeigen die Regler den zuletzt angeklickten
  Clip; eine Änderung übernimmt nur den bewegten Regler in alle ausgewählten Clips, „Auf
  ausgewählte Clips übertragen“ kopiert die komplette Korrektur
- **Ausschnitt per Ziehen:** Einen Bereich auf der Leiste unter der Zeitleiste ziehen markiert ihn
  als Auswahl. Der neue Speichern-Knopf rechts neben der Zeitleiste speichert sie als Ausschnitt;
  er ist nur aktiv, solange ein Bereich markiert ist
- **Projekte:** Neues Projekt (Strg+N), Projekt öffnen, Speichern (Strg+S) und Speichern unter
  (Strg+Umschalt+S) im Menü Datei. Bei ungespeicherten Änderungen fragt FPVCut, ob gespeichert,
  verworfen oder abgebrochen werden soll. Der Fenstertitel zeigt den Projektnamen und ein `*` bei
  Änderungen
- **Zuletzt geöffnet** im Menü Datei listet die letzten acht Projekte. Öffnen und Speichern starten
  im zuletzt gewählten Ordner, beim ersten Mal im Bibliotheksordner

### Behoben

- **Timeline-Vorschau** blieb stehen, sobald zwei aufeinanderfolgende Clips verschiedene Formate
  hatten (z. B. MP4 und TS, andere Auflösung oder Bildrate), und ließ sich ab dort nicht mehr abspielen
- **Ton in der Vorschau:** Der Originalton kam nach längeren stummen Strecken zu früh, und nach
  einem Sprung lief die Musik versetzt, blendete zu früh aus oder fehlte ganz. Originalton und
  Musik werden jetzt wie beim Export vorab zusammengemischt
- **Frame zurück (←)** blieb bei manchen Dateien (z. B. DVR-Aufnahmen) an bestimmten Stellen hängen
- **Tags im Speichern-Dialog:** Knöpfe sind nur so breit wie ihr Text und brechen um; alle Tags
  werden angezeigt statt höchstens 16
- **Ausschnitte-Reiter:** Das Tag-Feld wächst mit (bis acht Zeilen) und lässt sich am Trenner darunter
  größer oder kleiner ziehen
- **Vollbild per Doppelklick** löst nicht mehr aus Versehen aus: Die Klicks müssen innerhalb von 0,3 s
  kommen (wie bei mpv und YouTube) statt der 0,5 s von Windows

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
