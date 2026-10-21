# PyInstaller-Bauplan für FPVCut.exe (Ordner-Variante, startet schneller als eine Einzeldatei).
#
# Vorher müssen libmpv-2.dll in vendor/mpv sowie ffmpeg.exe und ffprobe.exe in vendor/ffmpeg
# liegen. Aufruf aus dem Projektordner: uv run --with pyinstaller pyinstaller packaging/fpvcut.spec
from pathlib import Path

root = Path(SPECPATH).parent
resources = root / "src" / "fpvcut" / "resources"
vendor = [
    (root / "vendor" / "mpv" / "libmpv-2.dll", "vendor/mpv"),
    (root / "vendor" / "ffmpeg" / "ffmpeg.exe", "vendor/ffmpeg"),
    (root / "vendor" / "ffmpeg" / "ffprobe.exe", "vendor/ffmpeg"),
]
missing = [str(src) for src, _ in vendor if not src.is_file()]
if missing:
    raise SystemExit("Fehlt für den Build: " + ", ".join(missing))

a = Analysis(
    [str(root / "packaging" / "fpvcut_main.py")],
    pathex=[str(root / "src")],
    datas=[(str(resources / "fpvcut.svg"), "fpvcut/resources")]
    + [(str(qm), "fpvcut/resources/i18n") for qm in sorted((resources / "i18n").glob("*.qm"))]
    + [(str(src), dest) for src, dest in vendor],
    hiddenimports=["mpv"],
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FPVCut",
    icon=str(resources / "fpvcut.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FPVCut", upx=False)
