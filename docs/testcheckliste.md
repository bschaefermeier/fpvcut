# Testcheckliste für Release-Kandidaten

Mit der heruntergeladenen `FPVCut.exe` durchgehen, nicht mit `uv run`. Was nicht klappt, als Issue
oder im Projekt-Chat melden; nach den Korrekturen gibt es den nächsten Kandidaten (`-rc2`, …).
Tipp: vorher Datei → "Ausschnitte exportieren …", dann ist nichts verloren.

## Start

- [ ] ZIP entpacken, `FPVCut\FPVCut.exe` startet ohne Fehlermeldung (evtl. SmartScreen:
      "Weitere Informationen" → "Trotzdem ausführen")
- [ ] Fenstertitel zeigt "FPVCut 1.0.0rc1", Taskleiste und Titelleiste zeigen das FPVCut-Icon
- [ ] Bibliothek, Ausschnitte und Timeline aus der bisherigen `uv run`-Version sind da
- [ ] Hilfe → Systemcheck: ffmpeg aus dem Programmordner gefunden, NVENC-Encoder als funktionierend

## Sichten

- [ ] Video per Klick in der Bibliothek öffnen, Leertaste, ←/→, Shift+←/→, J/L, Klick, Doppelklick, F11/Esc, Alt+F4
- [ ] F5 scannt neu, neue Videos sind markiert, "Nur neue" filtert
- [ ] I/O setzen, F speichert Ausschnitt mit Tags, gelber Balken erscheint; mit Haken "★ Favorit"
      ist der Balken kräftiger und die Bibliothek zeigt ★ statt ✂
- [ ] Bereich auf der Leiste unter der Zeitleiste ziehen: Bild folgt, Speichern-Knopf rechts neben
      der Zeitleiste wird aktiv und öffnet den Dialog
- [ ] Ausschnitte-Reiter: Tag-Filter, Suche, "Nur Favoriten", Klick auf den Stern schaltet um,
      Doppelklick spielt in Schleife

## Timeline

- [ ] Ausschnitte und ganze Videos hineinziehen, E fügt hinzu
- [ ] Verschieben, Trimmen, S teilt, Entf löscht, Strg+Z/Strg+Y, Mausrad-Zoom, Strg+←/→
- [ ] Musik wählen, Lautstärken, Ausblenden; Vorschau mit P, Ton bleibt nach Sprüngen synchron
- [ ] App schließen und neu starten: Timeline ist wieder da
- [ ] Strg+S speichert das Projekt (beim ersten Mal mit Dateiauswahl), Titel zeigt Namen und `*`
      bei Änderungen; Strg+N fragt nur bei ungespeicherten Änderungen (Speichern/Verwerfen/Abbrechen)
- [ ] Projekt öffnen startet im Bibliotheksordner, danach im zuletzt gewählten Ordner;
      Datei → Zuletzt geöffnet listet die Projekte

## Farbe

- [ ] Clip auswählen, Reiter Farbe: Regler wirken sofort in der Vorschau
- [ ] Doppelklick auf Regler oder Wert setzt zurück, LUT laden, "Auf alle Clips übertragen"

## Rendern

- [ ] Strg+R, Profil Web: Datei entsteht, läuft im Windows-Player, Farbe und Musik wie in der Vorschau
- [ ] Profil Original mit NVENC, Abbrechen löscht die halbfertige Datei

## Ordner und Sicherung

- [ ] Datei → "Ordner ins Schema umbenennen …": Vorschau stimmt, Umbenennen und Rückgängig klappen,
      Ausschnitte bleiben
- [ ] Ausschnitte exportieren und wieder importieren: nichts doppelt
