"""Datei → KI-Modelle: normales Modell und das hoher Qualität wählen, Stand von PyTorch und Grafikkarte."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
            "Models from fpv-restoration for cleaning up analog FPV footage. The normal model runs live in the "
            "timeline preview, the high-quality model optionally when rendering. Switch the cleanup on per clip in the "
            "Color tab."), self)
        intro.setWordWrap(True)
        self._labels: dict[str, QLabel] = {}
        form = QFormLayout()
        names = {"normal": self.tr("Normal:"), "high_quality": self.tr("High quality:")}
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
        self._convert = QPushButton(self.tr("Convert normal model to ONNX"), self)
        self._convert.setToolTip(self.tr("Creates a .onnx file next to the checkpoint: half the size, faster, "
                                         "and works without PyTorch"))
        self._convert.clicked.connect(self._convert_normal)
        form.addRow("", self._convert)
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
        lines = []
        if restore.onnx_installed():
            from fpvcut.restore.onnx_runner import providers  # noqa: PLC0415

            gpu = [p.removesuffix("ExecutionProvider") for p in providers() if p != "CPUExecutionProvider"]
            lines.append(self.tr("ONNX Runtime (normal): {devices}").format(
                devices=", ".join(gpu) if gpu else self.tr("processor only, far too slow")))
        else:
            lines.append(self.tr("ONNX Runtime is not installed."))
        if restore.torch_installed():
            try:
                from fpvcut.restore.torch_runner import gpu_name  # noqa: PLC0415

                gpu = gpu_name()
            except Exception as exc:  # noqa: BLE001  (kaputte CUDA-Installation o. Ä. nur anzeigen)
                gpu = str(exc)
            lines.append(self.tr("PyTorch (high quality): {gpu}").format(gpu=gpu or self.tr("no CUDA graphics card")))
        else:
            lines.append(self.tr("PyTorch is not installed (uv sync --extra ki), the high-quality model is not available."))
        self._system.setText("\n".join(lines))
        normal = restore.model_path("normal")
        self._convert.setVisible(normal is not None and normal.suffix.lower() == ".pt" and restore.torch_installed())

    def _convert_normal(self) -> None:
        """Checkpoint des normalen Modells nach ONNX umwandeln (daneben) und die ONNX-Datei verwenden."""
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415
        from PySide6.QtCore import Qt  # noqa: PLC0415

        source = restore.model_path("normal")
        target = source.with_suffix(".onnx")
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from fpvcut.restore.export import export  # noqa: PLC0415

            export(source, target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self.tr("AI models"), self.tr("Conversion failed: {error}").format(error=exc))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._set("normal", target)

    def _choose(self, kind: str) -> None:
        current = restore.model_path(kind)
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Choose checkpoint"), str(current or ""),
                                              self.tr("Model (*.onnx *.pt *.pth)"))
        if path:
            self._set(kind, Path(path))

    def _set(self, kind: str, path: Path | None) -> None:
        restore.set_model_path(kind, path)
        self._refresh()
