"""Section B — contour finding: blur, Canny thresholds, minimum area."""

from .base import Section


class ContourSection(Section):
    """Toggle plus the four knobs that decide which outlines get drawn."""

    def __init__(self):
        super().__init__("B · Contour Finding")
        self.enabled = self.check("Draw contours")
        # Only odd kernels are legal; the pipeline rounds up, so the slider is
        # free to land anywhere including 0 (= no blur).
        self.blur = self.knob("Blur kernel", 0, 31, 5, tip="0 or 1 = no blur; even values round up")
        self.canny_lo = self.knob("Canny lower", 0, 500, 50, tip="edges below this are discarded")
        self.canny_hi = self.knob("Canny upper", 0, 500, 150, tip="edges above this always kept")
        self.min_area = self.knob("Min contour area", 0, 5000, 200, tip="in pixels of the frame")
        self.note("Contours are found on whatever the stages above produced, so with "
                  "background subtraction on they outline the moving regions.")

    def values(self) -> dict:
        return {
            "contours_on": self.enabled.isChecked(),
            "blur_kernel": int(self.blur.value()),
            "canny_lo": int(self.canny_lo.value()),
            "canny_hi": int(self.canny_hi.value()),
            "min_area": int(self.min_area.value()),
        }
