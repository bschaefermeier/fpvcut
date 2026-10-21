"""Dialog zum Speichern oder Bearbeiten eines Ausschnitts: Favorit, Tags und Notiz."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fpvcut.ui.flow_layout import TagArea


def parse_tags(text: str) -> list[str]:
    """``"Crash, flip ,, Gap"`` → ``["Crash", "flip", "Gap"]`` (ohne Dubletten, Groß/klein egal)."""
    seen: dict[str, str] = {}
    for part in text.split(","):
        tag = part.strip()
        if tag and tag.lower() not in seen:
            seen[tag.lower()] = tag
    return list(seen.values())


class FavoriteDialog(QDialog):
    def __init__(
        self,
        range_text: str,
        known_tags: list[str],
        tags: list[str] = (),
        note: str = "",
        title: str | None = None,
        favorite: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or self.tr("Save clip"))
        self.setMinimumWidth(420)

        self.tags_edit = QLineEdit(", ".join(tags), self)
        self.tags_edit.setPlaceholderText(self.tr("e.g. crash, flip, gap (comma-separated)"))
        self.tags_edit.textChanged.connect(self._sync_buttons)
        self.note_edit = QLineEdit(note, self)
        self.note_edit.setPlaceholderText(self.tr("optional"))

        # Bekannte Tags als Knöpfe zum schnellen An- und Abwählen; brechen um, ab 8 Zeilen wird gescrollt.
        self._quick = TagArea(max_rows=8, parent=self)
        unique = list({tag.lower(): tag for tag in reversed(known_tags)}.values())[::-1]
        self._quick.set_tags([(tag.lower(), tag) for tag in unique])
        self._quick.setFixedHeight(self._quick.fitting_height(330))  # Schätzung, bis die Breite feststeht
        self._buttons: dict[str, QToolButton] = self._quick.buttons
        for tag in unique:
            self._buttons[tag.lower()].toggled.connect(lambda checked, t=tag: self._toggle_tag(t, checked))

        form = QFormLayout()
        form.addRow(self.tr("Clip:"), QLabel(range_text, self))
        form.addRow(self.tr("Tags:"), self.tags_edit)
        if self._buttons:
            form.addRow("", self._quick)
        form.addRow(self.tr("Note:"), self.note_edit)
        self.favorite_check = QCheckBox(self.tr("★ Favorite"), self)
        self.favorite_check.setChecked(favorite)
        self.favorite_check.setToolTip(self.tr("Especially good clips; can be filtered separately in the Clips tab"))
        form.addRow("", self.favorite_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._sync_buttons()
        self.tags_edit.setFocus()

    def showEvent(self, event) -> None:  # noqa: N802  (Qt-Name)
        super().showEvent(event)
        self.adjustSize()  # Tag-Feld steht jetzt in der echten Breite fest

    @property
    def tags(self) -> list[str]:
        return parse_tags(self.tags_edit.text())

    @property
    def favorite(self) -> bool:
        return self.favorite_check.isChecked()

    @property
    def note(self) -> str:
        return self.note_edit.text().strip()

    def _toggle_tag(self, tag: str, checked: bool) -> None:
        tags = self.tags
        present = any(t.lower() == tag.lower() for t in tags)
        if checked and not present:
            tags.append(tag)
        elif not checked and present:
            tags = [t for t in tags if t.lower() != tag.lower()]
        else:
            return
        self.tags_edit.setText(", ".join(tags))

    def _sync_buttons(self) -> None:
        current = {t.lower() for t in self.tags}
        for key, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(key in current)
            button.blockSignals(False)
