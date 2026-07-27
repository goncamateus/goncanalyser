# steam-detector

Exploratory OpenCV analysis of two drone thermal videos (`voo_1.mp4`, `voo_2.mp4`):
find the steam plume — the saturated hot core **and** the cooler halo around it that
still belongs to the plume — and draw its outline on the frame.

```bash
uv sync
uv run steam-detect voo_1.mp4 --out out/voo_1 --stride 30 --max-frames 20
open out/voo_1
```

Output is the original frame with two contours drawn on it: **green** = the whole
plume, halo included; **cyan** = the saturated core inside it. Cyan because white
would disappear against the clipped-white plume it sits on.

## What the data is

|  | voo_1 | voo_2 |
|---|---|---|
| resolution | 640×512 | 1920×1080, pillarboxed to 1352×1080 |
| length | 261 s / 7835 frames | 88 s / 2630 frames |

Both are **palette-mapped, not radiometric** — the camera baked a colormap
(black → purple → red → orange → yellow → white) into the pixels. Four facts follow,
and they drive every design choice in `steamdet/plume.py`:

1. **Temperature is HLS lightness.** Along that palette, `L` rises monotonically, so
   `cv2.cvtColor(frame, COLOR_BGR2HLS)[:,:,1]` is a temperature proxy (checked against
   a full inverse-LUT reconstruction on these clips: r = 0.96, for a fraction of the
   code). It is an *index*, not °C — °C would need the original FLIR radiometric file.
2. **The camera runs AGC**, rescaling the palette every frame. The same L is not the
   same temperature in the next frame, so every threshold here is a **percentile of
   the current frame**, never a fixed value.
3. **Hot equipment looks exactly like plume.** Pipes, heaters and car roofs saturate
   the palette too. What separates them is that the plume churns — so a pixel must be
   bright *and* changing to seed a plume.
4. **The drone moves**, so "changing" is only meaningful after aligning neighbour
   frames onto the current one (ORB + partial affine).

## Pipeline

```
frame → crop pillarbox → L = temperature index
      → align ±window neighbours onto it, median = plume-free background
      → motion = |L - background|
      → moving  = motion > percentile(motion, p_mot) + grad_w · edge(background)
      → seed    = (L > p_hi) & moving          hottest and churning
      → cand    = (L > p_lo) & moving          warm and churning
      → plume   = components of cand touching a seed        (hysteresis = the halo)
      → grow geodesically through hot, then warm, pixels    (the anchored jet)
      → contours of plume and of core, drawn on the frame
```

Two of those steps exist because of things the videos actually do:

- **`grad_w · edge(background)`** — a flat affine warp cannot register a 3D scene from
  a translating drone, so every sharp static edge leaves a residual proportional to
  its gradient and reads as fake motion. Charging each pixel `grad_w` pixels' worth of
  its gradient removes the parked cars and the equipment rims. The gradient is measured
  on the background median, not on the frame: the plume's own speckle is a strong
  gradient too, and charging that erases the plume.
- **geodesic growth** — the jet is anchored at the nozzle and clipped white, so its
  lower column has *zero* temporal residual no matter how hard it churns. Growth pulls
  the mask back down along the connected hot column, in bounded steps so a leak into
  the plant can only travel so far.

## Knobs

All are CLI flags; defaults live in `Config` (`steamdet/plume.py`). These are
calibration knobs — the plant, the flight and the AGC differ per clip, so expect to
turn them.

| flag | default | turn it when |
|---|---|---|
| `--p-hi` | 99.0 | core too small / too greedy |
| `--p-lo` | 90.0 | halo cut off early (lower) or bleeding into warm ground (raise) |
| `--p-mot` | 95.0 | plant leaking into the mask (raise) / plume fragmenting (lower) |
| `--tau` | 6 | floor for the motion bar; keeps a static scene empty |
| `--grad-w` | 1.5 | static edges still firing (raise) |
| `--window` | 2 | neighbours per side used for the median |
| `--stride` | 10 | every Nth frame; also sets how far apart the neighbours are |
| `--min-area` | 200 | speckle surviving as tiny components |

Observed on these clips: `voo_1` wants `--p-mot 93` to keep the whole anchored column.
`voo_2` (1080p, faster flight, hot plant everywhere) registers worse — median residual
7 vs the plume's ~34 — and wants `--p-mot 98.5` to keep the plant out. The 95 default
sits between them; that spread is the knob earning its place.

## Check

```bash
uv run pytest -q
```

One synthetic scene: a static hot blob (equipment) and a moving hot blob with a warm
ring (plume). The mask must contain the moving blob *and* its ring, and must not
contain the static one.

## Not done

- Absolute temperature — needs the radiometric source, not the mp4.
- COCO/RLE export for `steam-maker`.
- Overlay video and per-frame metrics CSV.
