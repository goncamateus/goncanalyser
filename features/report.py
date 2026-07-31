"""Export what the chain measured: JSON summary, CSV tables, processed overlays.

Written as a generator so the caller can drive a progress bar — a report re-runs
the whole chain over the whole source, which with HOG on is a quarter-second a
frame.

**Rows are streamed, not accumulated.** A 900-frame clip with SIFT on produces
close to half a million keypoint rows, and holding those in a list before
writing would cost more memory than the video. So each table's file is opened
the first time a row of that kind appears and written per frame; only the
per-frame metrics, which are a handful of numbers, are kept to build the JSON.
"""

import csv
import json
from dataclasses import asdict
from pathlib import Path

import cv2

from core.pipeline import analyse, composite
from core.settings import Settings
from core.source import FrameSource

FORMATS = ("json", "csv", "overlays")


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


def write(path: str, s: Settings, out_dir: str, formats: tuple[str, ...]):
    """Generator yielding (done, total); returns a summary dict when exhausted."""
    source = FrameSource(path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    overlay_dir = out / "overlays"
    if "overlays" in formats:
        overlay_dir.mkdir(exist_ok=True)

    total = source.count
    tables = _Tables(out)
    summary: list[dict] = []
    written = []

    try:
        for index in range(total):
            raw = source.read(index)
            if raw is None:
                break  # a truncated file is a normal thing to hand this
            result = analyse(raw, s)
            summary.append({"frame": index, "name": source.name(index), **result.metrics})

            if "csv" in formats:
                for kind, rows in result.rows.items():
                    tables.add(kind, rows, index)
            if "overlays" in formats:
                cv2.imwrite(str(overlay_dir / f"frame_{index:06d}.png"), composite(result, s))

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

    if "json" in formats:
        # The settings go in the file: a metrics table without the parameters
        # that produced it is not reproducible, and these are the parameters.
        (out / "report.json").write_text(
            json.dumps(
                {"source": str(path), "frames": len(summary), "settings": asdict(s),
                 "metrics": summary},
                indent=2,
            )
            + "\n"
        )
        written.append("report.json")

    if "overlays" in formats:
        written.append(f"overlays/ ({len(summary)} png)")

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
        assert summary["frames"] == 3 and "report.json" in summary["written"], summary

        report = json.loads((dest / "report.json").read_text())
        assert report["frames"] == 3, report
        assert report["settings"]["detector"] == "ORB"
        assert len(report["metrics"]) == 3 and "contours" in report["metrics"][0]

        rows = list(csv.DictReader((dest / "metrics.csv").open()))
        assert len(rows) == 3 and rows[0]["frame"] == "0"

        # Per-object tables carry the frame they came from, or they cannot be
        # joined back to anything.
        keypoints = list(csv.DictReader((dest / "keypoints.csv").open()))
        assert keypoints and set(keypoints[0]) >= {"frame", "x", "y", "response"}
        assert {r["frame"] for r in keypoints} == {"0", "1", "2"}

        overlays = sorted((dest / "overlays").glob("*.png"))
        assert len(overlays) == 3, overlays
        assert cv2.imread(str(overlays[0])).shape == (64, 64, 3)

        # Asking for one format must not write the others.
        only = Path(tmp) / "json-only"
        list(write(str(root), s, str(only), ("json",)))
        assert (only / "report.json").exists()
        assert not (only / "metrics.csv").exists() and not (only / "overlays").exists()

    print("report ok")


if __name__ == "__main__":
    _demo()
