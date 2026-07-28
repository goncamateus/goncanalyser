"""Section B — plume detection: source finding, then the plume grown out of it.

Grouped in the order the detector runs, because that is the order you tune in:
find the vent first, then decide how far the plume around it reaches. A knob in
the second group cannot help you if the first group is finding no sources at all.
"""

from processing.pipeline import PLUME_VIEWS

from .base import Section


class PlumeSection(Section):
    """Every knob in `plume.PlumeConfig`, plus what to draw."""

    def __init__(self):
        super().__init__("B · Plume Detection")
        self.enabled = self.check("Detect plumes", field="plume_on")
        self.view = self.combo(PLUME_VIEWS, field="plume_view")
        self.boxes = self.check("Show search regions", checked=True, field="plume_boxes")

        # --- finding the vent ------------------------------------------------
        self.note("<b>Sources</b> — where steam leaves a pipe: hot <i>and</i> dithered.")
        self.p_src = self.knob(
            "Source temperature pct", 90.0, 100.0, 99.0, 10,
            "percentile of the frame a source must reach", field="p_src",
        )
        self.sd_min = self.knob(
            "Source texture (sigma)", 0.0, 60.0, 20.0, 10,
            "above the palette top the sensor dithers; smooth hot metal fails this",
            field="sd_min",
        )
        self.src_close_k = self.knob(
            "Source closing", 1, 21, 7,
            tip="glues the speckle into one blob; too wide merges plume and equipment",
            field="src_close_k", cast=int,
        )
        self.src_min_area = self.knob(
            "Source min area", 0, 2000, 120, tip="px", field="src_min_area", cast=int,
        )
        self.roi_margin = self.knob(
            "Search margin", 0, 200, 20,
            tip="px of slack sideways; the region always runs from the source base upward",
            field="roi_margin", cast=int,
        )

        # --- growing the plume -----------------------------------------------
        self.note("<b>Plume</b> — grown out of each source, bounded by temperature.")
        self.p_hi = self.knob(
            "Core temperature pct", 90.0, 100.0, 99.0, 10,
            "at or above this percentile a pixel is core", field="p_hi",
        )
        self.p_lo = self.knob(
            "Halo temperature pct", 50.0, 100.0, 90.0, 10,
            "below this a pixel is background, period", field="p_lo",
        )
        self.sd_plume = self.knob(
            "Plume texture (sigma)", 0.0, 40.0, 8.0, 10,
            "0 disables; without it the mask leaks into smooth hot equipment",
            field="sd_plume",
        )
        self.open_k = self.knob(
            "Opening", 1, 15, 3, tip="speckle removal", field="open_k", cast=int
        )
        self.close_k = self.knob(
            "Closing", 1, 21, 7, tip="fills the wispy halo", field="close_k", cast=int
        )
        self.min_area = self.knob(
            "Plume min area", 0, 5000, 200, tip="px", field="min_area", cast=int
        )
        self.grow_hot = self.knob(
            "Grow through core", 0, 80, 30,
            tip="geodesic steps along saturated pixels, 2 px each",
            field="grow_hot", cast=int,
        )
        self.grow_warm = self.knob(
            "Grow through halo", 0, 40, 8,
            tip="then this many steps into merely warm pixels",
            field="grow_warm", cast=int,
        )

        # --- holding it steady across frames ---------------------------------
        self.note(
            "<b>Tracking</b> — the raw detector changed how many sources it found on "
            "36 of 59 frame transitions on <i>voo_1</i>. These follow each source "
            "across frames instead."
        )
        self.track_on = self.check("Track sources across frames", checked=True, field="track_on")
        self.max_age = self.knob(
            "Coast for (frames)", 0, 15, 3,
            tip="how long a source is held after the detector loses it — this is what "
                "bridges a 1-2 frame dropout",
            field="max_age", cast=int,
        )
        self.min_hits = self.knob(
            "Confirm after (frames)", 1, 10, 2,
            tip="detections before a new source is shown at all; 1 shows every speck",
            field="min_hits", cast=int,
        )
        self.max_distance = self.knob(
            "Match within (px)", 5, 300, 60,
            tip="how far a source may move between frames and still be the same one",
            field="max_distance",
        )
        self.measure_var = self.knob(
            "Detection noise", 1, 200, 24,
            tip="how much the filter distrusts each detection; raise it to smooth harder",
            field="measure_var",
        )
        self.process_var = self.knob(
            "Motion noise", 1, 100, 12,
            tip="how much the plume is expected to move on its own; raise it to follow "
                "fast drift, lower it to smooth harder",
            field="process_var",
        )

        self.note(
            "Every threshold is a <b>percentile of the frame</b>, not a grey level — the "
            "camera runs AGC, so the same brightness is not the same temperature two "
            "seconds later.<br><br>"
            "Which means Section A is not neutral here: brightness, contrast and gamma "
            "move the histogram these percentiles are taken from. Settle those first, "
            "then calibrate, then leave them alone."
        )
