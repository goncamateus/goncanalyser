"""One module per analysis family. No Qt anywhere in here.

Every module exposes the same entry point:

    run(frame: np.ndarray, s: Settings, out: pipeline.Result, state=None) -> None

and writes what it produced into the three collectors on `out` — a whole-frame
`canvas`, an overlay `op`, `metrics`, `rows`, or any mix. `adjust` is the one
exception: it takes no state and also returns the frame every other module reads.

`state` is a `motion.MotionState`, and `motion` is the only module that looks at
it — the rest accept and ignore it so `pipeline.analyse` can call all of them
through one loop instead of special-casing the one feature that spans frames.

Deliberately not importing the submodules here. `core.pipeline` imports them by
name, and leaving this file empty keeps `python -m features.color` from dragging
in scikit-image and every OpenCV detector to draw one histogram.
"""
