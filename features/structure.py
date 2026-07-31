"""Structural and geometric analysis: edges, lines, corners, contours, blobs.

Five independent detectors that happen to share an input. Each one is off by
default and costs nothing when off, so this module is cheap to leave loaded.

Two inputs are borrowed rather than recomputed, which is the point of the
`Result` collector:

* **contours read the "Threshold" canvas** that `adjust` always fills. Contour
  finding wants a binary image and thresholding is how you get one, so pointing
  the contour finder anywhere else would mean tuning the same thing twice.
* **Hough always makes its own Canny** from `canny_lo`/`canny_hi`, even when the
  edge combo is on Sobel — `HoughLinesP` needs a *binary* edge map and a Sobel
  magnitude is not one.
"""

from dataclasses import replace

import cv2
import numpy as np

from core.settings import Settings

from .adjust import odd_kernel, to_bgr, to_gray

EDGES = ("None", "Canny", "Sobel", "Laplacian")
HOUGH = ("None", "Lines", "Circles")
CORNERS = ("None", "Harris", "Shi-Tomasi")
CONTOUR_MODES = {
    "External": cv2.RETR_EXTERNAL,
    "List": cv2.RETR_LIST,
    "Tree": cv2.RETR_TREE,
}

LINE_COLOR = (0, 255, 0)
CIRCLE_COLOR = (255, 255, 0)
CORNER_COLOR = (0, 0, 255)
CONTOUR_COLOR = (0, 255, 255)
BOX_COLOR = (255, 160, 0)
BLOB_COLOR = (255, 0, 255)


def edge_map(gray: np.ndarray, s: Settings) -> np.ndarray:
    """Single-channel uint8 edge image for the chosen operator."""
    if s.edge_kind == "Canny":
        return cv2.Canny(gray, int(s.canny_lo), int(s.canny_hi))
    if s.edge_kind == "Sobel":
        # ksize must be 1/3/5/7 or OpenCV throws. dx and dy may not both be 0.
        k = min(7, odd_kernel(s.sobel_k))
        dx, dy = int(s.sobel_dx), int(s.sobel_dy)
        if not dx and not dy:
            dx = 1
        return cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_64F, dx, dy, ksize=k))
    return cv2.convertScaleAbs(cv2.Laplacian(gray, cv2.CV_64F, ksize=min(31, odd_kernel(s.lap_k))))


def corners(gray: np.ndarray, s: Settings) -> np.ndarray:
    """(N, 2) array of corner coordinates, capped at `corner_max`."""
    if s.corner_kind == "Shi-Tomasi":
        found = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=max(1, int(s.corner_max)),
            qualityLevel=max(1e-4, s.corner_quality),
            minDistance=max(1, int(s.corner_min_dist)),
        )
        return np.empty((0, 2)) if found is None else found.reshape(-1, 2)

    response = cv2.cornerHarris(np.float32(gray), blockSize=2, ksize=3, k=s.harris_k)
    peak = response.max()
    if peak <= 0:
        return np.empty((0, 2))
    ys, xs = np.nonzero(response > s.corner_quality * peak)
    points = np.column_stack((xs, ys)).astype(np.float32)
    if len(points) <= s.corner_max:
        return points
    # Harris marks every pixel over the threshold, so a strong corner comes back
    # as a blob of dozens. Keep the strongest, or the cap would just truncate
    # whichever ones happened to be scanned first (i.e. the top-left of the image).
    order = np.argsort(response[ys, xs])[::-1][: int(s.corner_max)]
    return points[order]


def blob_detector(s: Settings) -> cv2.SimpleBlobDetector:
    """SimpleBlobDetector with the filters the panel exposes. 0 disables a filter."""
    p = cv2.SimpleBlobDetector.Params()
    p.filterByColor = True
    p.blobColor = 0 if s.blob_dark else 255
    p.filterByArea = True
    p.minArea = float(max(1, s.blob_min_area))
    p.maxArea = float(max(s.blob_min_area + 1, s.blob_max_area))
    p.filterByCircularity = s.blob_circularity > 0
    p.minCircularity = max(1e-3, s.blob_circularity)
    p.filterByConvexity = s.blob_convexity > 0
    p.minConvexity = max(1e-3, s.blob_convexity)
    p.filterByInertia = False
    return cv2.SimpleBlobDetector.create(p)


def run(frame: np.ndarray, s: Settings, out, state=None) -> None:
    gray = to_gray(frame)

    if s.edge_kind != "None":
        edges = edge_map(gray, s)
        out.canvases["Edges"] = to_bgr(edges)
        out.metrics["edge_px"] = int(np.count_nonzero(edges))

    if s.hough_kind == "Lines":
        binary = cv2.Canny(gray, int(s.canny_lo), int(s.canny_hi))
        lines = cv2.HoughLinesP(
            binary,
            rho=1,
            theta=np.pi / 180,
            threshold=max(1, int(s.hough_thresh)),
            minLineLength=max(1, int(s.hough_min_len)),
            maxLineGap=max(0, int(s.hough_max_gap)),
        )
        # OpenCV 4 returns (N, 1, 4) here and OpenCV 5 returns (N, 4). Reshaping
        # rather than indexing `[:, 0]` reads the same on both.
        lines = np.empty((0, 4), np.int32) if lines is None else lines.reshape(-1, 4)
        out.metrics["lines"] = len(lines)
        out.rows["lines"] = [
            {"x1": int(a), "y1": int(b), "x2": int(c), "y2": int(d)} for a, b, c, d in lines
        ]
        out.ops.append(
            lambda canvas, ls=lines: [
                cv2.line(canvas, (a, b), (c, d), LINE_COLOR, 1) for a, b, c, d in ls
            ]
        )

    elif s.hough_kind == "Circles":
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=max(1, int(s.hough_min_len)),
            param1=max(1, int(s.canny_hi)),
            param2=max(1, int(s.hough_thresh)),
        )
        found = (
            np.empty((0, 3), int) if circles is None else np.round(circles.reshape(-1, 3)).astype(int)
        )
        out.metrics["circles"] = len(found)
        out.rows["circles"] = [{"x": int(x), "y": int(y), "r": int(r)} for x, y, r in found]
        out.ops.append(
            lambda canvas, cs=found: [
                cv2.circle(canvas, (x, y), r, CIRCLE_COLOR, 1) for x, y, r in cs
            ]
        )

    if s.corner_kind != "None":
        points = corners(gray, s)
        out.metrics["corners"] = len(points)
        out.rows["corners"] = [{"x": float(x), "y": float(y)} for x, y in points]
        out.ops.append(
            lambda canvas, ps=points: [
                cv2.circle(canvas, (int(x), int(y)), 3, CORNER_COLOR, 1) for x, y in ps
            ]
        )

    if s.contours_on:
        _contours(s, out)

    if s.blobs_on:
        found = blob_detector(s).detect(gray)
        out.metrics["blobs"] = len(found)
        out.rows["blobs"] = [
            {"x": kp.pt[0], "y": kp.pt[1], "diameter": kp.size, "response": kp.response}
            for kp in found
        ]
        out.ops.append(
            lambda canvas, kps=found: cv2.drawKeypoints(
                canvas,
                kps,
                canvas,
                BLOB_COLOR,
                cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS,
            )
        )


def _contours(s: Settings, out) -> None:
    """Contours off the threshold canvas, plus their geometry as rows."""
    binary = to_gray(out.canvases["Threshold"])
    found, hierarchy = cv2.findContours(
        binary, CONTOUR_MODES[s.contour_mode], cv2.CHAIN_APPROX_SIMPLE
    )
    # Index into the hierarchy before filtering: OpenCV's parent/child links are
    # positions in the original list, so dropping small contours first would make
    # every remaining link point at the wrong shape.
    parents = (
        [int(h[3]) for h in hierarchy[0]] if hierarchy is not None else [-1] * len(found)
    )
    kept = [
        (c, parents[i]) for i, c in enumerate(found) if cv2.contourArea(c) >= s.contour_min_area
    ]

    out.metrics["contours"] = len(kept)
    out.metrics["contour_area"] = int(sum(cv2.contourArea(c) for c, _ in kept))
    out.rows["contours"] = [
        {
            "area": cv2.contourArea(c),
            "perimeter": cv2.arcLength(c, True),
            "x": int(cv2.boundingRect(c)[0]),
            "y": int(cv2.boundingRect(c)[1]),
            "w": int(cv2.boundingRect(c)[2]),
            "h": int(cv2.boundingRect(c)[3]),
            "parent": parent,
        }
        for c, parent in kept
    ]

    shapes = [c for c, _ in kept]
    mask = np.zeros(binary.shape, np.uint8)
    cv2.drawContours(mask, shapes, -1, 255, cv2.FILLED)
    out.canvases["Contour mask"] = to_bgr(mask)

    def draw(canvas, shapes=shapes):
        cv2.drawContours(canvas, shapes, -1, CONTOUR_COLOR, 1)
        if s.contour_boxes:
            for c in shapes:
                x, y, w, h = cv2.boundingRect(c)
                cv2.rectangle(canvas, (x, y), (x + w, y + h), BOX_COLOR, 1)

    out.ops.append(draw)


def _demo() -> None:
    """A synthetic square: every detector must find the thing that is obviously there."""
    from core.pipeline import Result

    from . import adjust

    frame = np.zeros((200, 200, 3), np.uint8)
    cv2.rectangle(frame, (50, 50), (150, 150), (255, 255, 255), -1)
    base = Settings(threshold_kind="Binary", threshold=127)

    def analyse(s):
        out = Result()
        adjust.run(frame, s, out)
        run(adjust.apply(frame, s), s, out)
        return out

    edges = analyse(replace(base, edge_kind="Canny")).metrics["edge_px"]
    assert edges > 300, f"a 100px square has ~400px of outline, got {edges}"
    for kind in EDGES[1:]:
        got = analyse(replace(base, edge_kind=kind))
        assert got.canvases["Edges"].shape == frame.shape, kind

    # Four sides, so at least four line segments — Hough usually splits them more.
    assert analyse(replace(base, hough_kind="Lines", hough_thresh=50)).metrics["lines"] >= 4

    for kind in CORNERS[1:]:
        found = analyse(replace(base, corner_kind=kind)).metrics["corners"]
        assert 4 <= found <= 200, f"{kind} found {found} corners on a square"

    got = analyse(replace(base, contours_on=True))
    assert got.metrics["contours"] == 1, got.metrics
    row = got.rows["contours"][0]
    assert abs(row["area"] - 100 * 100) < 500, row
    assert (row["w"], row["h"]) == (101, 101), row
    assert got.canvases["Contour mask"].shape == frame.shape

    # A dark square on white is what SimpleBlobDetector looks for by default.
    inverted = np.full((200, 200, 3), 255, np.uint8)
    cv2.circle(inverted, (100, 100), 30, (0, 0, 0), -1)
    out = Result()
    s = replace(base, blobs_on=True, threshold_kind="None", blob_max_area=20000)
    adjust.run(inverted, s, out)
    run(adjust.apply(inverted, s), s, out)
    assert out.metrics["blobs"] == 1, out.metrics

    # Nothing on measures nothing, and every branch tolerates an empty image.
    empty = analyse(Settings(edge_kind="Canny", hough_kind="Circles", contours_on=True))
    assert empty.metrics["circles"] == 0

    print("structure ok")


if __name__ == "__main__":
    _demo()
