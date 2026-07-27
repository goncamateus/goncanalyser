# steam-detector

Exploratory OpenCV analysis of two drone thermal videos (`voo_1.mp4`, `voo_2.mp4`):
find the steam plume — the saturated hot core **and** the cooler halo around it that
still belongs to the plume — and draw its outline on the frame.

```bash
uv sync
uv run steam-detect voo_1.mp4 --out out/voo_1 --stride 30 --max-frames 20
open out/voo_1
```

Output per frame: the annotated frame `frame_000120.png`, plus one crop per detected
source, `frame_000120_src0.png`. Contours are **green** = the whole plume, halo
included; **cyan** = the saturated core inside it (cyan because white would disappear
against the clipped-white plume it sits on); **red** = the ROI the source was allowed
to claim.

## Tuning them: `steam-tune`

```bash
uv run steam-tune voo_1.mp4              # sliders + playback, contours redraw live
uv run steam-tune voo_2.mp4 --scale 0.5  # 1080p is slower; work at half size
```

One OpenCV window, a slider per knob, the video playing under the contours.

| key | |
|---|---|
| `space` | play / pause |
| `.` `,` | step one sampled frame forward / back |
| `1` `2` `3` `4` | view: contours on the frame · temperature (L) · motion map · lava blobs and candidate source boxes |
| `s` | write `tune.json` **and** print the equivalent `steam-detect` command |
| `w` | write the current view as `tuned_<frame>.png` |
| `q` / `esc` | quit |

Then feed the result straight back in — flags typed on the command line still win
over the file:

```bash
uv run steam-detect voo_1.mp4 --out out/voo_1 --config tune.json
```

Dragging a slider is instant (17 ms on voo_1, 67 ms on voo_2) because no knob feeds
the expensive half of the pipeline — frame decoding, ORB alignment, the temporal
median are cached per frame, and only `plume_mask` re-runs. Changing frames is the
slow part (~60 ms per step once the cache is warm), so playback runs at the speed
the pipeline allows, not at 30 fps. Views `2` and `3` are worth the keystroke: the
motion map shows *why* a `p_mot` or `grad_w` change did what it did.

Note `--scale`: percentile knobs are resolution-independent, the **area** knobs are
not — they count pixels of the working image, so `--scale 0.5` quarters every blob.
At the defaults that means every source falls under `src_min_area` and the app finds
nothing; divide `min_area` and `src_min_area` by 4 when you halve the scale. The app
prints the factor at startup.

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

Sources first, then one segmentation per source:

```
frame → crop pillarbox → L = temperature index
      → align ±window neighbours onto it, median = plume-free background
      → motion = |L - background|
      → moving = motion > percentile(motion, p_mot) + grad_w · edge(background)

  sources: (local stddev ≥ sd_min) & (L > p_src), closed → one box per hot source
  per source:
      → ROI: everything above the source base, x-cropped to the motion beside it
      → seed  = (L > p_hi) & moving         hottest and churning, inside the ROI
      → cand  = (L > p_lo) & moving         warm and churning, inside the ROI
      → plume = components of cand touching a seed      (hysteresis = the halo)
      → grow geodesically through hot, then warm, pixels  (the anchored jet)
      → empty mask ⇒ the source vents nothing ⇒ dropped
      → overlapping masks ⇒ the bigger claim wins
```

Three things make the source step work:

- **The "lava" texture is a real signature.** Above the top of the palette the camera
  dithers, so off-scale heat comes out speckled rather than flat. High local standard
  deviation *and* a top-percentile temperature finds exactly those pixels; smooth hot
  metal fails the first test.
- **`src_close_k` is delicate.** It glues the speckle into blobs, but one size too
  wide bridges the plume and the equipment next to it into one useless box — measured
  on voo_1: `7` separates them, `15` merges them.
- **The texture alone does not tell plume from equipment** — a dithered heat exchanger
  looks identical. What rejects it is the ROI: nothing churning above its base means
  no mask, and no mask means no source. That falls out of the segmentation, with no
  extra rule.

Contours are drawn per source, each labelled `#0`, `#1`, … with its ROI boxed.

Two more steps exist because of things the videos actually do:

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

Source knobs live in `Config` and on the tuner's sliders (`--config` carries them to
the CLI): `p_src` 99.0, `sd_min` 20, `src_close_k` 7, `src_min_area` 120,
`roi_margin` 20.

Observed on these clips: `voo_1` wants `--p-mot 93` to keep the whole anchored column,
and yields exactly one source — the equipment on the right is detected as a source and
then dropped for venting nothing. `voo_2` (1080p, faster flight, hot plant everywhere)
registers worse — median residual 7 vs the plume's ~34 — and at the default keeps a
flickering heat exchanger as a second source. It is genuinely hot and genuinely
churning, so nothing here is wrong; `--p-mot 98.5` drops it. Sources are numbered, so
a spurious one is now a labelled extra rather than contamination of the plume's mask.

## Check

```bash
uv run pytest -q
```

Three synthetic checks, no GUI: the plume's warm ring comes along while static hot
equipment stays out; two dithered sources are both found but only the venting one
survives, with its mask never reaching below its own base; and a saved `tune.json`
round-trips with typed flags still winning over the file.

## Not done

- Absolute temperature — needs the radiometric source, not the mp4.
- COCO/RLE export for `steam-maker`.
- Overlay video and per-frame metrics CSV.
