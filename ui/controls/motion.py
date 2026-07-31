"""Motion tab — heatmap, foreground extraction, and which algorithm found it.

Every knob for all six algorithms is on screen at once, and which ones are live
depends on the combo at the top. That is deliberate and matches the rest of the
workspace: nothing hides, and a parameter you cannot see is a parameter you
cannot compare. Each group says which algorithms read it.
"""

from features.motion import MOTION_ALGOS

from .base import Preview, Section


class MotionTab(Section):
    def __init__(self):
        super().__init__()

        self.group("Algorithm")
        self.combo(MOTION_ALGOS, field="motion_algo")
        self.knob("Sensitivity", 1, 255, 25,
                  tip="grey levels of change that count as motion — lower finds more",
                  field="motion_threshold", cast=int)
        self.knob("Noise removal", 0, 15, 3,
                  tip="morphological open kernel; 0 or 1 = off. The first thing to "
                      "reach for when the mask is speckled", field="motion_open", cast=int)
        self.note(
            "All six report motion as a 0..255 image before <b>Sensitivity</b> cuts it "
            "into a mask, so the threshold means the same thing whichever you pick. "
            "Optical flow is scaled on the way in — 8 px/frame reads as full scale."
        )

        self.group("Background subtraction — MOG2 and KNN")
        self.knob("Learning rate", -1.0, 1.0, -1.0, 100,
                  "-1 lets OpenCV pick from History; higher forgets the background faster",
                  field="motion_learning")
        self.knob("MOG2 history", 1, 2000, 500, tip="frames the model is built from",
                  field="mog_history", cast=int)
        self.knob("MOG2 variance", 1, 100, 16, tip="lower is more sensitive",
                  field="mog_var")
        self.check("MOG2 shadows", checked=True, field="mog_shadows")
        self.knob("KNN history", 1, 2000, 500, field="knn_history", cast=int)
        self.knob("KNN distance", 10, 2000, 400, tip="squared distance to a neighbour",
                  field="knn_dist")
        self.check("KNN shadows", checked=True, field="knn_shadows")
        self.note(
            "Detected shadows are found but never counted — a shadow is the moving "
            "thing's effect on the background, not the moving thing. Untick to spend "
            "nothing looking for them."
        )

        self.group("Optical flow — Farneback and Lucas-Kanade")
        self.knob("Pyramid scale", 0.1, 0.9, 0.5, 100,
                  "each level this fraction of the last", field="fb_pyr_scale")
        self.knob("Pyramid levels", 1, 8, 3, tip="more levels catch faster motion",
                  field="fb_levels", cast=int)
        self.knob("Window (px)", 3, 51, 15, tip="bigger is smoother and less precise",
                  field="fb_winsize", cast=int)
        self.knob("Iterations", 1, 10, 3, field="fb_iterations", cast=int)
        self.knob("LK max points", 1, 1000, 200, tip="corners tracked per frame",
                  field="lk_max_points", cast=int)
        self.knob("LK window (px)", 3, 51, 15, tip="also the size of the disc each "
                  "tracked point paints", field="lk_win", cast=int)
        self.note(
            "<b>Farneback is the slow one: 30-60 ms a frame at 640x512.</b> It runs off "
            "the GUI thread, but playback will drop frames.<br><br>"
            "Lucas-Kanade is <i>sparse</i> — it tracks corners, so its mask is a disc "
            "per point rather than the outline of anything. Use Farneback when the "
            "shape of the moving thing matters."
        )

        self.group("Heatmap")
        self.heat_on = self.check("Overlay the heatmap on the view", field="heat_on")
        self.knob("Opacity", 0.0, 1.0, 0.5, 100, field="heat_opacity")
        self.knob("Window (frames)", 1, 200, 20,
                  tip="how far back the heat is averaged; longer settles, shorter reacts",
                  field="heat_window", cast=int)
        self.knob("Floor", 0.0, 1.0, 0.05, 100,
                  "fraction of full scale below which a pixel stays cold",
                  field="heat_threshold")
        self.heat = Preview()
        self._column.addWidget(self.heat)
        self.note(
            "Blue is rare motion, red is constant motion. Cold pixels are left as the "
            "frame rather than painted blue, so the overlay stays readable. Draw a "
            "region on the Adjust tab and the heat is confined to it."
        )

        self.group("Moving objects")
        self.knob("Min area (px)", 0, 5000, 50, tip="contours smaller than this are noise",
                  field="motion_min_area", cast=int)
        self.boxes = self.check("Bounding boxes", checked=True, field="motion_boxes")
        self.check("Label area and speed", field="motion_metrics")
        self.knob("Max travel (px/frame)", 1, 500, 60,
                  tip="further than this and two blobs are not the same object",
                  field="motion_max_travel", cast=int)
        self.mask = Preview()
        self._column.addWidget(self.mask)
        self.note(
            "Speed is nearest-centroid between frames, in pixels per frame — it says "
            "how fast something here is moving, not where object 7 went. Box geometry, "
            "area and speed go into the exported <code>motion.csv</code>; tick "
            "<b>objects/</b> in the export dialog to also get each one cropped out."
        )

        self.stretch()

    def previews(self) -> tuple[str, ...]:
        return ("Motion heatmap", "Motion mask")

    def show_preview(self, name: str, image) -> None:
        target = {"Motion heatmap": self.heat, "Motion mask": self.mask}.get(name)
        if target is not None:
            target.show_image(image)
