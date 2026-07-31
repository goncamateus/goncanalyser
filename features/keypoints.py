"""Local feature detectors and descriptors: SIFT and ORB.

These are what this OpenCV build actually offers. `opencv-python` 5.0 ships no
AKAZE, BRISK or KAZE in its Python bindings, its ALIKED and DISK need ONNX model
files that are not bundled, and SURF is patented and excluded from every
published wheel. SIFT and ORB are the two that work out of the box, and between
them they cover the trade-off worth teaching: SIFT is a 128-d float descriptor
that is slower and more discriminative, ORB is a 32-byte binary one that is fast
enough for video.

The one knob worth explaining is **sensitivity**. Both detectors have a
threshold and they are not on the same scale — SIFT wants ~0.04, ORB wants ~20.
Exposing the raw number would make the control meaningless the moment you switch
detector, so the panel has one 0..1 knob and `SENSITIVITY` holds each detector's
real range. Turning it up always means more keypoints.
"""

from dataclasses import replace

import cv2
import numpy as np

from core.settings import Settings

from .adjust import to_gray

DETECTORS = ("None", "SIFT", "ORB")

# detector -> (threshold at sensitivity 0, threshold at sensitivity 1).
# Both ranges run strict -> permissive, so the knob reads the same way for each
# even though SIFT's number falls as ORB's does too but from a different scale.
SENSITIVITY: dict[str, tuple[float, float]] = {
    "SIFT": (0.16, 0.005),  # contrastThreshold
    "ORB": (60.0, 3.0),  # fastThreshold
}

KP_COLOR = (0, 200, 255)


def threshold_for(s: Settings) -> float:
    """The chosen detector's native threshold, from the normalised knob."""
    lo, hi = SENSITIVITY[s.detector]
    return lo + (hi - lo) * min(1.0, max(0.0, s.kp_sensitivity))


def build(s: Settings):
    """The configured detector, or None when nothing is selected."""
    if s.detector not in SENSITIVITY:
        return None
    value = threshold_for(s)
    octaves = max(1, int(s.kp_octaves))
    if s.detector == "SIFT":
        return cv2.SIFT.create(
            nfeatures=max(0, int(s.kp_max)),
            nOctaveLayers=octaves,
            contrastThreshold=value,
            edgeThreshold=s.kp_edge,
        )
    return cv2.ORB.create(
        nfeatures=max(1, int(s.kp_max)),
        nlevels=octaves + 5,
        edgeThreshold=max(1, int(s.kp_edge)),
        fastThreshold=max(1, int(value)),
    )


def detect(gray: np.ndarray, s: Settings):
    """(keypoints, descriptors), strongest first and capped at `kp_max`.

    SIFT's `nfeatures` cap is applied *before* its own scoring in some builds and
    ORB's is a target rather than a limit, so the cap is re-applied here. It also
    means the knob keeps meaning the same thing if another detector is added.
    """
    detector = build(s)
    if detector is None:
        return [], None
    found, described = detector.detectAndCompute(gray, None)
    if not found:
        return [], None
    if len(found) > s.kp_max:
        order = np.argsort([-kp.response for kp in found])[: int(s.kp_max)]
        found = [found[i] for i in order]
        described = None if described is None else described[order]
    return found, described


def run(frame: np.ndarray, s: Settings, out, state=None) -> None:
    if s.detector == "None":
        return
    found, described = detect(to_gray(frame), s)
    out.metrics["keypoints"] = len(found)
    if described is not None:
        out.metrics["descriptor"] = f"{described.shape[1]}d"
    out.rows["keypoints"] = [
        {
            "x": kp.pt[0],
            "y": kp.pt[1],
            "size": kp.size,
            "angle": kp.angle,
            "response": kp.response,
            "octave": kp.octave,
        }
        for kp in found
    ]

    # Rich keypoints draw the scale circle and orientation ray, which is the
    # whole point of looking at SIFT output rather than a scatter of dots.
    flags = (
        cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS
        if s.kp_rich
        else cv2.DRAW_MATCHES_FLAGS_DEFAULT
    )
    out.ops.append(
        lambda canvas, kps=found: cv2.drawKeypoints(canvas, kps, canvas, KP_COLOR, flags)
    )


def _demo() -> None:
    """Both detectors find the corners of a synthetic checkerboard."""
    from core.pipeline import Result

    board = np.zeros((240, 240), np.uint8)
    for y in range(0, 240, 40):
        for x in range(0, 240, 40):
            if (x // 40 + y // 40) % 2:
                board[y : y + 40, x : x + 40] = 255
    frame = cv2.cvtColor(board, cv2.COLOR_GRAY2BGR)
    base = Settings(kp_sensitivity=0.8)

    for name in DETECTORS[1:]:
        s = replace(base, detector=name)
        found, described = detect(board, s)
        assert found, f"{name} found nothing on a checkerboard"
        assert described is not None and len(described) == len(found), name

        out = Result(canvases={"Source": frame})
        run(frame, s, out)
        assert out.metrics["keypoints"] == len(found), name
        assert len(out.rows["keypoints"]) == len(found), name
        # The overlay must not resize or retype the canvas it is handed.
        canvas = frame.copy()
        for op in out.ops:
            op(canvas)
        assert canvas.shape == frame.shape and canvas.dtype == np.uint8, name
        assert not (canvas == frame).all(), f"{name} drew nothing"

        # The cap is re-applied here, not left to the detector's own parameter.
        assert len(detect(board, replace(s, kp_max=5))[0]) <= 5, name

        # Turning sensitivity up must never find fewer keypoints.
        loose = len(detect(board, replace(s, kp_sensitivity=1.0, kp_max=10**6))[0])
        strict = len(detect(board, replace(s, kp_sensitivity=0.0, kp_max=10**6))[0])
        assert loose >= strict, f"{name} sensitivity runs backwards: {strict} -> {loose}"

    # SIFT is a 128-d float descriptor, ORB a 32-byte binary one. Getting these
    # crossed means the descriptor readout in the panel is lying.
    assert detect(board, replace(base, detector="SIFT"))[1].shape[1] == 128
    assert detect(board, replace(base, detector="ORB"))[1].shape[1] == 32

    # Off is off.
    out = Result(canvases={"Source": frame})
    run(frame, Settings(), out)
    assert not out.metrics and not out.ops

    print("keypoints ok")


if __name__ == "__main__":
    _demo()
