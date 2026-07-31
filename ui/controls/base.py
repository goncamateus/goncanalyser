"""Shared building blocks for the control tabs.

Two pieces:

* `Knob`  — a labelled slider with a live readout, and integer-only Qt sliders
            faked into decimals via a `scale` factor.
* `Section` — a tab's worth of controls that emits one `changed` signal for *any*
            widget in it and knows how to report its own values as a dict.

The dict is the whole contract with the main window: it merges the five tabs'
dicts into one `Settings` and hands it to the worker. Adding a knob therefore
means touching exactly one file — the tab it belongs to.

Each factory also takes the `Settings` field it feeds. That one extra argument is
what lets this class generate `values()` *and* its inverse `restore()` for every
tab, instead of each one hand-writing two mirror-image mappings that drift apart
the first time a knob is added to only one of them.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
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


class Section(QWidget):
    """One tab of controls, reporting a single `changed` signal for all of them.

    Subclasses build their widgets with `self.knob(...)`, `self.combo(...)` and
    `self.check(...)`, which create the widget, stack it in the current group and
    wire its change signal to `changed` — so no subclass ever has to remember the
    connection step.

    `cast`/`back` convert between the widget's natural type and the field's, in
    that order — `cast` on the way out, `back` on the way in.
    """

    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._fields: dict[str, tuple] = {}  # field -> (widget, kind, cast, back)
        # Two references, and the difference matters: `_root` is the tab's own
        # column and never changes, `_column` is wherever the next widget goes.
        # Adding a group to `_column` instead would nest it inside the previous
        # group — Hough inside Edges, Corners inside Hough, all the way down.
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(6, 6, 6, 6)
        self._column = self._root

    # --- structure ----------------------------------------------------------

    def group(self, title: str) -> QGroupBox:
        """Start a titled box. Everything added after this lands inside it.

        Groups are siblings, always: each one is added to the tab's root column,
        not to whichever group came before it.

        The tab bar names the *family* ("Structures"); a tab still holds four or
        five independent detectors, and a wall of thirty sliders with no headings
        is unreadable. These are plain boxes, not collapsibles — the point of
        choosing tabs was that nothing hides.
        """
        box = QGroupBox(title)
        self._root.addWidget(box)
        self._column = QVBoxLayout(box)
        return box

    def stretch(self) -> None:
        """Push everything up. Call once at the end of a tab's __init__."""
        self._root.addStretch(1)

    # --- thumbnails, for the tabs that have any -----------------------------

    def previews(self) -> tuple[str, ...]:
        """Canvases this tab wants a thumbnail of while it is the visible one."""
        return ()

    def show_preview(self, name: str, image) -> None:
        """Paint one. Only ever called with a name this tab asked for."""

    # --- widget factories ---------------------------------------------------

    def knob(self, name: str, *args, field: str = "", cast=None, **kwargs) -> Knob:
        widget = Knob(name, *args, **kwargs)
        widget.slider.valueChanged.connect(self.changed)
        return self._add(widget, field, "knob", cast)

    def combo(self, items, field: str = "", cast=None, back=None) -> QComboBox:
        widget = QComboBox()
        widget.addItems(list(items))
        widget.currentIndexChanged.connect(self.changed)
        return self._add(widget, field, "combo", cast, back)

    def check(self, text: str, checked: bool = False, field: str = "") -> QCheckBox:
        widget = QCheckBox(text)
        widget.setChecked(checked)
        widget.toggled.connect(self.changed)
        return self._add(widget, field, "check")

    def spin(
        self,
        name: str,
        lo: int = 0,
        hi: int = 10_000,
        value: int = 0,
        step: int = 10,
        tip: str = "",
        field: str = "",
    ) -> QSpinBox:
        """A labelled number box with up/down arrows. For values you want to type.

        A slider is right for a knob you sweep looking for an effect; a pixel
        coordinate is a number you know, or nudge one step at a time.
        """
        widget = QSpinBox()
        widget.setRange(lo, hi)
        widget.setSingleStep(step)
        widget.setValue(value)
        if tip:
            widget.setToolTip(tip)
        widget.valueChanged.connect(self.changed)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(name))
        layout.addWidget(widget, 1)
        self._column.addWidget(row)
        if field:
            self._fields[field] = (widget, "spin", None, None)
        return widget

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

    def _add(self, widget, field: str = "", kind: str = "", cast=None, back=None):
        self._column.addWidget(widget)
        if field:
            self._fields[field] = (widget, kind, cast, back)
        return widget

    # --- the contract with MainWindow ---------------------------------------

    def values(self) -> dict:
        """The tab's controls as `Settings` field names -> values."""
        out = {}
        for field, (widget, kind, cast, _) in self._fields.items():
            raw = (
                widget.value()
                if kind in ("knob", "spin")
                else widget.isChecked()
                if kind == "check"
                else widget.currentText()
            )
            out[field] = cast(raw) if cast else raw
        return out

    def restore(self, data: dict) -> None:
        """Put saved values back into the widgets. Unknown fields are ignored.

        Signals stay blocked throughout: restoring forty controls one at a time
        would otherwise fire forty settings rebuilds, and any field the saved
        file does not carry keeps the widget's own default.
        """
        blocked = self.signalsBlocked()
        self.blockSignals(True)
        try:
            for field, (widget, kind, _, back) in self._fields.items():
                if field not in data:
                    continue
                value = back(data[field]) if back else data[field]
                if kind == "knob":
                    widget.set_value(float(value))
                elif kind == "spin":
                    # QSpinBox has setValue, not the Knob's set_value.
                    widget.setValue(int(value))
                elif kind == "check":
                    widget.setChecked(bool(value))
                else:
                    widget.setCurrentText(str(value))
        finally:
            self.blockSignals(blocked)


class Preview(QLabel):
    """A fixed-height thumbnail for a canvas the viewer is not currently showing.

    Lives inside a tab next to the controls that produce it, which is the point
    of the tabbed layout: the histogram is visible while you drag the knob that
    changes it, without giving up the main viewer.
    """

    def __init__(self, height: int = 150):
        super().__init__("—")
        self.setMinimumHeight(height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: rgba(128,128,128,0.12);")

    def show_image(self, image) -> None:
        from PyQt6.QtGui import QPixmap

        self.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def _demo() -> None:
    """The two ways a tab can be silently wrong: bad layout, or a field that lies.

    Lives here rather than in the package `__init__` only because `python -m`
    cannot run a package. The tabs are imported inside the function, so importing
    this module never pulls them in — which is what keeps the cycle away, since
    every tab imports `Section` from here.
    """
    from dataclasses import asdict, fields

    from PyQt6.QtWidgets import QApplication

    from core.settings import Settings

    from . import TABS

    app = QApplication.instance() or QApplication([])
    known = {f.name for f in fields(Settings)}
    declared: set[str] = set()

    for factory in TABS:
        tab = factory()
        name = factory.__name__

        # Groups must be siblings. Adding one to the *current* column instead of
        # the tab's root nests it inside its predecessor — Hough inside Edges,
        # Corners inside Hough — which looks like a styling glitch and is not.
        for box in tab.findChildren(QGroupBox):
            parent = box.parentWidget()
            assert not isinstance(parent, QGroupBox), (
                f"{name}: '{box.title()}' is nested inside '{parent.title()}'"
            )

        # A field name Settings does not have raises deep in the worker on the
        # first frame, far from the typo that caused it.
        unknown = set(tab._fields) - known
        assert not unknown, f"{name} declares fields Settings has no room for: {unknown}"
        declared |= set(tab._fields)

        # values() and restore() are generated from the same declaration, so they
        # must be exact inverses. They stop being so the moment a `cast` has no
        # matching `back`.
        before = tab.values()
        tab.restore(before)
        assert tab.values() == before, f"{name}: values()/restore() are not inverses"

    # `view` lives on the transport bar, not in a tab. Everything else must be
    # reachable, or it is a knob nobody can turn.
    orphans = known - declared - {"view"}
    assert not orphans, f"Settings fields no tab exposes: {orphans}"

    print(f"controls ok ({len(declared)} fields across {len(TABS)} tabs, no nesting)")
    del app


if __name__ == "__main__":
    _demo()
