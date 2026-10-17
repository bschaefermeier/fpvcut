# FPVCut

Schlanke Desktop-Software zum Sichten, Markieren und Schneiden von FPV-Videos.
Python + PySide6 als Oberfläche, libmpv als Player, ffmpeg (mit NVIDIA NVENC) zum Rendern.

Der Gesamtplan mit allen Meilensteinen liegt in [docs/plan.md](docs/plan.md).

## Stand

Meilenstein 1 (Grundgerüst):

- Fenster mit eingebettetem mpv-Player: Video öffnen (Strg+O), Leertaste = Play/Pause,
  ←/→ = ein Frame, Shift+←/→ = 1 s, J/L = 5 s, Zeitleiste zum Springen
- Systemcheck (Hilfe → Systemcheck, Status unten rechts): findet ffmpeg/ffprobe und prüft per
  Testencode, welche Encoder wirklich funktionieren (NVENC wird von ffmpeg auch ohne passende GPU
  gelistet, daher der Test)

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
  core/   ohne UI, testbar (ffmpeg-Erkennung; später Bibliothek, Fingerprints, Datenbank)
  ui/     PySide6-Oberfläche (Hauptfenster, Player)
tests/
```
