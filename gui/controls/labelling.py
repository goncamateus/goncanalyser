"""Section C — labelling and dataset export.

The odd one out: it registers no `Settings` fields, because nothing here tunes an
image. It is a readout and two actions, and the labelling itself happens on the
keyboard, where it belongs — with one keystroke per frame you can walk a clip in
a sitting, which you cannot do reaching for a widget each time.
"""

from PyQt6.QtCore import pyqtSignal

from .base import Section


class LabelSection(Section):
    """Live counts, the key legend, and the export button."""

    export_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self):
        super().__init__("C · Labelling")
        self.summary = self.note("nothing labelled yet")
        self.note(
            "<b>0</b>–<b>9</b> pick that numbered plume as the real one · "
            "<b>N</b> none of them (a negative sample) · "
            "<b>U</b> undo the label on this frame<br><br>"
            "Picks are stored as a <i>point in the image</i>, not as the number you "
            "pressed, so re-tuning the detector re-binds them to whichever plume is "
            "nearest instead of silently relabelling the wrong one. A pick whose plume "
            "no longer exists is reported lost and left out of the export."
        )
        self.button("Export COCO dataset…", self.export_requested.emit)
        self.button("Clear all labels", self.clear_requested.emit)

    def show_summary(self, counts: dict, frames: int, current: str) -> None:
        """Repaint the counts line, and say what *this* frame is.

        The per-frame part matters more than the totals: it is the only feedback
        that a keystroke landed on a frame where nothing was detected, and the
        only place a re-anchored pick can report itself lost.
        """
        self.summary.setText(
            f"this frame: <b>{current}</b><br>"
            f"{counts['labelled']} labelled · {counts['negative']} negative · "
            f"{frames} frames in the clip"
        )
