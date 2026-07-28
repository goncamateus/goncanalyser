"""Background subtraction that survives a moving camera.

MOG2 and KNN model *this pixel* over time, so they only work when the pixel grid
is nailed to the world. Under a drone every pixel changes every frame and both
report the whole image as foreground. The geometry here is the opposite of what
they assume: the camera moves, the steam moves, the world does not.

The fix is two stages:

    GlobalMotion    estimate the frame-to-frame camera motion (a 3x3 warp)
    CompensatedSGM  warp the background model by it, *then* compare

The model is a port of the dual-mode single Gaussian model with age from
Yi et al., CVPRW 2013, "Detection of Moving Objects with Non-Stationary Cameras
in 5.8ms" (reference C++ at github.com/kmyid/fastMCD). Two Gaussians per block:
an *apparent* model that answers queries, and a *candidate* that quietly builds
up an alternative. Neither is contaminated by the other, so a plume hanging over
one spot cannot bleed into the background the way a single running average does.

Two things about this footage shape the defaults:

* The plume vents from a fixed *world* location, so once camera motion is
  compensated the plume is stationary in model coordinates. A long history will
  absorb it. What separates steam from hot metal is that it churns — keep the
  age cap short and the candidate model does the rest.
* A planar warp cannot register a 3D scene shot from a translating drone.
  Sharp static edges leave a residual proportional to their gradient, so every
  pixel is charged `edge_tolerance * |grad(background)|` of slack before it may
  be called foreground.
"""

import cv2
import numpy as np

# Ordered as the GUI combo shows them. "flow" is the default: sparse Lucas-Kanade
# is both the fastest and the most forgiving on video, where consecutive frames
# are nearly identical.
GMC_METHODS = ("flow", "orb", "ecc", "none")

IDENTITY = np.eye(3, dtype=np.float32)


def edge_strength(img: np.ndarray) -> np.ndarray:
    """Sobel magnitude, dilated: what a 1 px misregistration would cost here.

    Measured on the background model rather than on the frame — the plume's own
    speckle is a strong gradient too, and charging it slack would erase it.
    """
    src = img.astype(np.float32)
    gx = cv2.Sobel(src, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(src, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    return cv2.dilate(cv2.magnitude(gx, gy), np.ones((5, 5), np.uint8))


class GlobalMotion:
    """Frame-to-frame camera motion as a 3x3 warp, or identity when it fails.

    Estimated on a downscaled grey frame — the camera motion is a global, smooth
    thing, and halving the resolution quarters the work without measurably moving
    the answer.

    Every failure mode (no features, RANSAC gives up, ECC does not converge)
    returns identity with `inliers=0` rather than raising. This runs inside the
    worker thread, and a dropped frame must not take the app down; the caller
    surfaces the zero in the status bar so a dead registration stays visible.
    """

    def __init__(self, method: str = "flow", homography: bool = False, downscale: int = 2):
        self.method = method if method in GMC_METHODS else "flow"
        self.homography = homography
        self.downscale = max(1, int(downscale))

    # --- helpers ------------------------------------------------------------

    def _small(self, gray: np.ndarray) -> np.ndarray:
        if self.downscale == 1:
            return gray
        h, w = gray.shape
        return cv2.resize(gray, (w // self.downscale, h // self.downscale))

    def _fit(self, src_pts: np.ndarray, dst_pts: np.ndarray) -> tuple[np.ndarray, int]:
        """RANSAC fit of src -> dst, returned as a 3x3 and an inlier count.

        Affine by default. A homography has eight degrees of freedom and will
        happily explain a plume as a perspective change when the matches are
        thin; the four-parameter similarity cannot, which is why it is the
        default despite modelling less.
        """
        if len(src_pts) < 5:
            return IDENTITY.copy(), 0
        if self.homography:
            M, inliers = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 3.0)
        else:
            M, inliers = cv2.estimateAffinePartial2D(
                src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=3.0
            )
        if M is None:
            return IDENTITY.copy(), 0
        count = int(inliers.sum()) if inliers is not None else len(src_pts)
        return self._to_3x3(M), count

    def _to_3x3(self, M: np.ndarray) -> np.ndarray:
        """Promote a 2x3 affine to 3x3 and undo the downscale.

        Scaling matters: the rotation/scale block is scale-invariant but the
        translation column was measured in small-image pixels, so it has to be
        multiplied back up. Doing it as S^-1 * M * S handles both at once.
        """
        full = np.eye(3, dtype=np.float32)
        full[: M.shape[0], :] = M
        if self.downscale == 1:
            return full
        d = float(self.downscale)
        up = np.diag([d, d, 1.0]).astype(np.float32)  # small px -> full px
        down = np.diag([1 / d, 1 / d, 1.0]).astype(np.float32)
        return up @ full @ down

    # --- estimators ---------------------------------------------------------

    def estimate(self, prev_gray: np.ndarray, cur_gray: np.ndarray) -> tuple[np.ndarray, int]:
        """Warp taking `prev_gray`'s coordinates to `cur_gray`'s, and its inliers."""
        if self.method == "none" or prev_gray.shape != cur_gray.shape:
            return IDENTITY.copy(), 0
        prev, cur = self._small(prev_gray), self._small(cur_gray)
        try:
            if self.method == "ecc":
                return self._by_ecc(prev, cur)
            if self.method == "orb":
                return self._by_orb(prev, cur)
            return self._by_flow(prev, cur)
        except cv2.error:
            # OpenCV raises on non-convergence and on degenerate inputs alike.
            # Either way the honest answer is "no motion estimate this frame".
            return IDENTITY.copy(), 0

    def _by_flow(self, prev: np.ndarray, cur: np.ndarray) -> tuple[np.ndarray, int]:
        """Shi-Tomasi corners tracked by pyramidal Lucas-Kanade.

        Parameters follow the BoT-SORT / Ultralytics GMC recipe, which is the
        best-tested version of this in the wild.
        """
        pts = cv2.goodFeaturesToTrack(
            prev, maxCorners=1000, qualityLevel=0.01, minDistance=1, blockSize=3
        )
        if pts is None or len(pts) < 5:
            return IDENTITY.copy(), 0
        moved, ok, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None)
        if moved is None:
            return IDENTITY.copy(), 0
        kept = ok.ravel().astype(bool)
        return self._fit(pts[kept].reshape(-1, 2), moved[kept].reshape(-1, 2))

    def _by_orb(self, prev: np.ndarray, cur: np.ndarray) -> tuple[np.ndarray, int]:
        """ORB descriptors matched both ways. Slower, but it survives a big jump."""
        orb = cv2.ORB_create(1000)
        k1, d1 = orb.detectAndCompute(prev, None)
        k2, d2 = orb.detectAndCompute(cur, None)
        if d1 is None or d2 is None or len(k1) < 5 or len(k2) < 5:
            return IDENTITY.copy(), 0
        matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
        if len(matches) < 5:
            return IDENTITY.copy(), 0
        src = np.float32([k1[m.queryIdx].pt for m in matches])
        dst = np.float32([k2[m.trainIdx].pt for m in matches])
        return self._fit(src, dst)

    def _by_ecc(self, prev: np.ndarray, cur: np.ndarray) -> tuple[np.ndarray, int]:
        """Direct photometric alignment. No features, so it works on smooth scenes.

        There is no inlier concept here, so it reports the pixel count as a stand-in
        for "converged" — the caller only ever tests it against zero.
        """
        blur = (3, 3)
        prev = cv2.GaussianBlur(prev.astype(np.float32), blur, 1.5)
        cur = cv2.GaussianBlur(cur.astype(np.float32), blur, 1.5)
        warp = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
        _, warp = cv2.findTransformECC(prev, cur, warp, cv2.MOTION_EUCLIDEAN, criteria, None, 1)
        return self._to_3x3(warp), prev.size


class CompensatedSGM:
    """Dual-mode single Gaussian background model, warped by the camera motion.

    State lives on a grid of `block` x `block` pixel cells — the paper's "one model
    for multiple pixels", which is what makes it real time and also smooths the
    per-pixel noise for free.

    Two models per cell:

        apparent   answers the foreground query
        candidate  builds up an alternative in the background

    A pixel that matches neither updates only the candidate. When the candidate
    has been stable *longer* than the apparent model, the two swap: whatever has
    persisted longest is by definition the background. That indirection is what
    stops a plume that lingers over one spot from being absorbed — it keeps
    resetting the candidate, so the candidate never gets old enough to win.
    """

    VAR_INIT = 900.0  # (30 grey levels)^2 — wide enough that nothing matches at first
    VAR_FLOOR = 25.0  # (5 grey levels)^2 — sensor noise; without it flat sky is all foreground

    def __init__(
        self,
        block: int = 4,
        history: int = 100,
        var_threshold: float = 16.0,
        learning_rate: float = -1.0,
        edge_tolerance: float = 1.5,
        min_age: int = 10,
    ):
        self.block = max(1, int(block))
        self.history = max(1, int(history))  # age cap == how far back the model remembers
        self.var_threshold = float(var_threshold)  # in units of the model's own variance
        self.learning_rate = float(learning_rate)  # -1 = the paper's 1/age schedule
        self.edge_tolerance = float(edge_tolerance)
        self.min_age = max(0, int(min_age))
        self.reset()

    def reset(self) -> None:
        """Forget everything. The model re-seeds from the next frame."""
        self._mean = None  # (2, gh, gw): [apparent, candidate]
        self._var = None
        self._age = None
        self._shape: tuple[int, int] | None = None

    # --- internals ----------------------------------------------------------

    def _seed(self, obs: np.ndarray, shape: tuple[int, int]) -> None:
        """Both models start as the first observation, aged zero and wide open."""
        self._mean = np.stack((obs, obs)).astype(np.float32)
        self._var = np.full_like(self._mean, self.VAR_INIT)
        self._age = np.zeros_like(self._mean)
        self._shape = shape

    def _warp(self, M: np.ndarray) -> None:
        """Move the whole model into the current frame's coordinates.

        The grid is `block` times coarser than the image, so the pixel-space warp
        is conjugated into grid space by S * M * S^-1.

        Bilinear interpolation here *is* the paper's "mixing of neighbouring
        models": a warped cell is a blend of the four it landed between.

        Variance is mixed plainly, *not* inflated by the spatial disagreement
        between the cells that were mixed. Inflating it is the textbook mixture
        formula (Var = E[x^2] - E[x]^2) and it compounds: the model warps every
        frame, so over a textured scene the variance ratchets up until nothing
        can ever exceed it — measured at 30 grey levels of noise on a background
        that is perfectly static. The registration slack it was meant to buy is
        already bought, and bought better, by the `edge_tolerance` term in
        `apply`, which is recomputed from scratch each frame and cannot ratchet.
        """
        gh, gw = self._mean.shape[1:]
        s = 1.0 / self.block
        G = np.diag([s, s, 1.0]).astype(np.float32) @ M @ np.diag(
            [self.block, self.block, 1.0]
        ).astype(np.float32)

        def warped(plane: np.ndarray, border: float) -> np.ndarray:
            return cv2.warpPerspective(
                plane,
                G,
                (gw, gh),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=border,
            )

        for i in range(2):
            self._mean[i] = warped(self._mean[i], 0.0)
            self._var[i] = np.maximum(warped(self._var[i], self.VAR_INIT), self.VAR_FLOOR)
            # Age warps in with border 0: territory the camera just uncovered has
            # no history, and the min_age gate in `apply` keeps it out of the mask
            # until it earns one.
            self._age[i] = warped(self._age[i], 0.0)

    def _update(self, obs: np.ndarray) -> None:
        """Match, update the model that matched, and swap when the candidate wins."""
        diff2 = (obs - self._mean) ** 2
        hit = diff2 < self.var_threshold * np.maximum(self._var, self.VAR_FLOOR)
        # A pixel is only offered to the candidate if the apparent model rejected
        # it — the two models must never learn the same evidence.
        target = np.stack((hit[0], ~hit[0] & hit[1]))
        miss = ~hit[0] & ~hit[1]  # matched nothing: the candidate restarts here

        self._age = np.where(target, np.minimum(self._age + 1, self.history), self._age)
        alpha = (
            1.0 / np.maximum(self._age, 1.0) if self.learning_rate < 0 else self.learning_rate
        )
        mean = self._mean + alpha * (obs - self._mean)
        var = self._var + alpha * (diff2 - self._var)
        self._mean = np.where(target, mean, self._mean)
        self._var = np.where(target, np.maximum(var, self.VAR_FLOOR), self._var)

        # Restart the candidate on the observation it could not explain.
        self._mean[1] = np.where(miss, obs, self._mean[1])
        self._var[1] = np.where(miss, self.VAR_INIT, self._var[1])
        self._age[1] = np.where(miss, 0.0, self._age[1])

        swap = self._age[1] > self._age[0]
        for plane in (self._mean, self._var, self._age):
            keep = plane[0].copy()
            plane[0] = np.where(swap, plane[1], plane[0])
            plane[1] = np.where(swap, keep, plane[1])

    # --- entry point --------------------------------------------------------

    def apply(self, gray: np.ndarray, M: np.ndarray) -> np.ndarray:
        """Foreground mask (uint8 0/255) for `gray`, given the camera warp `M`."""
        h, w = gray.shape
        grid = (max(1, w // self.block), max(1, h // self.block))  # cv2 order: (w, h)
        # INTER_AREA averages the block, which is the observation the model wants.
        obs = cv2.resize(gray, grid, interpolation=cv2.INTER_AREA).astype(np.float32)

        if self._mean is None or self._shape != (h, w):
            self._seed(obs, (h, w))
            return np.zeros((h, w), np.uint8)  # nothing is foreground on frame one

        self._warp(M)
        self._update(obs)

        # The query runs at full resolution: the model is coarse, the answer is not.
        mean = cv2.resize(self._mean[0], (w, h), interpolation=cv2.INTER_LINEAR)
        var = cv2.resize(self._var[0], (w, h), interpolation=cv2.INTER_LINEAR)
        age = cv2.resize(self._age[0], (w, h), interpolation=cv2.INTER_NEAREST)

        bar = self.var_threshold * np.maximum(var, self.VAR_FLOOR)
        if self.edge_tolerance:
            # Parallax slack: a planar warp cannot register a 3D scene, and the
            # residual it leaves scales with the local gradient. Squared, because
            # the test below is on squared differences.
            bar = bar + (self.edge_tolerance * edge_strength(mean)) ** 2

        fg = (gray.astype(np.float32) - mean) ** 2 > bar
        fg &= age >= self.min_age  # cells the camera only just uncovered abstain
        return (fg.astype(np.uint8)) * 255


def _demo() -> None:
    """Synthetic pan over a static world with one genuinely moving object.

    This is the whole point of the module in one check: MOG2 on these frames
    lights up everywhere, so the assert that matters is the *false positive* one.
    """
    rng = np.random.default_rng(7)
    world = cv2.GaussianBlur(rng.integers(0, 255, (400, 700), dtype=np.uint8), (5, 5), 0)
    cv2.rectangle(world, (100, 100), (300, 260), 240, 3)  # some structure to lock onto
    cv2.circle(world, (500, 300), 60, 30, -1)
    dx, dy = 3, 2  # the camera's motion per frame, in world pixels
    h, w = 200, 320

    def shot(i: int) -> tuple[np.ndarray, tuple[int, int]]:
        """Frame i of the pan, plus where the moving square sits inside it."""
        x0, y0 = 40 + dx * i, 40 + dy * i
        view = world[y0 : y0 + h, x0 : x0 + w].copy()
        # The square moves in *world* coordinates, i.e. independently of the pan.
        sx, sy = 60 + 4 * i, 120
        cv2.rectangle(view, (sx, sy - 40), (sx + 30, sy - 10), 255, -1)
        return view, (sx, sy - 40)

    # 1. The estimator must recover the pan, whichever way it looks for it.
    #    Frame 1 sampled the world dx/dy further along, so a world point moved by
    #    (-dx, -dy) *within* the frame.
    a, _ = shot(0)
    b, _ = shot(1)
    for method in ("flow", "orb", "ecc"):
        M, inliers = GlobalMotion(method=method, downscale=1).estimate(a, b)
        assert inliers > 0, f"{method} found no motion at all"
        assert abs(M[0, 2] + dx) < 1.0 and abs(M[1, 2] + dy) < 1.0, f"{method}: {M[:2, 2]}"

    # Separately: the downscale path must scale its translation back up. Only
    # checked on "flow" — ORB's keypoints get too coarse to localise on a frame
    # this small once it is halved, which is a property of the toy input, not of
    # the rescaling. On 1080p footage halving still leaves ORB plenty to work with.
    M, _ = GlobalMotion(method="flow", downscale=2).estimate(a, b)
    assert abs(M[0, 2] + dx) < 1.0 and abs(M[1, 2] + dy) < 1.0, f"downscaled: {M[:2, 2]}"

    # 2. Failure is identity and zero, never an exception.
    flat = np.zeros((h, w), np.uint8)
    M, inliers = GlobalMotion().estimate(flat, flat)
    assert inliers == 0 and np.allclose(M, np.eye(3)), "a blank pair must fail quietly"

    # 3. The model must find the square and (mostly) nothing else.
    gmc = GlobalMotion()
    sgm = CompensatedSGM(block=4, history=40, var_threshold=16, min_age=5)
    prev = None
    for i in range(40):
        frame, (sx, sy) = shot(i)
        M = IDENTITY if prev is None else gmc.estimate(prev, frame)[0]
        mask = sgm.apply(frame, M) > 0
        prev = frame

    truth = np.zeros((h, w), bool)
    truth[sy : sy + 30, sx : sx + 30] = True
    hit = (mask & truth).sum() / truth.sum()
    false = (mask & ~truth).sum() / (~truth).sum()
    assert hit > 0.5, f"only {hit:.0%} of the moving square was detected"
    assert false < 0.05, f"{false:.0%} of the static world was called foreground"

    # 4. The reason this module exists: MOG2 on the same frames charges the pan
    #    to the foreground, mislabelling an order of magnitude more of the static
    #    world. (A 3 px/frame pan is gentle — real drone footage is far worse.)
    #    If this ever stops being true, delete the module.
    mog = cv2.createBackgroundSubtractorMOG2(history=40, varThreshold=16)
    for i in range(40):
        mog_mask = mog.apply(shot(i)[0]) > 0
    mog_false = (mog_mask & ~truth).sum() / (~truth).sum()
    assert mog_false > 10 * false, f"MOG2 only mislabelled {mog_false:.0%}; is the pan real?"

    print(
        f"motion ok — square {hit:.0%} detected, background {false:.1%} false positive "
        f"(MOG2 on the same frames: {mog_false:.0%} false positive)"
    )


if __name__ == "__main__":
    _demo()
