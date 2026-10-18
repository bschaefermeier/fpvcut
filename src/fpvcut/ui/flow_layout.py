"""Layout, das Widgets nebeneinander anordnet und bei Platzmangel umbricht (wie Text)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QLayout, QLayoutItem, QScrollArea, QToolButton, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802  (Qt-Name)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            # Direkt beim Widget fragen: QWidgetItem meldet 0×0, solange das Fenster noch nicht sichtbar war.
            widget = item.widget()
            hint = widget.sizeHint() if widget is not None else item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height > 0:
                x, y = area.x(), y + line_height + self.spacing()
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class TagArea(QScrollArea):
    """Umschaltbare Tag-Knöpfe, so breit wie ihr Text, die wie Text umbrechen.

    Die Höhe wächst mit den Zeilen bis ``max_rows``, danach wird gescrollt.
    """

    def __init__(self, max_rows: int = 6, auto_height: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.max_rows = max_rows
        self.auto_height = auto_height  # sonst bestimmt der Aufrufer die Höhe (z. B. per Splitter)
        self.buttons: dict[str, QToolButton] = {}
        self._box = QWidget()
        self._flow = FlowLayout(self._box)
        self.setWidget(self._box)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def set_tags(self, tags: list[tuple[str, str]], checked: set[str] = frozenset()) -> None:
        """``tags`` als (Name, Beschriftung); vorhandene Knöpfe werden ersetzt."""
        for button in self.buttons.values():
            self._flow.removeWidget(button)
            button.deleteLater()
        self.buttons = {}
        for name, label in tags:
            button = QToolButton(self._box)
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(name in checked)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._flow.addWidget(button)
            self.buttons[name] = button
        self.setVisible(bool(tags))
        self.updateGeometry()

    def row_height(self) -> int:
        if not self.buttons:
            return 0
        return next(iter(self.buttons.values())).sizeHint().height() + self._flow.spacing()

    def needed_height(self, width: int | None = None) -> int:
        """Höhe für alle Zeilen bei dieser Breite."""
        return self._flow.heightForWidth(width or self.viewport().width() or self.width())

    def fitting_height(self, width: int | None = None) -> int:
        """Nötige Höhe, höchstens ``max_rows`` Zeilen."""
        if not self.buttons:
            return 0
        return min(self.needed_height(width), self.max_rows * self.row_height() - self._flow.spacing())

    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt-Name)
        return QSize(0, min(self.row_height(), self.fitting_height()))  # Scroll-Areas wollen sonst ~70 px

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.auto_height and self.buttons:
            self.setFixedHeight(self.fitting_height(event.size().width()))
