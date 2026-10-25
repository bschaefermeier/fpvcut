# FPVCut

FPVCut is a lightweight video editor for FPV footage. It brings the usual steps after a day of
flying together in one application: review your recordings, save the best scenes as clips, arrange
them on a timeline with music and export the result with GPU acceleration.

![FPVCut with the Clips tab, preview, color correction and timeline](docs/bilder/fpvcut.png)

## Features

- **Import from SD card:** Copy the videos from the SD card into a new flight day folder, check
  every copy, delete the originals on the card and eject it, in one step. FPVCut remembers the card
  and folder, so next time it is ready as soon as the card is inserted.
- **Library:** Video folders are grouped by flight day automatically. New recordings you haven't
  reviewed yet are highlighted. Renamed or moved files are recognized.
- **Reviewing and clips:** Frame-accurate playback; mark scenes with in and out points and save
  them as clips with tags and notes. The best ones can be marked as favorites (★).
- **Clips tab:** All clips across all flight days, filterable by tags, favorites and free text.
- **Timeline:** Arrange clips by drag and drop, trim and split them, and move, delete or color
  several at once. Plus a music track with volume control and fade-out, and an optional fade to black at the end. The preview plays without
  rendering first.
- **Color correction:** Brightness, contrast, gamma, shadows, highlights, saturation, vibrance,
  color temperature and sharpness per clip, an automatic mode that sets these sliders with one
  click, and 3D LUTs (`.cube`) for D-Log or flat profiles.
- **AI cleanup for analog FPV footage (optional):** Removes noise, rainbow stripes and color tears,
  and on request the OSD, with the models from
  [fpv-restoration](https://github.com/bschaefermeier/fpv-restoration). Switched on per clip in the
  Color tab; the small student model runs live in the timeline preview, before the color correction.
  When rendering, the better but much slower teacher model can be used instead (stride 1–5). Needs
  an NVIDIA graphics card, PyTorch and the two checkpoints (see [AI cleanup](#ai-cleanup)).
- **Export:** Profiles for original quality (H.265), web (H.264) and archive (H.265, 10 bit).
  Encoding uses NVIDIA NVENC, or the CPU without a suitable graphics card.
- **Rename folders:** Bring flight day folders into the consistent scheme `YYYY-MM-DD_Spot`, with a
  preview and undo.

## Installation

Requires Windows 10 or 11 (64 bit).

1. Download the latest `FPVCut-…-windows.zip` from
   [Releases](https://github.com/bschaefermeier/fpvcut/releases).
2. Unzip the archive and start `FPVCut.exe`.

All required components (libmpv, ffmpeg) are included.

> **Note:** Since the .exe is not signed, Windows SmartScreen may show a warning on first start.
> Click "More info" → "Run anyway" to start FPVCut. Alternatively, you can run FPVCut directly from
> source or build it yourself, see [Running from source](#running-from-source).

To update, replace the program folder with the new version. Your library, clips and projects are
kept.

## Usage

### Getting started

1. Choose the folder with your recordings via **File → Add library folder**. FPVCut recognizes
   flight days by the date in the folder name, e.g. `2026-08-28_Field` or `28_08_26_Field`.
2. To import a flight day, insert the SD card and choose **File → Import from SD card**
   (**Ctrl+I**). Pick the folder with the videos on the card once; FPVCut remembers it. Enter the
   spot, and FPVCut copies the videos into `YYYY-MM-DD_Spot`, checks the copies, deletes them on
   the card and ejects it (both can be switched off).
3. Open a video with a click, mark scenes with **I** and **O** and save them as clips with **F**.
   Alternatively, drag a range on the bar below the seek bar and save it with the save button to
   the right of the seek bar.
4. Drag clips from the **Clips** tab into the timeline, optionally add music, and export with
   **Ctrl+R**. **Ctrl+S** saves the project.
5. To export only part of the timeline, drag a range in the time ruler above the timeline. The
   render window then asks whether to render just that range or the whole timeline.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| Space | Play / pause |
| ← / → | One frame back / forward |
| Shift + ← / → | 1 second back / forward |
| J / L | 5 seconds back / forward |
| I / O | Set in / out point |
| F | Save selection as clip |
| Shift + F | Save whole video as clip |
| Esc | Clear selection and marked range (also in the timeline), exit full screen |
| F11 or double-click | Full screen |
| E | Add selection to timeline |
| S | Split clip at playhead |
| Del | Remove selected clips |
| Ctrl + click / Shift + click | Select several clips in the timeline |
| Ctrl + A | Select all clips in the timeline (timeline focused) |
| Shift + I / O | Start / end of the render range at the timeline playhead |
| P | Play timeline |
| Ctrl + ← / → | Start / end of timeline |
| Ctrl + Z / Ctrl + Y | Undo / redo |
| Ctrl + R | Render |
| Ctrl + I | Import from SD card |
| Ctrl + N | New project |
| Ctrl + S | Save project |
| F5 | Rescan library |

## Data and backups

FPVCut never modifies your video files. Library, clips and tags are stored in `%APPDATA%\FPVCut`.
The timeline is saved there continuously, even if the project hasn't been saved yet; project files
(`.fpvcut.json`) go wherever you save them.

Clips, tags and review status are backed up automatically on start and exit; backups from the last
30 days are kept in `%APPDATA%\FPVCut\sicherungen`. You can also back up your clips anywhere with
**File → Export clips** and read them back with **Import clips**. If FPVCut starts with an empty
library, it offers to restore the latest backup.

## Running from source

### Requirements

- [uv](https://docs.astral.sh/uv/) as the Python package manager
- [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) with NVENC support
- `libmpv-2.dll` from an `mpv-dev-x86_64` package of
  [mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake/releases)

### Setup

```powershell
# install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# clone the repository and install dependencies
git clone https://github.com/bschaefermeier/fpvcut.git
cd fpvcut
uv sync
```

Put `libmpv-2.dll` into `vendor\mpv\`, and `ffmpeg.exe` and `ffprobe.exe` into `vendor\ffmpeg\`.
ffmpeg is also found via `PATH`.

### Run

```powershell
uv run fpvcut
```

### AI cleanup

The AI cleanup needs PyTorch with CUDA (about 2.5 GB), which is an optional extra:

```powershell
uv sync --extra ki
```

FPVCut looks for the checkpoints `schueler_2h.pt` (student) and `lehrer_cluster.pt` (teacher) in
`%FPVCUT_MODELS%`, `%APPDATA%\FPVCut\modelle` and `..pv-restoration\checkpoints` next to this
repository; other files can be chosen under File → AI models. Both models work on half resolution
(the BoxPro+ picture 1200 × 720 becomes 592 × 352) and the result is scaled back to the source size.
On an RTX 3070 the student manages about 70 frames/s including decoding, the teacher about 2 frames/s
at stride 1 up to 11 frames/s at stride 5. The Windows package does not include PyTorch.

### Tests

```powershell
uv run pytest
```

### Build the Windows package

```powershell
uv run --with pyinstaller pyinstaller --noconfirm packaging/fpvcut.spec
```

The result is in `dist\FPVCut\`. How to publish a new version is described in
[docs/release.md](docs/release.md).

## License

FPVCut is licensed under the [GNU General Public License v3.0](LICENSE) or any later version.
