"""Section B — contour finding: blur, Canny thresholds, minimum area."""

from .base import Section


class ContourSection(Section):
    """Toggle plus the four knobs that decide which outlines get drawn."""

    def __init__(self):
        super().__init__("B · Contour Finding")
        self.enabled = self.check("Draw contours", field="contours_on")
        # Only odd kernels are legal; the pipeline rounds up, so the slider is
        # free to land anywhere including 0 (= no blur).
        self.blur = self.knob(
            "Blur kernel", 0, 31, 5, tip="0 or 1 = no blur; even values round up",
            field="blur_kernel", cast=int,
        )
        self.canny_lo = self.knob(
            "Canny lower", 0, 500, 50, tip="edges below this are discarded",
            field="canny_lo", cast=int,
        )
        self.canny_hi = self.knob(
            "Canny upper", 0, 500, 150, tip="edges above this always kept",
            field="canny_hi", cast=int,
        )
        self.min_area = self.knob(
            "Min contour area", 0, 5000, 200, tip="in pixels of the frame",
            field="min_area", cast=int,
        )
        self.note(
            "Contours run <b>after</b> background subtraction. With it on they are "
            "traced on the motion mask itself — blobs, not edges — so the Canny "
            "sliders do nothing and Min area measures the moving region. With it off "
            "they are Canny edges of the adjusted frame."
        )
