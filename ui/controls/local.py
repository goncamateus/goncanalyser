"""Local tab — keypoint detectors and their descriptors."""

from features.keypoints import DETECTORS

from .base import Section


class LocalTab(Section):
    def __init__(self):
        super().__init__()

        self.group("Detector")
        self.combo(DETECTORS, field="detector")
        self.note(
            "<b>SIFT</b> — 128-d float descriptor, scale and rotation invariant, slow.<br>"
            "<b>ORB</b> — 32-byte binary descriptor, fast enough for video.<br><br>"
            "SURF is absent on purpose: it is patented and excluded from every "
            "published OpenCV wheel. AKAZE, BRISK and KAZE are gone from the "
            "opencv-python 5.0 Python bindings, and its ALIKED and DISK need ONNX "
            "model files that are not shipped."
        )

        self.group("Parameters")
        self.knob(
            "Sensitivity", 0.0, 1.0, 0.5, 100,
            "one normalised knob for both detectors — their native thresholds are on "
            "different scales (SIFT ~0.04, ORB ~20). Up always means more keypoints.",
            field="kp_sensitivity",
        )
        self.knob("Max keypoints", 10, 5000, 500, tip="strongest by response are kept",
                  field="kp_max", cast=int)
        self.knob("Octave layers", 1, 8, 3, tip="scale-space depth; more finds features "
                  "across a wider size range and costs more",
                  field="kp_octaves", cast=int)
        self.knob("Edge threshold", 1, 50, 10, tip="rejects keypoints lying along an edge, "
                  "which are poorly localised in one direction",
                  field="kp_edge")

        self.group("Overlay")
        self.check("Draw scale and orientation", checked=True, field="kp_rich")
        self.note(
            "Rich keypoints draw each one's scale circle and orientation ray. Turn it "
            "off for a plain scatter when there are thousands of them."
        )

        self.stretch()
