"""Datei → KI-Modelle: Checkpoints von Schüler und Lehrer wählen, Stand von PyTorch und Grafikkarte."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fpvcut import restore


class RestoreDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("AI models"))
        self.setMinimumWidth(620)
        intro = QLabel(self.tr(
            "Models from fpv-restoration for cleaning up analog FPV footage. The student runs live in the "
            "timeline preview, the teacher optionally when rendering. Switch the cleanup on per clip in the "
            "Color tab."), self)
        intro.setWordWrap(True)
        self._labels: dict[str, QLabel] = {}
        form = QFormLayout()
        names = {"student": self.tr("Student:"), "teacher": self.tr("Teacher:")}
        for kind in restore.KINDS:
            label = QLabel(self)
            label.setWordWrap(True)
            choose = QPushButton(self.tr("Choose …"), self)
            choose.clicked.connect(lambda _=False, k=kind: self._choose(k))
            default = QPushButton(self.tr("Default"), self)
            default.setToolTip(self.tr("Search in the default folders again: {folders}").format(
                folders=", ".join(str(d) for d in restore.default_dirs())))
            default.clicked.connect(lambda _=False, k=kind: self._set(k, None))
            row = QHBoxLayout()
            row.addWidget(label, 1)
            row.addWidget(choose)
            row.addWidget(default)
            form.addRow(names[kind], row)
            self._labels[kind] = label
        self._system = QLabel(self)
        self._system.setWordWrap(True)
        form.addRow(self.tr("System:"), self._system)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self) -> None:
        for kind, label in self._labels.items():
            path = restore.model_path(kind)
            label.setText(str(path) if path else self.tr("not found"))
        if not restore.torch_installed():
            self._system.setText(restore.problem() or "")
            return
        try:
            gpu = restore.gpu_name()
        except Exception as exc:  # noqa: BLE001  (kaputte CUDA-Installation o. Ä. nur anzeigen)
            gpu, error = None, str(exc)
        else:
            error = None
        self._system.setText(self.tr("Graphics card: {gpu}").format(gpu=gpu) if gpu else
                             self.tr("No CUDA graphics card found, the models would be far too slow.") +
                             (f"\n{error}" if error else ""))

    def _choose(self, kind: str) -> None:
        current = restore.model_path(kind)
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Choose checkpoint"), str(current or ""),
                                              self.tr("PyTorch checkpoint (*.pt *.pth)"))
        if path:
            self._set(kind, Path(path))

    def _set(self, kind: str, path: Path | None) -> None:
        restore.set_model_path(kind, path)
        self._refresh()
