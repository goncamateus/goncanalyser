"""Structures tab — edges, lines, corners, contours, blobs.

Five independent detectors. Each stays off until its combo or checkbox says
otherwise, so this tab can be read top to bottom without anything running.
"""

from features.structure import CONTOUR_MODES, CORNERS, EDGES, HOUGH

from .base import Section


class StructuresTab(Section):
    def __init__(self):
        super().__init__()

        self.group("Edges")
        self.combo(EDGES, field="edge_kind")
        self.knob("Canny low", 0, 500, 100, tip="below this a pixel is never an edge",
                  field="canny_lo", cast=int)
        self.knob("Canny high", 0, 500, 200, tip="above this it always is; between the "
                  "two it survives only when connected to a strong edge",
                  field="canny_hi", cast=int)
        self.knob("Sobel kernel", 1, 7, 3, tip="odd, clamped to 7", field="sobel_k", cast=int)
        self.knob("Sobel dx", 0, 2, 1, tip="order of the x derivative",
                  field="sobel_dx", cast=int)
        self.knob("Sobel dy", 0, 2, 1, tip="order of the y derivative; dx and dy may not "
                  "both be 0", field="sobel_dy", cast=int)
        self.knob("Laplacian kernel", 1, 31, 3, tip="odd", field="lap_k", cast=int)

        self.group("Hough")
        self.combo(HOUGH, field="hough_kind")
        self.knob("Votes", 1, 400, 120, tip="accumulator threshold — how much evidence a "
                  "line or circle needs", field="hough_thresh", cast=int)
        self.knob("Min length / min distance", 1, 400, 50,
                  tip="shortest line segment kept; for circles, the closest two centres "
                      "may be", field="hough_min_len", cast=int)
        self.knob("Max gap", 0, 100, 10, tip="lines only: gap that still counts as one line",
                  field="hough_max_gap", cast=int)
        self.note(
            "Hough always builds its own Canny from the two thresholds above, even when "
            "the edge combo is on Sobel — it needs a <i>binary</i> edge map and a Sobel "
            "magnitude is not one."
        )

        self.group("Corners")
        self.combo(CORNERS, field="corner_kind")
        self.knob("Max corners", 1, 2000, 200, field="corner_max", cast=int)
        self.knob("Quality", 0.001, 0.2, 0.01, 1000,
                  "fraction of the strongest response a corner must reach",
                  field="corner_quality")
        self.knob("Min distance (px)", 1, 100, 10, tip="Shi-Tomasi only",
                  field="corner_min_dist", cast=int)
        self.knob("Harris k", 0.01, 0.2, 0.04, 1000, "Harris only; lower detects more",
                  field="harris_k")

        self.group("Contours")
        self.check("Find contours", field="contours_on")
        self.combo(CONTOUR_MODES.keys(), field="contour_mode")
        self.knob("Min area (px)", 0, 5000, 50, field="contour_min_area", cast=int)
        self.check("Bounding boxes", checked=True, field="contour_boxes")
        self.note(
            "Read off the <b>Threshold</b> image, not the edges — set that up on the "
            "Image Adjustment tab first. Area, perimeter, bounding box and parent go "
            "into the exported <code>contours.csv</code>; <i>Tree</i> mode is the one "
            "that fills the parent column."
        )

        self.group("Blobs")
        self.check("Find blobs", field="blobs_on")
        self.knob("Min area (px)", 1, 5000, 50, field="blob_min_area", cast=int)
        self.knob("Max area (px)", 2, 50000, 5000, field="blob_max_area", cast=int)
        self.knob("Min circularity", 0.0, 1.0, 0.0, 100, "0 disables; 1 is a perfect circle",
                  field="blob_circularity")
        self.knob("Min convexity", 0.0, 1.0, 0.0, 100, "0 disables; low values allow dents",
                  field="blob_convexity")
        self.check("Dark blobs on light", checked=True, field="blob_dark")

        self.stretch()
