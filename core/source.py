"""One interface over the three things you can load: a video, a folder, an image.

A single image is a folder of one, and a folder is a video you cannot scrub
smoothly — so this is one class with two backends rather than three classes. The
window, the worker and the report exporter all just ask for frame *n*.

The sequential fast path matters and is the reason `read` tracks its own
position: `CAP_PROP_POS_FRAMES` forces a keyframe hunt and re-decode, so setting
it once per frame during playback is many times slower than reading ahead.
"""

from pathlib import Path

import cv2
import numpy as np

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".ppm", ".pgm"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".mpg", ".mpeg"}

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)"
VIDEO_FILTER = "Video (*.mp4 *.mov *.avi *.mkv *.m4v *.webm);;All files (*)"
ANY_FILTER = (
    "Image or video ("
    + " ".join(f"*{e}" for e in sorted(IMAGE_EXT | VIDEO_EXT))
    + ");;All files (*)"
)


class SourceError(Exception):
    """The path is not something we can read frames out of."""


class FrameSource:
    """Frames by index, from a video file or a list of images."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.frames: list[Path] = []
        self.capture: cv2.VideoCapture | None = None
        self._next = 0  # the frame index the capture is positioned at

        if self.path.is_dir():
            self.frames = sorted(
                p for p in self.path.iterdir() if p.suffix.lower() in IMAGE_EXT
            )
            if not self.frames:
                raise SourceError(f"no images in {self.path}")
        elif self.path.suffix.lower() in IMAGE_EXT:
            self.frames = [self.path]
        else:
            self.capture = cv2.VideoCapture(str(self.path))
            if not self.capture.isOpened():
                raise SourceError(f"cannot open {self.path}")

    @property
    def is_video(self) -> bool:
        return self.capture is not None

    @property
    def count(self) -> int:
        if self.capture is None:
            return len(self.frames)
        # Some containers report 0 or a wild number. Treat anything non-positive
        # as unknown and let the read loop discover the end by failing.
        return max(0, int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)))

    @property
    def fps(self) -> float:
        """0 for stills, which is how the worker knows not to advance on its own."""
        if self.capture is None:
            return 0.0
        fps = self.capture.get(cv2.CAP_PROP_FPS)
        return fps if fps and fps > 1 else 0.0

    @property
    def size(self) -> tuple[int, int]:
        """(width, height) in pixels, or (0, 0) if that cannot be established.

        Asked for directly rather than inferred from a painted frame, because the
        Histogram view paints a 512x256 plot instead of the frame and would give
        the wrong answer. Video reports its own dimensions without decoding
        anything; a folder has to read its first image.
        """
        if self.capture is not None:
            w = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return (max(0, w), max(0, h))
        first = self.read(0)
        return (0, 0) if first is None else (first.shape[1], first.shape[0])

    def name(self, index: int) -> str:
        """A label for this frame — the file name for stills, the number for video."""
        if self.capture is None:
            return self.frames[index].name if 0 <= index < len(self.frames) else str(index)
        return f"{self.path.name}:{index}"

    def read(self, index: int) -> np.ndarray | None:
        """Frame `index` as BGR, or None past the end."""
        if self.capture is None:
            if not 0 <= index < len(self.frames):
                return None
            # imread returns None on an unreadable or non-image file rather than
            # raising, so a stray .png that is really a text file just gets skipped.
            return cv2.imread(str(self.frames[index]), cv2.IMREAD_COLOR)

        if index != self._next:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, index))
        ok, frame = self.capture.read()
        if not ok:
            return None
        self._next = index + 1
        return frame

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None


def _demo() -> None:
    """Video, folder and single image must all answer the same three questions."""
    import tempfile

    rng = np.random.default_rng(0)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        images = [rng.integers(0, 255, (32, 48, 3), dtype=np.uint8) for _ in range(5)]
        for i, img in enumerate(images):
            cv2.imwrite(str(root / f"f{i:02d}.png"), img)

        folder = FrameSource(str(root))
        assert folder.count == 5 and not folder.is_video and folder.fps == 0.0
        assert folder.size == (48, 32), folder.size
        assert folder.read(0).shape == (32, 48, 3)
        assert folder.read(4) is not None and folder.read(5) is None
        assert folder.name(0) == "f00.png"
        # Random access must not depend on what was read before it.
        assert (folder.read(2) == folder.read(2)).all()

        single = FrameSource(str(root / "f01.png"))
        assert single.count == 1 and single.read(0) is not None and single.read(1) is None

        video_path = root / "clip.mp4"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (48, 32)
        )
        for img in images:
            writer.write(img)
        writer.release()

        clip = FrameSource(str(video_path))
        assert clip.is_video and clip.fps == 10.0, clip.fps
        assert clip.count == 5, clip.count
        # Reported by the container, so asking must not disturb the read position.
        assert clip.size == (48, 32), clip.size
        assert clip.read(0).shape == (32, 48, 3)
        # Sequential reads take the fast path; the seek back must still work.
        assert clip.read(1) is not None and clip.read(2) is not None
        assert clip.read(0) is not None, "seeking backwards failed"
        clip.release()

        for bad in (root / "nope.mp4", root / "empty"):
            (root / "empty").mkdir(exist_ok=True)
            try:
                FrameSource(str(bad))
            except SourceError:
                continue
            raise AssertionError(f"{bad} should have raised")

    print("source ok")


if __name__ == "__main__":
    _demo()
