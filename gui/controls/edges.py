"""Section C — edge detection: blur, then the two Canny thresholds."""

from .base import Section

VIEWS = ("Overlay", "Edges only")  # second entry means Settings.edges_only


class EdgeSection(Section):
    """Toggle plus the three knobs that decide which edges survive."""

    def __init__(self):
        super().__init__("C · Edge Detection")
        self.enabled = self.check("Detect edges", field="edges_on")
        # Only odd kernels are legal; the pipeline rounds up, so the slider is
        # free to land anywhere including 0 (= no blur).
        self.blur = self.knob(
            "Blur kernel", 0, 31, 5, tip="0 or 1 = no blur; even values round up",
            field="blur_kernel", cast=int,
        )
        # Canny's hysteresis: above the upper threshold is always an edge, below
        # the lower never is, and what lies between survives only if it connects
        # to something above. A 1:2 or 1:3 ratio is the usual starting point —
        # set them equal and the hysteresis does nothing, leaving speckle.
        self.canny_lo = self.knob(
            "Canny lower", 0, 500, 50, tip="below this, never an edge",
            field="canny_lo", cast=int,
        )
        self.canny_hi = self.knob(
            "Canny upper", 0, 500, 150, tip="above this, always an edge",
            field="canny_hi", cast=int,
        )
        self.view = self.combo(
            VIEWS,
            field="edges_only",
            cast=lambda text: text == VIEWS[1],
            back=lambda flag: VIEWS[1] if flag else VIEWS[0],
        )
        self.note(
            "Edges are found <b>after</b> background subtraction, on the motion mask "
            "itself — so with it on you get the outline of what moved, and with it off "
            "the edges of the adjusted frame. The status bar reports how much of the "
            "frame came back as edge; a few percent is a healthy setting."
        )
