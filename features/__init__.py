"""One module per analysis family. No Qt anywhere in here.

Every module exposes the same entry point:

    run(frame: np.ndarray, s: Settings, out: pipeline.Result) -> None

and writes what it produced into the three collectors on `out` — a whole-frame
`canvas`, an overlay `op`, `metrics`, `rows`, or any mix. `adjust` is the one
exception: it also returns the frame every other module reads.

Deliberately not importing the submodules here. `core.pipeline` imports them by
name, and leaving this file empty keeps `python -m features.color` from dragging
in scikit-image and every OpenCV detector to draw one histogram.
"""
