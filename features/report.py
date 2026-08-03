"""Export what the chain measured: CSV tables, processed overlays, the settings.

Written as a generator so the caller can drive a progress bar — a report re-runs
the whole chain over the whole source, which with HOG on is a quarter-second a
frame.

**Rows are streamed, not accumulated.** A 900-frame clip with SIFT on produces
close to half a million keypoint rows, and holding those in a list before
writing would cost more memory than the video. So each table's file is opened
the first time a row of that kind appears and written per frame; the per-frame
metrics, which are a handful of numbers each, are the one exception — they are
kept so `metrics.csv` can be written with a header taken from the first row.

`settings.json` holds no measurements at all. The numbers are the CSVs' job, and
duplicating them as JSON meant a 900-frame export carried the same table twice —
half a megabyte of it — in two formats that could disagree.
"""

import csv
import json
from dataclasses import asdict
from pathlib import Path

import cv2

from core.pipeline import analyse, composite
from core.settings import Settings
from core.source import FrameSource

from .motion import MotionState

FORMATS = ("settings", "csv", "overlays", "objects")


class _Tables:
    """One CSV per row kind, opened on first sight and closed together.

    The header comes from the first row, which is safe here because the settings
    are fixed for the whole run — every contour row has the same keys as every
    other contour row.
    """

    def __init__(self, out: Path):
        self.out = out
        self.open: dict[str, tuple] = {}

    def add(self, kind: str, rows: list[dict], frame: int) -> None:
        if not rows:
            return
        if kind not in self.open:
            handle = (self.out / f"{kind}.csv").open("w", newline="")
            writer = csv.DictWriter(handle, ["frame", *rows[0]])
            writer.writeheader()
            self.open[kind] = (handle, writer)
        _, writer = self.open[kind]
        writer.writerows({"frame": frame, **row} for row in rows)

    def close(self) -> list[str]:
        for handle, _ in self.open.values():
            handle.close()
        return sorted(f"{k}.csv" for k in self.open)


def _crops(raw, rows, out: Path, index: int) -> int:
    """Every moving object in this frame, cut out of the source. Returns how many.

    Cut from the *raw* frame rather than the composite, so what lands on disk is
    the object as the camera saw it and not a picture of a box drawn round it.
    The rows are already in full-frame coordinates by the time they get here —
    `pipeline.analyse` translates them out of region space — so they index the
    frame directly.
    """
    height, width = raw.shape[:2]
    written = 0
    for n, row in enumerate(rows):
        x, y = max(0, int(row["x"])), max(0, int(row["y"]))
        x2, y2 = min(width, x + int(row["w"])), min(height, y + int(row["h"]))
        if x2 <= x or y2 <= y:
            continue  # a box entirely off-frame is nothing to write
        cv2.imwrite(str(out / f"frame_{index:06d}_{n:02d}.png"), raw[y:y2, x:x2])
        written += 1
    return written


def write(path: str, s: Settings, out_dir: str, formats: tuple[str, ...]):
    """Generator yielding (done, total); returns a summary dict when exhausted."""
    source = FrameSource(path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    overlay_dir = out / "overlays"
    if "overlays" in formats:
        overlay_dir.mkdir(exist_ok=True)
    object_dir = out / "objects"
    if "objects" in formats:
        object_dir.mkdir(exist_ok=True)

    total = source.count
    tables = _Tables(out)
    summary: list[dict] = []
    written = []
    crops = 0

    # Up front, because it does not depend on a single frame: a metrics table
    # without the parameters that produced it is not reproducible, and these are
    # the parameters. Same shape the app's own settings cache has, so the window
    # loads it back through the same path.
    if "settings" in formats:
        (out / "settings.json").write_text(
            json.dumps(
                {"source": str(path), "frames": total, "settings": asdict(s)}, indent=2
            )
            + "\n"
        )
        written.append("settings.json")

    # Nothing else ticked means nothing to measure — re-analysing the whole
    # source to write a file that is already on disk would be pure waste.
    measured = tuple(f for f in formats if f != "settings")
    # This run's own motion state. The loop below is strictly sequential, frame 0
    # upwards, which is exactly what it wants — and it is a separate object from
    # the viewer's, so exporting while the window plays disturbs neither.
    state = MotionState()

    try:
        for index in range(total if measured else 0):
            raw = source.read(index)
            if raw is None:
                break  # a truncated file is a normal thing to hand this
            result = analyse(raw, s, state.at(index))
            summary.append({"frame": index, "name": source.name(index), **result.metrics})

            if "csv" in formats:
                for kind, rows in result.rows.items():
                    tables.add(kind, rows, index)
            if "overlays" in formats:
                cv2.imwrite(str(overlay_dir / f"frame_{index:06d}.png"), composite(result, s))
            if "objects" in formats:
                crops += _crops(raw, result.rows.get("motion", ()), object_dir, index)

            yield index + 1, total
    finally:
        written += tables.close()
        source.release()

    if "csv" in formats and summary:
        with (out / "metrics.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, list(summary[0]), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(summary)
        written.append("metrics.csv")

    if "overlays" in formats:
        written.append(f"overlays/ ({len(summary)} png)")
    if "objects" in formats:
        written.append(f"objects/ ({crops} png)")

    return {"frames": len(summary), "dir": str(out), "written": written}


def _demo() -> None:
    """A three-image folder round-trips through every format."""
    import tempfile

    import numpy as np

    rng = np.random.default_rng(0)
    with tempfile.TemporaryDirectory() as tmp:
        root, dest = Path(tmp) / "in", Path(tmp) / "out"
        root.mkdir()
        for i in range(3):
            img = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
            cv2.rectangle(img, (10, 10), (40, 40), (255, 255, 255), -1)
            cv2.imwrite(str(root / f"{i}.png"), img)

        s = Settings(threshold_kind="Otsu", contours_on=True, detector="ORB", view="Edges")

        # Driven exactly the way ReportThread drives it: the progress ticks come
        # out of next(), and the summary only exists on StopIteration.
        steps = write(str(root), s, str(dest), FORMATS)
        seen, summary = [], None
        while summary is None:
            try:
                seen.append(next(steps))
            except StopIteration as finished:
                summary = finished.value
        assert seen == [(1, 3), (2, 3), (3, 3)], seen
        assert summary["frames"] == 3 and "settings.json" in summary["written"], summary

        # The settings file carries the parameters and nothing else — the
        # measurements are the CSVs' job and are not duplicated here.
        saved = json.loads((dest / "settings.json").read_text())
        assert saved["frames"] == 3 and saved["source"] == str(root), saved
        assert saved["settings"] == asdict(s), saved["settings"]
        assert "metrics" not in saved, saved

        rows = list(csv.DictReader((dest / "metrics.csv").open()))
        assert len(rows) == 3 and rows[0]["frame"] == "0"
        assert "contours" in rows[0], rows[0]

        # Per-object tables carry the frame they came from, or they cannot be
        # joined back to anything.
        keypoints = list(csv.DictReader((dest / "keypoints.csv").open()))
        assert keypoints and set(keypoints[0]) >= {"frame", "x", "y", "response"}
        assert {r["frame"] for r in keypoints} == {"0", "1", "2"}

        overlays = sorted((dest / "overlays").glob("*.png"))
        assert len(overlays) == 3, overlays
        assert cv2.imread(str(overlays[0])).shape == (64, 64, 3)

        # Motion spans frames, so the exporter has to carry a state of its own
        # down the loop — without it every frame is frame one and nothing moves.
        # Its own fixture: a square that actually travels, on a clean background,
        # so the rows are the object and not a threshold's worth of speckle.
        clip = Path(tmp) / "clip"
        clip.mkdir()
        for i in range(3):
            img = np.zeros((64, 64, 3), np.uint8)
            cv2.rectangle(img, (5 + i * 10, 20), (25 + i * 10, 40), (255, 255, 255), -1)
            cv2.imwrite(str(clip / f"{i}.png"), img)

        moving = Path(tmp) / "moving"
        list(write(str(clip), Settings(motion_algo="Frame difference"), str(moving),
                   ("csv", "objects")))
        rows = list(csv.DictReader((moving / "motion.csv").open()))
        assert rows and set(rows[0]) >= {"frame", "x", "y", "w", "h", "area", "speed"}
        # Frame 0 has nothing to difference against; the ones after it do.
        assert {r["frame"] for r in rows} <= {"1", "2"} and rows[0]["frame"] != "0"
        assert list((moving / "objects").glob("*.png")), "no object crops written"

        # Asking for one format must not write the others. Settings on its own
        # also reads no frames at all — no progress ticks come out of it.
        only = Path(tmp) / "settings-only"
        steps = write(str(root), s, str(only), ("settings",))
        assert list(steps) == [], "settings-only re-analysed the source"
        assert (only / "settings.json").exists()
        assert not (only / "metrics.csv").exists() and not (only / "overlays").exists()
        # …and it still knows how long the source is, without having read it.
        assert json.loads((only / "settings.json").read_text())["frames"] == 3

    print("report ok")


if __name__ == "__main__":
    _demo()
