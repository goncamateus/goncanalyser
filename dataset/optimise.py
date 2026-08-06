"""Search the settings that best reproduce a dataset's ground-truth masks.

The objective is the one asked for:

    f(θ) = α·IoU(Mθ, Mgt) + β·|Mθ ∩ Mgt| / |Mgt| − γ·|Mθ \\ Mgt| / |I \\ Mgt|

IoU alone would be enough for a benchmark. The other two terms are what make it a
*tuning* objective: β pays for coverage, so a timid threshold that finds a clean
sliver of every object cannot win; γ charges for spilled background, normalised by
how much background there is, so the price of over-segmenting does not depend on
how big the objects happen to be in this dataset.

**What is actually searched, and why it is twelve parameters and not thirty-five.**

`Mθ` is the "Contour mask" canvas, and there is exactly one route to it:

    adjust.apply() -> canvases["Threshold"] -> structure._contours() -> "Contour mask"

`features/structure.py:_contours` reads the Threshold canvas and nothing else. So
HOG, LBP, SIFT, ORB, Canny, Hough, Harris and the blob detector — everything in
the Global and Local tabs, and most of Structures — cannot move `f(θ)` by a single
pixel. They produce descriptors, keypoints and overlay `ops`. Handing them to the
optimiser would not be more thorough, it would be twenty-three dimensions of noise
charged at a second a trial.

Two values are pinned rather than searched: `contours_on`, because it is what
produces a mask at all, and `roi_on`, because a ground-truth mask covers the whole
frame and scoring a crop against one measures the crop.
"""

import json
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np
import optuna

from core.pipeline import analyse as run_chain
from core.settings import Settings
from features.adjust import BLURS, COLOR_SPACES, THRESHOLDS, to_gray
from features.structure import CONTOUR_MODES

from .coco import load, plan, read

WEIGHTS = (1.0, 0.5, 0.5)  # alpha, beta, gamma

# field -> ("int" | "float" | "cat", …bounds or choices). The vocabularies come
# from the feature modules that consume them, exactly as `ui/controls/*.py` takes
# them, so a new colour space or threshold mode reaches the optimiser for free.
#
# The floats carry a step, and it is the panel's own resolution: `Knob` fakes
# decimals on an integer Qt slider with `scale=100`, so 2.9167 is a number the
# controls cannot hold. Without the step the winner would quietly become a
# slightly different setting the moment Apply put it into a slider, and the score
# reported next to it would no longer be the score you get.
STEP = 0.01  # ui.controls.base.Knob, scale=100
SPACE: dict[str, tuple] = {
    "brightness": ("int", -100, 100),
    "contrast": ("float", 0.5, 3.0),
    "saturation": ("float", 0.0, 3.0),
    "gamma": ("float", 0.3, 3.0),
    "color_space": ("cat", tuple(COLOR_SPACES)),
    "blur_kind": ("cat", BLURS),
    "blur": ("int", 0, 31),
    "threshold_kind": ("cat", THRESHOLDS),
    "threshold": ("int", 0, 255),
    "adaptive_block": ("int", 3, 51),
    "contour_mode": ("cat", tuple(CONTOUR_MODES)),
    "contour_min_area": ("int", 0, 5000),
}

PINNED = {"contours_on": True, "roi_on": False}


def score(pred: np.ndarray, gt: np.ndarray, weights: tuple = WEIGHTS) -> float:
    """f(θ) for one frame. 1 + β is perfect; an empty prediction is 0."""
    alpha, beta, gamma = weights
    p, t = pred > 0, gt > 0
    intersection = np.count_nonzero(p & t)
    return (
        alpha * intersection / (np.count_nonzero(p | t) or 1)
        + beta * intersection / (np.count_nonzero(t) or 1)
        - gamma * np.count_nonzero(p & ~t) / (np.count_nonzero(~t) or 1)
    )


def predict(bgr: np.ndarray, s: Settings) -> np.ndarray:
    """`Mθ` — the chain's filled contour mask for these settings."""
    out = run_chain(bgr, replace(s, **PINNED))
    canvas = out.canvases.get("Contour mask")
    return np.zeros(bgr.shape[:2], np.uint8) if canvas is None else to_gray(canvas)


def evaluate(samples: list, s: Settings, weights: tuple = WEIGHTS) -> float:
    """Mean f(θ) over the held sample. Unaveraged, a big image would outvote ten."""
    try:
        return float(np.mean([score(predict(bgr, s), mask, weights) for _, bgr, mask in samples]))
    except cv2.error:
        # A parameter combination OpenCV refuses is a bad point, not a reason to
        # throw away the ninety trials already paid for. Scoring it below the
        # worst real value is also how TPE learns to stop proposing it.
        return -1.0


def decompose(samples: list, s: Settings) -> dict:
    """The three terms of f(θ) separately, plus how much frame the mask covers.

    f(θ) on its own cannot tell an accurate mask from one that swallows the
    frame. On a dataset whose objects are ~1% of the image, a mask covering ten
    times the ground truth scores within half a percent of a tight one, because
    the spill term is divided by the background and the background is nearly
    everything. These are the numbers that do separate them, and `coverage`
    against `truth` is the one to read first: ten times larger is ten times
    larger no matter what the weighted total says.
    """
    iou, recall, spill, coverage, truth = [], [], [], [], []
    for _, bgr, gt in samples:
        p, t = predict(bgr, s) > 0, gt > 0
        hit = np.count_nonzero(p & t)
        iou.append(hit / (np.count_nonzero(p | t) or 1))
        recall.append(hit / (np.count_nonzero(t) or 1))
        spill.append(np.count_nonzero(p & ~t) / (np.count_nonzero(~t) or 1))
        coverage.append(np.count_nonzero(p) / p.size)
        truth.append(np.count_nonzero(t) / t.size)
    return {
        "iou": round(float(np.mean(iou)), 4),
        "recall": round(float(np.mean(recall)), 4),
        "spill": round(float(np.mean(spill)), 4),
        "coverage": round(float(np.mean(coverage)), 4),
        "truth": round(float(np.mean(truth)), 4),
    }


def settings_of(params: dict, base: Settings | None = None) -> Settings:
    """A trial's parameters as a full `Settings`, with the pinned values applied."""
    return replace(base or Settings(), **params, **PINNED)


def _suggest(trial) -> dict:
    """One trial's parameters, snapped to the grid the panel can hold.

    Snapped through `seed_params` rather than used raw: Optuna builds a stepped
    float as `low + k * step`, which lands on 1.2000000000000002 rather than 1.2.
    That evaluates identically and *displays* identically, and then fails to equal
    itself after a round trip through a slider — the kind of difference that is
    only ever seen as "Apply did not apply".
    """
    out = {}
    for field, spec in SPACE.items():
        if spec[0] == "int":
            out[field] = trial.suggest_int(field, spec[1], spec[2])
        elif spec[0] == "float":
            out[field] = trial.suggest_float(field, spec[1], spec[2], step=STEP)
        else:
            out[field] = trial.suggest_categorical(field, list(spec[1]))
    return seed_params(out)


def seed_params(values: dict) -> dict:
    """The searchable subset of a settings dict, clamped into the search space.

    Clamped rather than trusted: the panel's sliders are wider than these bounds in
    places, and Optuna rejects an enqueued value outside the distribution it is
    asked to sample from. Floats are also snapped onto `STEP`, for the same reason
    — an enqueued value off the grid is not a point the sampler can represent.
    """
    out = {}
    for field, spec in SPACE.items():
        if field not in values:
            continue
        value = values[field]
        if spec[0] == "cat":
            if value in spec[1]:
                out[field] = value
        elif spec[0] == "int":
            out[field] = int(min(spec[2], max(spec[1], int(value))))
        else:
            snapped = spec[1] + round((float(value) - spec[1]) / STEP) * STEP
            out[field] = round(float(min(spec[2], max(spec[1], snapped))), 4)
    return out


def search(
    ann_path: str,
    images_dir: str,
    out_dir: str,
    trials: int = 100,
    n: int = 50,
    category: str = "",
    weights: tuple = WEIGHTS,
    seed: dict | None = None,
):
    """Generator yielding (done, total); returns the best settings when exhausted.

    The sample is decoded **once** and held for the whole study. Re-reading it per
    trial would cost more than the chain does, and re-*drawing* it would make the
    objective stochastic — two trials could then differ only in which images they
    happened to be scored on, which is not a comparison.
    """
    # Optuna logs a paragraph per trial at INFO. A hundred trials of it buries
    # whatever the app itself has to say.
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    coco = load(ann_path)
    cat = coco.category_id(category) if category else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    samples = [got for i in plan(coco, n, cat) if (got := read(coco, images_dir, i, cat))]
    if not samples:
        raise ValueError("no readable annotated images in that dataset")

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=0)
    )
    baseline = settings_of(seed_params(seed), Settings()) if seed else Settings()
    if seed:
        # Trial zero is the tuning already on screen, so the search starts from
        # human judgement and the result is always comparable against it.
        study.enqueue_trial(seed_params(seed))

    # ponytail: trials run one at a time. Optuna's ask/tell is what lets this be a
    # generator at all, and a progress bar the user can watch is worth more than
    # the cores; a process pool is the upgrade if a study starts taking too long.
    for done in range(1, int(trials) + 1):
        trial = study.ask()
        study.tell(trial, evaluate(samples, settings_of(_suggest(trial)), weights))
        yield done, int(trials)

    # Through the same snap the trials went through, or the winner comes back off
    # the grid — `best_params` returns what Optuna stored, not what was evaluated.
    best = settings_of(seed_params(study.best_params))
    before = evaluate(samples, replace(baseline, **PINNED), weights)
    values = asdict(best)
    (out / "best_settings.json").write_text(
        json.dumps({"source": ann_path, "frames": len(samples), "settings": values}, indent=2) + "\n"
    )
    parts = decompose(samples, best)
    return {
        "dir": str(out),
        "best": values,
        "score": round(study.best_value, 4),
        "baseline": round(before, 4),
        "images": len(samples),
        "trials": int(trials),
        "weights": list(weights),
        "parts": parts,
        # The winner covering far more frame than the ground truth means the
        # spill weight is too small to bite on objects this size, not that the
        # search failed. Said here because a single score cannot show it.
        "oversegmented": parts["coverage"] > 3 * parts["truth"],
        "changed": {k: v for k, v in values.items() if v != getattr(baseline, k)},
        "written": ["best_settings.json"],
    }


def _demo() -> None:
    """The objective's algebra, then a study that has to beat the defaults."""
    import tempfile

    from .coco import fixture

    gt = np.zeros((40, 60), np.uint8)
    gt[10:30, 15:45] = 255

    # Three points where f(θ) is known exactly. A sign slip in any term survives a
    # score that still trends upward, so pin the corners rather than the trend.
    assert score(gt, gt) == 1.5, score(gt, gt)  # IoU 1, recall 1, no spill
    assert score(np.zeros_like(gt), gt) == 0.0  # nothing found, nothing spilled
    everything = score(np.full_like(gt, 255), gt)
    assert everything < score(gt, gt), everything
    # Predicting the whole frame: IoU is the mask's share, recall is 1, and the
    # background penalty is the full gamma. Any other value means a wrong divisor.
    assert abs(everything - (np.count_nonzero(gt) / gt.size + 0.5 - 0.5)) < 1e-9, everything

    # Half the object found and nothing spilled: recall halves, IoU halves, and
    # the penalty stays zero. This is the term β exists to reward.
    half = np.zeros_like(gt)
    half[10:20, 15:45] = 255
    assert abs(score(half, gt) - (0.5 + 0.5 * 0.5)) < 1e-9, score(half, gt)
    # …and γ is what stops "predict more" from always paying.
    assert score(half, gt) > score(np.full_like(gt, 255), gt)

    # The weights do what they are named. Zeroing a term removes exactly it.
    assert score(half, gt, (1.0, 0.0, 0.0)) == 0.5
    assert score(np.full_like(gt, 255), gt, (0.0, 0.0, 1.0)) == -1.0

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ann_path, images_dir = fixture(root, count=3)
        dest = root / "out"

        steps = search(ann_path, images_dir, str(dest), trials=25, n=3, category="square")
        seen, result = [], None
        while result is None:
            try:
                seen.append(next(steps))
            except StopIteration as finished:
                result = finished.value
        assert seen[0] == (1, 25) and seen[-1] == (25, 25), (seen[0], seen[-1])

        # The fixture is bright squares on dark noise, so a threshold exists that
        # nearly nails it. A study that cannot beat the defaults is not searching.
        assert result["score"] > result["baseline"], result
        assert result["score"] > 1.0, f"25 trials found only {result['score']}"
        assert result["images"] == 3 and result["trials"] == 25

        # The winner is reproducible: the reported score is what these settings do.
        coco = load(ann_path)
        cat = coco.category_id("square")
        samples = [got for i in plan(coco, 3, cat) if (got := read(coco, images_dir, i, cat))]
        again = evaluate(samples, Settings(**result["best"]))
        assert abs(again - result["score"]) < 1e-9, (again, result["score"])

        # It lands on disk in the shape `MainWindow.load_settings` already reads,
        # so Ctrl+L on this file restores the tuning.
        saved = json.loads((dest / "best_settings.json").read_text())
        assert saved["settings"] == result["best"]
        assert Settings(**saved["settings"]).contours_on, "the mask maker was not saved on"
        assert not Settings(**saved["settings"]).roi_on, "a region would score a crop"

        # Every winning value has to survive the panel. `Knob` rounds to STEP, so a
        # float off that grid would silently become a different setting the moment
        # Apply put it in a slider — and the score printed beside it would be a
        # score for settings the user does not have.
        for field, spec in SPACE.items():
            value = result["best"][field]
            if spec[0] == "float":
                assert abs(round(value / STEP) * STEP - value) < 1e-9, (field, value)
            assert seed_params(result["best"])[field] == value, f"{field} does not round-trip"

    # Seeding: an out-of-range value from the panel is clamped, not rejected, and
    # a field outside the twelve is dropped rather than smuggled into the search.
    clamped = seed_params({"brightness": 5000, "blur": -3, "detector": "SIFT", "gamma": 1.25})
    assert clamped == {"brightness": 100, "blur": 0, "gamma": 1.25}, clamped
    assert seed_params({"color_space": "CMYK"}) == {}, "an unknown choice must not be enqueued"
    # A value between two slider stops is snapped to one, not left where it is.
    assert seed_params({"gamma": 1.2567})["gamma"] == 1.26, seed_params({"gamma": 1.2567})
    assert set(SPACE) <= {f for f in asdict(Settings())}, "SPACE names a field Settings lacks"
    assert not set(SPACE) & set(PINNED), "a pinned value must not also be searched"

    print("optimise ok")


if __name__ == "__main__":
    _demo()
