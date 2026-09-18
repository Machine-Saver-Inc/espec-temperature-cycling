"""Small shared widgets and form helpers."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Title")
    return label


def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Subtitle")
    label.setWordWrap(True)
    return label


def primary(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("Primary")
    return button


def field_row(label: str, widget: QWidget, hint: str = "") -> QWidget:
    """One labelled control, with an optional explanation underneath."""
    holder = QWidget()
    outer = QVBoxLayout(holder)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(2)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    name = QLabel(label)
    name.setMinimumWidth(210)
    row.addWidget(name)
    row.addWidget(widget, 1)
    outer.addLayout(row)

    if hint:
        note = QLabel(hint)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        note.setContentsMargins(214, 0, 0, 0)
        outer.addWidget(note)
    return holder


def spin(value: float, low: float, high: float, *, step: float = 1.0,
         decimals: int = 0, suffix: str = "") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    return box


def int_spin(value: int, low: int, high: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    box.setValue(int(value))
    return box


def choice(options: list[str], current: str) -> QComboBox:
    box = QComboBox()
    box.addItems(options)
    if current in options:
        box.setCurrentText(current)
    return box


def check(text: str, value: bool) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(bool(value))
    return box
