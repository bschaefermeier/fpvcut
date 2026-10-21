# Neue Version veröffentlichen

1. Version in `src/fpvcut/__init__.py` und `pyproject.toml` anheben.
2. Geänderte Texte übersetzen: `uv run python packaging/update_translations.py`, dann in
   `fpvcut_de.ts` die als unübersetzt markierten Einträge füllen und den Befehl wiederholen
   (der Test `test_i18n.py` schlägt fehl, solange etwas fehlt).
3. Den Abschnitt „Unveröffentlicht“ in `CHANGELOG.md` in die neue Version umbenennen.
4. Änderungen mergen und auf `main` einen Tag setzen, z. B. `v1.0.0-rc2` oder `v1.0.0`:

   ```powershell
   git tag -a v1.0.0 -m "FPVCut 1.0.0"
   git push origin v1.0.0
   ```

Der Workflow [windows-build.yml](../.github/workflows/windows-build.yml) baut daraufhin
`FPVCut.exe` mit libmpv und ffmpeg, führt einen Selbsttest aus und veröffentlicht das ZIP als
GitHub-Release. Tags mit Bindestrich (`-rc1`) werden als Vorabversion markiert.

Ohne Tag lässt sich der Workflow unter **Actions → Windows-Build → Run workflow** starten; das ZIP
liegt dann als Artefakt am jeweiligen Lauf.

Das Programmsymbol `src/fpvcut/resources/fpvcut.ico` wird bei Änderungen am SVG mit
`uv run python packaging/make_icon.py` neu erzeugt.
