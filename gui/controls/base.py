"""Shared building blocks for the control sections.

Two pieces:

* `Knob`  — a labelled slider with a live readout, and integer-only Qt sliders
            faked into decimals via a `scale` factor.
* `Section` — a QGroupBox that emits one `changed` signal for *any* widget in it
            and knows how to report its own values as a dict.

The dict is the whole contract with the main window: it merges the three dicts
into one `Settings` and hands it to the worker. Adding a knob therefore means
touching exactly one file — the section it belongs to.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class Knob(QWidget):
    """Name, slider and live value in one row.

    Qt sliders are integer-only, so a knob that needs decimals stores its value
    multiplied by `scale` and divides on the way out — e.g. scale=100 gives a
    0.01 step. `value()` always returns the real-world number.
    """

    def __init__(
        self,
        name: str,
        lo: float,
        hi: float,
        value: float,
        scale: int = 1,
        tip: str = "",
    ):
        super().__init__()
        self.scale = scale
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(lo * scale), int(hi * scale))
        self.slider.setValue(int(round(value * scale)))

        self.readout = QLabel()
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.addWidget(QLabel(name), 0, 0)
        grid.addWidget(self.readout, 0, 1)
        grid.addWidget(self.slider, 1, 0, 1, 2)
        if tip:
            self.setToolTip(tip)

        self.slider.valueChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.readout.setText(f"{self.value():g}")

    def value(self) -> float:
        return self.slider.value() / self.scale

    def set_value(self, value: float) -> None:
        self.slider.setValue(int(round(value * self.scale)))


class Section(QGroupBox):
    """A titled group of controls that reports one `changed` signal for all of them.

    Subclasses build their widgets with `self.knob(...)`, `self.combo(...)` and
    `self.check(...)`, which create the widget, stack it in the section's layout
    and wire its change signal to `changed` — so no subclass ever has to remember
    the connection step. They then implement `values()`.
    """

    changed = pyqtSignal()

    def __init__(self, title: str):
        super().__init__(title)
        self._column = QVBoxLayout(self)

    # --- widget factories ---------------------------------------------------

    def knob(self, *args, **kwargs) -> Knob:
        widget = Knob(*args, **kwargs)
        widget.slider.valueChanged.connect(self.changed)
        return self._add(widget)

    def combo(self, items) -> QComboBox:
        widget = QComboBox()
        widget.addItems(items)
        widget.currentIndexChanged.connect(self.changed)
        return self._add(widget)

    def check(self, text: str, checked: bool = False) -> QCheckBox:
        widget = QCheckBox(text)
        widget.setChecked(checked)
        widget.toggled.connect(self.changed)
        return self._add(widget)

    def button(self, text: str, slot) -> QPushButton:
        """An action button. Its slot is its own — it does not report `changed`."""
        widget = QPushButton(text)
        widget.clicked.connect(slot)
        return self._add(widget)

    def note(self, text: str) -> QLabel:
        """A wrapped explanatory line. Emits nothing — it is just prose."""
        widget = QLabel(text)
        widget.setWordWrap(True)
        return self._add(widget)

    def _add(self, widget):
        self._column.addWidget(widget)
        return widget

    # --- contract -----------------------------------------------------------

    def values(self) -> dict:
        """The section's knobs as `Settings` field names -> values."""
        raise NotImplementedError
