# Änderungen

Versionen nach [Semantic Versioning](https://semver.org/lang/de/). Vorabversionen (`-rc1`, `-rc2`, …)
sind Release-Kandidaten zum Testen; ist die [Testcheckliste](docs/testcheckliste.md) ohne Fehler
durch, wird daraus die fertige Version.

## Unveröffentlicht

### Neu

- **Import von der SD-Karte:** Datei → Von SD-Karte importieren (Strg+I) kopiert die Videos samt
  gleichnamigen Begleitdateien (z. B. `.srt`, `.osd`) in einen neuen Flugtag-Ordner
  `YYYY-MM-DD_Spot` im Bibliotheksordner, liest jede Kopie zur Prüfung zurück, löscht danach die
  Originale auf der Karte und wirft sie aus (beides abwählbar). Karte und Unterordner merkt sich
  FPVCut beim ersten Mal und findet sie auch unter anderem Laufwerksbuchstaben wieder; steckt die
  Karte, bietet die Statusleiste den Import an. Gleiche Dateinamen bekommen `_1`, `_2` …, schon
  importierte Dateien werden erkannt und nicht doppelt kopiert
- **Schwarzblende am Ende:** Neben „Ausblenden“ der Musik stellt „Schwarzblende“ ein, wie viele
  Sekunden das Bild am Ende in Schwarz ausblendet (0 = aus). Wirkt in Vorschau und Export; beim
  Rendern eines markierten Bereichs blendet das Bild wie die Musik am Bereichsende aus. Die Timeline
  zeigt die Blende als dunklen Verlauf über dem Ende der Videospur
- **Nur einen Bereich rendern:** Im Zeitlineal über der Timeline einen Bereich ziehen (Kanten
  lassen sich nachziehen), oder unter Timeline → Bereich rendern per Umschalt+I/O am Abspielkopf
  bzw. aus den ausgewählten Clips setzen. Das Renderfenster bietet dann „Markierter Bereich“ oder
  „Ganze Timeline“ an. Angeschnittene Clips werden gekürzt, die Musik setzt an der passenden
  Stelle ein und blendet am Ende des Bereichs aus. Esc hebt den Bereich auf
- **Englisch und Deutsch:** Die Oberfläche gibt es jetzt auf Englisch und Deutsch. FPVCut folgt
  der Systemsprache, unter **Datei → Sprache** lässt sich eine feste Sprache wählen (gilt ab dem
  nächsten Start). Auch Standarddialoge und Datumsangaben folgen der Sprache. Projektdateien,
  Ordnernamen und Sicherungen bleiben unverändert
- **Schärfe:** neuer Regler im Reiter Farbe, nach rechts schärfer, nach links weicher; wirkt in
  Vorschau und Export
- **Automatische Farbkorrektur (✨ Automatisch):** misst fünf Bilder jedes ausgewählten Clips (nach
  der LUT) und stellt Helligkeit, Kontrast, Gamma, Schatten, Lichter, Dynamik und Farbtemperatur
  ein. LUT und Schärfe bleiben; alles lässt sich danach von Hand nachstellen und in einem Schritt
  rückgängig machen
- **Neue Regler Schatten, Lichter und Dynamik:** dunkle bzw. helle Bildteile gezielt anheben oder
  absenken; Dynamik hebt blasse Farben stärker an als kräftige
- **Schnellere Vorschau mit Farbkorrektur:** die Filter laufen in der Vorschau auf höchstens 1080
  Zeilen, bei 4K-Material etwa dreimal so schnell. Der Export rechnet weiter in voller Größe
- **Timeline:** Ein Klick auf eine freie Stelle oder die Zeitleiste versetzt nur den Abspielkopf;
  ausgewählte Clips bleiben ausgewählt. Esc hebt die Auswahl auf

### Behoben

- **Farbkorrektur und LUTs in der Vorschau:** wurden bei hardware-dekodierten Clips (unter Windows
  die Regel) nicht oder nur vereinzelt angezeigt, weil mpv den Farbfilter stillschweigend abschaltete,
  wenn die Bilder im Grafikspeicher lagen. Mit Farbkorrektur kopiert die Vorschau die Bilder jetzt
  in den Arbeitsspeicher
- **Vorschau mit Farbkorrektur und Clips unterschiedlicher Auflösung:** Clips, deren Auflösung von
  der des ersten abwich, erschienen in der Vorschau in falscher Größe

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
