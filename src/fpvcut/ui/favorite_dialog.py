"""Dialog zum Speichern oder Bearbeiten eines Favoriten: Tags und Notiz."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_QUICK_TAGS = 16


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
        title: str = "Favorit speichern",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        self.tags_edit = QLineEdit(", ".join(tags), self)
        self.tags_edit.setPlaceholderText("z. B. Crash, Flip, Gap (mit Komma getrennt)")
        self.tags_edit.textChanged.connect(self._sync_buttons)
        self.note_edit = QLineEdit(note, self)
        self.note_edit.setPlaceholderText("optional")

        # Bekannte Tags als Schaltflächen zum schnellen An- und Abwählen.
        self._buttons: dict[str, QPushButton] = {}
        quick = QHBoxLayout()
        quick.setSpacing(4)
        for tag in known_tags[:MAX_QUICK_TAGS]:
            button = QPushButton(tag, self)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.toggled.connect(lambda checked, t=tag: self._toggle_tag(t, checked))
            quick.addWidget(button)
            self._buttons[tag.lower()] = button
        quick.addStretch(1)

        form = QFormLayout()
        form.addRow("Ausschnitt:", QLabel(range_text, self))
        form.addRow("Tags:", self.tags_edit)
        if self._buttons:
            form.addRow("", quick)
        form.addRow("Notiz:", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._sync_buttons()
        self.tags_edit.setFocus()

    @property
    def tags(self) -> list[str]:
        return parse_tags(self.tags_edit.text())

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
