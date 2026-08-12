# Features

Every feature, every parameter, and what moving each one from its minimum to its maximum
actually does.

Each section gives you a description, the workflow, a parameter table with the exact range
and default the control enforces, an effect analysis, and a figure generated from the real
application.

!!! note "Reading the parameter tables"

    **Field** is the name in `settings.json`, so you can edit an exported file or a
    hand-written one and load it back with ++ctrl+l++. **Range** is what the slider or
    spinbox allows — values outside it cannot be entered, and several are additionally
    clamped in the feature itself (odd kernels, mostly).

---

## Image Adjustment

**Tab:** Adjust · **Menu:** `Image Adjustment`

![The Image Adjustment tab](../assets/images/tab_adjust.png){ width="400" }

### What it does

Everything on this tab runs **before** every other feature, colour space included. Edges,
keypoints, texture and motion all measure the frame this tab produces, so switching to LAB
genuinely changes what SIFT sees. Preprocessing here is not cosmetic and not a preview — it
is part of the measurement.

The order inside the tab is the order of operations: tone, then colour space, then
smoothing, then threshold. A region, if one is active, is cropped before all of it.

### Tone

Four multiplicative and additive corrections, applied first.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Brightness | `brightness` | int | −100 … 100 | `0` | Additive offset on every channel |
| Contrast | `contrast` | float | 0.1 … 3.0 | `1.0` | Multiplicative gain. `1.0` is identity |
| Saturation | `saturation` | float | 0.0 … 3.0 | `1.0` | HSV S-channel gain. `1.0` is identity |
| Gamma | `gamma` | float | 0.1 … 3.0 | `1.0` | `<1` darkens, `>1` lifts shadows |

#### Effect analysis

**Brightness −100 → +100.** At −100 everything below mid-grey clips to black and detail in
the shadows is gone for good — every downstream feature sees the clipped frame, not the
original. At +100 the highlights saturate instead, which is the more damaging direction for
keypoint detectors: a flat white region has no gradient, so SIFT and Canny find nothing
there.

![Brightness from −100 to +100](../assets/images/adjust_brightness.jpg)

**Contrast 0.1 → 3.0.** At 0.1 the frame collapses towards black and the histogram becomes a
spike — Otsu, which picks its level from that histogram, then has almost nothing to separate.
At 3.0 the mid-tones stretch out to both ends, which makes a threshold much easier to place
and simultaneously destroys the extremes. The useful range for most tuning is 0.7–1.6.

![Contrast from 0.1 to 3.0](../assets/images/adjust_contrast.jpg)

**Saturation 0.0 → 3.0.** At `0.0` the frame is grey — not converted to grayscale, but with
its colour removed, which is different from picking `Grayscale` below because the array stays
three-channel. Above `1.0` colour separation grows, which helps if you are about to threshold
on a colour channel and does nothing at all for the grayscale-only features.

![Saturation from 0.0 to 3.0](../assets/images/adjust_saturation.jpg)

**Gamma 0.1 → 3.0.** The non-linear one. Below `1.0` it compresses shadows and expands
highlights; above `1.0` it does the reverse, which is the setting to reach for when the thing
you want is dark and the background is not. Unlike contrast it does not clip — the curve is
monotonic across the whole range — so it is the safer of the two when detail matters.

![Gamma from 0.1 to 3.0](../assets/images/adjust_gamma.jpg)

### Colour space

| Name | Field | Type | Values | Default |
|---|---|---|---|---|
| Colour space | `color_space` | choice | `BGR`, `Grayscale`, `HSV`, `LAB`, `HLS` | `BGR` |

Converted **before** everything downstream. HSV, HLS and LAB are drawn as raw channels — that
is, as false colour — because there is no meaningful way to display them otherwise, and
because what matters is what the *features* read, not what it looks like.

#### Effect analysis

`Grayscale` is the cheapest and removes any chance of a colour artefact driving a detector.
`HSV` puts hue in channel 0, which makes a hue threshold trivial and makes any grayscale
conversion downstream meaningless — `to_gray` of an HSV image is not a luminance. `LAB`
separates lightness from colour more faithfully than HSV, at slightly more cost. Nothing here
is wrong; it changes what "brightness" means to every operator after it.

![The five colour spaces](../assets/images/adjust_colorspace.jpg)

### Smoothing

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Kind | `blur_kind` | choice | `None`, `Gaussian`, `Median` | `None` | Which filter |
| Kernel | `blur` | int | 0 … 31 | `0` | `0` or `1` disables it; even values round up to odd |

#### Effect analysis

**Kernel 0 → 31.** At 0 or 1 the filter is off. Small kernels (3–7) remove sensor noise and
leave structure; large ones (15+) remove structure too, which is occasionally what you want —
a heavily blurred frame thresholds into a few large regions instead of hundreds of speckles.
Every increase costs edge sharpness, and Canny's response falls with it.

**Median beats Gaussian on salt-and-pepper noise** and keeps edges sharper at the same
kernel, because it takes an actual pixel value rather than a weighted average of the
neighbourhood. Gaussian is cheaper and is the right default for sensor noise that is roughly
normal.

![None, Gaussian and Median at kernels 9 and 31](../assets/images/adjust_blur.jpg)

### Threshold

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Kind | `threshold_kind` | choice | `None`, `Binary`, `Binary inverted`, `Otsu`, `Adaptive mean`, `Adaptive Gaussian` | `None` | Which rule |
| Level | `threshold` | int | 0 … 255 | `127` | Cut point. **Ignored** by Otsu and both adaptive modes |
| Adaptive neighbourhood | `adaptive_block` | int | 3 … 51 | `11` | The two adaptive modes only. Odd, clamped to ≥ 3 |

!!! warning "Selecting a threshold mode binarises the working frame"

    Not just the `Threshold` view — the `Source` view goes black and white too, and every
    feature after this point measures a binary image. That is what makes the threshold part
    of preprocessing rather than a display option.

    Leave the combo on `None` and the `Threshold` canvas is still derived, at `Binary` using
    `Level`, so the contour finder has something to read and the rest of the chain keeps the
    colour frame.

#### Effect analysis

**Level 0 → 255** with `Binary`: at 0 everything is foreground and the mask is solid white;
at 255 nothing is. The interesting range is narrow and scene-dependent, which is exactly why
this is a slider and not an argument.

![Binary threshold at levels 60 to 210](../assets/images/adjust_threshold_level.jpg)

**The five modes.** `Binary` and `Binary inverted` are the same cut in opposite directions —
use the inverted one when the thing you want is darker than its surroundings. `Otsu` picks
the level itself by maximising between-class variance, which is excellent on a bimodal
histogram and arbitrary on a flat one. The two adaptive modes compute a level per
neighbourhood instead of one for the frame, which is what you need under uneven
illumination — and which produces speckle on smooth regions, because a neighbourhood with no
real structure still gets split in half.

**Adaptive neighbourhood 3 → 51.** Small blocks follow local illumination closely and turn
noise into structure; large blocks approach a global threshold and stop compensating for the
gradient you switched adaptive on for.

![The five threshold modes](../assets/images/adjust_threshold_kind.jpg)

### Selection — region of interest

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Limit analysis to a region | `roi_on` | bool | — | `false` | Master switch |
| X | `roi_x` | int | 0 … frame width | `0` | Left edge, px |
| Y | `roi_y` | int | 0 … frame height | `0` | Top edge, px |
| W | `roi_w` | int | 0 … frame width | `0` | Width. **`0` means out to the right edge** |
| H | `roi_h` | int | 0 … frame height | `0` | Height. **`0` means out to the bottom edge** |

Everything is measured **inside the rectangle only**. The frame around it stays on screen as
context and never reaches the numbers. Exported coordinates are translated back to full-frame
pixels, so a CSV means the same thing with a region as without one.

#### Effect analysis

The region is not a crop of the display, it is a crop of the *analysis*, and it happens
first. Otsu inside a region picks its level from that region's histogram alone; a blur inside
a region reads no pixels from outside it. Both would be untrue if the crop happened last, and
both are the reason it does not.

The second effect is speed: SIFT + HOG over a full 640×512 frame is 202 ms and over a 200×160
region 21 ms, which is the difference between dropping frames and not.

![Otsu with the region off and on — the same frame, two different levels](../assets/images/adjust_roi.jpg)

See [Controls → Region of interest](controls.md#region-of-interest) for the drag and spinbox
workflow.

---

## Colour histogram

**Tab:** Global · **Menu:** `Global`

![The Global tab](../assets/images/tab_global.png){ width="400" }

### What it does

Three-channel histograms of the preprocessed frame, plotted with `cv2.polylines` into a
512×256 canvas that is both a panel preview and a full `View`. **Always measured** — three
`calcHist` calls are cheaper than the checkbox that would let you turn them off.

### How to use it

1. Pick a space in the **Colour histogram** group.
2. Read it in the panel preview, or set `View` to `Histogram` for the full-size plot.
3. Channel means and standard deviations appear in the status bar and in `metrics.csv`; the
   per-bin counts go to `histogram.csv` on export.

| Name | Field | Type | Values | Default |
|---|---|---|---|---|
| Space | `hist_space` | choice | `RGB`, `HSV`, `LAB` | `RGB` |

#### Effect analysis

`RGB` shows the three channels as they are stored, and its three curves move together under
any exposure change. `HSV` separates hue from intensity, so a hue peak stays put when the
lighting changes — which is what makes it the right space for finding a coloured object.
`LAB` puts perceptual lightness in one channel and colour in two, so an `L` histogram is the
closest thing here to "what a human would call brightness".

![The same frame in RGB, HSV and LAB](../assets/images/color_histogram.jpg)

!!! note

    The histogram is a plot, not a frame. It stays 512×256 whatever the source is, which is
    why a region cannot be drawn while it is the active view and why it is never squeezed
    into a region rectangle.

---

## HOG — Histogram of Oriented Gradients

**Tab:** Global

### What it does

Divides the frame into cells, builds a histogram of gradient directions in each, normalises
over blocks of cells, and returns both the descriptor and a visualisation. It is the
classical shape descriptor — what a pedestrian detector was built on before CNNs.

### How to use it

1. Tick **Compute HOG**.
2. Set `View` to `HOG` to see the visualisation full size, or watch the panel preview.
3. Tune `Cell` first — it dominates the result — then orientations, then block size.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Compute HOG | `hog_on` | bool | — | `false` | Off by default because it is the expensive one |
| Orientations | `hog_orientations` | int | 2 … 18 | `9` | Gradient direction bins per cell |
| Cell (px) | `hog_cell` | int | 2 … 32 | `8` | Pixels per cell, square |
| Block (cells) | `hog_block` | int | 1 … 6 | `2` | Cells per normalisation block |

!!! danger "HOG costs 150–300 ms a frame at 640×512"

    That is slower than a video frame arrives. It runs on the worker thread so the window
    never freezes, but **playback will drop frames while it is on**. Draw a region to make it
    usable on video.

#### Effect analysis

**Cell 2 → 32.** At 2 px the descriptor is enormous, extremely sensitive to noise, and slow;
at 32 px each cell averages away everything but the coarsest shape. The classic 8 px is a
genuine sweet spot for human-scale objects at typical resolutions — scale it with your
object, not with your image.

**Orientations 2 → 18.** Two bins can only distinguish horizontal from vertical. Nine bins
over 180° is the standard unsigned configuration and separates most shapes. Past about 12 the
extra bins mostly encode noise, and the descriptor grows linearly in cost.

**Block 1 → 6.** Block normalisation is what gives HOG its illumination invariance. At 1 there
is effectively none, so a brightness change moves the whole descriptor. At 6 the
normalisation window covers so much of the frame that local contrast is flattened out.

![HOG at cell sizes 4, 8, 16 and orientations 4, 9, 18](../assets/images/texture_hog.jpg)

---

## LBP — Local Binary Patterns

**Tab:** Global

### What it does

Compares each pixel to `P` neighbours on a circle of radius `R` and encodes the comparison as
a binary code. Cheap, rotation-tolerant in its `uniform` form, and a genuinely good texture
descriptor for material and surface classification.

### How to use it

1. Tick **Compute LBP**.
2. Set `View` to `LBP` for the code image.
3. Read `lbp_entropy` in the status bar — high for varied texture, low for flat.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Compute LBP | `lbp_on` | bool | — | `false` | |
| Neighbours (P) | `lbp_points` | int | 1 … 24 | `8` | Sample points on the circle |
| Radius (R) | `lbp_radius` | int | 1 … 8 | `1` | Circle radius in px |
| Method | `lbp_method` | choice | `uniform`, `default`, `ror`, `nri_uniform`, `var` | `uniform` | scikit-image's LBP variants |

#### Effect analysis

**P and R together set the texture scale.** `P=8, R=1` reads the immediate neighbourhood and
responds to fine grain. `P=16, R=2` and `P=24, R=4` read progressively coarser structure and
cost proportionally more. Raising `R` without raising `P` undersamples the circle and
introduces aliasing — the conventional pairs are `(8,1)`, `(16,2)`, `(24,3)`.

**Method.** `uniform` collapses the codes with at most two bitwise transitions into `P+1`
bins and everything else into one, which is both compact and rotation-invariant — it is the
right default. `default` keeps all 2^P codes. `ror` rotates each code to its minimum, which
is rotation-invariant without the uniform collapse. `nri_uniform` is uniform *without*
rotation invariance, so it keeps orientation information. `var` returns local variance rather
than a code, which is contrast rather than pattern.

![LBP at P=8/R=1, P=8/R=3, P=16/R=2 and P=24/R=4](../assets/images/texture_lbp.jpg)

---

## Keypoints

**Tab:** Local · **Menu:** `Local`

![The Local tab](../assets/images/tab_local.png){ width="400" }

### What it does

Finds distinctive, repeatable points and computes a descriptor for each, so the same physical
point can be recognised in another frame. Two detectors are available:

- **SIFT** — 128-dimensional float descriptor, scale and rotation invariant, more
  discriminative, slow.
- **ORB** — 32-byte binary descriptor, fast enough for video, less discriminative.

!!! info "Why SURF, AKAZE, BRISK and KAZE are not here"

    Not an omission, and not a to-do. **SURF** is patented, lives behind
    `OPENCV_ENABLE_NONFREE`, and no published wheel sets it — not even
    `opencv-contrib-python`; it needs a source build. **AKAZE, BRISK and KAZE** are absent
    from the `opencv-python` 5.0 Python bindings entirely — `cv2.AKAZE` does not exist.
    **ALIKED and DISK**, which 5.0 adds in their place, require ONNX model files that are not
    bundled. What is shipped is the two that work.

### How to use it

1. Choose `SIFT` or `ORB`.
2. Move **Sensitivity** until you have the density of points you want.
3. Cap the count with **Max keypoints** if the overlay becomes unreadable.
4. Turn off **Draw scale and orientation** when there are thousands of them.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Detector | `detector` | choice | `None`, `SIFT`, `ORB` | `None` | |
| Sensitivity | `kp_sensitivity` | float | 0.0 … 1.0 | `0.5` | One normalised knob for both detectors |
| Max keypoints | `kp_max` | int | 10 … 5000 | `500` | Strongest by response are kept |
| Octave layers | `kp_octaves` | int | 1 … 8 | `3` | Scale-space depth |
| Edge threshold | `kp_edge` | float | 1 … 50 | `10.0` | Rejects points lying along an edge |
| Draw scale and orientation | `kp_rich` | bool | — | `true` | Rich keypoints rather than bare dots |

#### Effect analysis

**Sensitivity 0.0 → 1.0.** The two detectors' native thresholds are not comparable numbers —
SIFT wants a `contrastThreshold` around 0.04, ORB a `fastThreshold` around 20 — so the panel
exposes one normalised knob and maps it onto each detector's real range: SIFT `0.16 → 0.005`,
ORB `60 → 3`. Both run strict to permissive, so **up always means more keypoints**, whichever
detector is selected.

At 0.0 you get only the few highest-contrast corners, which is what you want for matching
across a wide baseline. At 1.0 you get thousands, most of them noise, and `Max keypoints`
becomes the thing actually deciding what you see.

![SIFT at sensitivity 0.1, 0.5 and 0.9](../assets/images/keypoints_sensitivity.jpg)

**Max keypoints 10 → 5000.** A cap, not a target — the detector finds what it finds and the
strongest by response survive. Raising it past what the sensitivity produces changes nothing.

**Octave layers 1 → 8.** Scale-space depth. More layers find features across a wider range of
sizes and cost proportionally more time. 3 is the standard SIFT value and is right unless
your objects vary in size by more than about 4×.

**Edge threshold 1 → 50.** Rejects keypoints that lie along an edge rather than at a corner —
they are poorly localised in one direction, so they move along the edge between frames and
match badly. Low values reject aggressively; high values keep almost everything.

![SIFT vs ORB, rich keypoints and plain dots](../assets/images/keypoints_detectors.jpg)

---

## Edges

**Tab:** Structures · **Menu:** `Structures`

![The Structures tab](../assets/images/tab_structures.png){ width="400" }

### What it does

Three edge operators, one at a time, rendered into the `Edges` canvas.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Kind | `edge_kind` | choice | `None`, `Canny`, `Sobel`, `Laplacian` | `None` | |
| Canny low | `canny_lo` | int | 0 … 500 | `100` | Below this a pixel is never an edge |
| Canny high | `canny_hi` | int | 0 … 500 | `200` | Above this it always is |
| Sobel kernel | `sobel_k` | int | 1 … 7 | `3` | Odd, clamped to 7 |
| Sobel dx | `sobel_dx` | int | 0 … 2 | `1` | Order of the x derivative |
| Sobel dy | `sobel_dy` | int | 0 … 2 | `1` | Order of the y derivative. `dx` and `dy` may not both be 0 |
| Laplacian kernel | `lap_k` | int | 1 … 31 | `3` | Odd |

#### Effect analysis

**Canny low and high.** Canny is a hysteresis threshold: above `high` a pixel is always an
edge, below `low` never, and in between only if it connects to a strong edge. Lowering `low`
extends existing edges and joins broken ones; lowering `high` creates new seed edges and,
past a point, floods the image. The conventional ratio is 1:2 or 1:3 — `100/200` is the
default for that reason. `30/90` on a noisy frame produces a dense web; `200/400` keeps only
the strongest boundaries.

![Canny at 30/90, 100/200 and 200/400](../assets/images/edges_canny.jpg)

**Sobel kernel 1 → 7.** A larger kernel is a wider derivative window: less noise-sensitive,
thicker and less precisely located edges. Sobel returns a gradient *magnitude*, not a binary
map, which is why it looks like an embossed frame rather than a line drawing — and why Hough
cannot use it directly.

**Sobel dx / dy.** `dx=1, dy=0` finds vertical edges only, `dx=0, dy=1` horizontal only,
`dx=1, dy=1` both. Second-order (`2`) responds to change in the gradient rather than the
gradient, which highlights ridges rather than steps.

**Laplacian kernel 1 → 31.** The second derivative in both directions at once, so it is
isotropic and has no direction parameter. It is the most noise-sensitive of the three at small
kernels; large kernels smooth it into a broad response.

![Canny, Sobel at kernel 3 and 7, and Laplacian at kernel 5](../assets/images/edges_kinds.jpg)

---

## Hough

**Tab:** Structures

### What it does

Finds lines or circles by voting in a parameter space. Every candidate edge pixel votes for
every line or circle that could pass through it, and the peaks are the answers.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Kind | `hough_kind` | choice | `None`, `Lines`, `Circles` | `None` | |
| Votes | `hough_thresh` | int | 1 … 400 | `120` | Accumulator threshold — how much evidence is needed |
| Min length / min distance | `hough_min_len` | int | 1 … 400 | `50` | Shortest line segment kept; for circles, the closest two centres may be |
| Max gap | `hough_max_gap` | int | 0 … 100 | `10` | Lines only: a gap this size still counts as one line |

!!! note "Hough builds its own Canny"

    Always, from `Canny low` and `Canny high` above — even when the edge combo is on Sobel or
    `None`. It needs a *binary* edge map and a Sobel magnitude is not one. So the two Canny
    knobs affect Hough whether or not Canny is the selected edge operator.

#### Effect analysis

**Votes 1 → 400.** The single most important knob here. Low values return hundreds of
spurious lines fitted to noise; high values return only long, unambiguous straight edges, and
past a point nothing at all. It scales with image size, because a longer line simply has more
pixels to vote with — a threshold tuned at 640×480 will find nothing at 320×240.

**Min length 1 → 400.** A post-filter on segment length, so it discards short fragments
without changing what the accumulator found.

**Max gap 0 → 100.** At 0, any interruption splits a line in two. Raising it bridges dashed
lines and dotted borders — and, past the scale of the real gaps in your scene, merges
genuinely separate collinear segments into one.

![Hough lines at 60, 120 and 240 votes](../assets/images/hough_lines.jpg)

---

## Corners

**Tab:** Structures

### What it does

Finds points where the image gradient is strong in two directions at once. Unlike keypoints,
corners carry no descriptor — they are locations, not identities.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Kind | `corner_kind` | choice | `None`, `Harris`, `Shi-Tomasi` | `None` | |
| Max corners | `corner_max` | int | 1 … 2000 | `200` | |
| Quality | `corner_quality` | float | 0.001 … 0.2 | `0.01` | Fraction of the strongest response a corner must reach |
| Min distance (px) | `corner_min_dist` | int | 1 … 100 | `10` | Shi-Tomasi only |
| Harris k | `harris_k` | float | 0.01 … 0.2 | `0.04` | Harris only. Lower detects more |

#### Effect analysis

**Quality 0.001 → 0.2.** Relative, not absolute: a corner must score at least this fraction of
the best corner in the frame. That makes it stable across exposure changes and unstable across
scene changes — one very strong corner raises the bar for everything else. At 0.001 almost
every local maximum qualifies; at 0.2 only corners within a factor of five of the best.

**Min distance 1 → 100.** Enforces spacing, so corners spread over the frame instead of
clustering on the one high-contrast object. Raise it when the overlay is a solid blob in one
corner of the image.

**Harris k 0.01 → 0.2.** The sensitivity term in Harris's response function. Lower values make
the response more permissive and detect more corners — including edge points that are not
really corners. 0.04–0.06 is the conventional band.

**Harris vs Shi-Tomasi.** Shi-Tomasi uses the smaller of the two eigenvalues directly rather
than Harris's determinant-minus-trace approximation, which makes it slightly more reliable and
slightly slower; it is also the one with the spacing control.

![Harris at k=0.04 and 0.15, Shi-Tomasi at quality 0.01 and 0.1](../assets/images/corners.jpg)

---

## Contours

**Tab:** Structures

### What it does

Traces the outlines of connected regions in the **`Threshold` image** — not the edge map.
Contour finding wants a binary image, and thresholding is how you get one. Each contour
contributes area, perimeter, bounding box and parent to `contours.csv`, and the filled result
is the `Contour mask` canvas — which is also the mask the dataset optimiser scores.

### How to use it

1. Set up the threshold on the Image Adjustment tab **first**, and look at the `Threshold`
   view to see exactly what the finder is being handed.
2. Tick **Find contours**.
3. Raise **Min area** until the noise is gone.
4. Switch to `Contour mask` to see the mask, or stay on `Source` for boxes over the frame.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Find contours | `contours_on` | bool | — | `false` | |
| Mode | `contour_mode` | choice | `External`, `List`, `Tree` | `External` | Retrieval mode |
| Min area (px) | `contour_min_area` | int | 0 … 5000 | `50` | |
| Bounding boxes | `contour_boxes` | bool | — | `true` | Draw the boxes as well as the outlines |

#### Effect analysis

**Min area 0 → 5000.** The noise filter. At 0 every speckle in the threshold becomes a
contour — on a real frame that is hundreds of them, and the CSV inherits every one. At 5000
only substantial regions survive. It is measured in pixels of the *analysed* frame, so a
region changes what a given number means.

![Minimum area at 0, 50, 500 and 5000 px](../assets/images/contours_min_area.jpg)

**Mode.** `External` keeps only outermost contours — a ring becomes one contour, not two.
`List` returns every contour with no hierarchy. `Tree` returns every contour *with* the
hierarchy, and is the only mode that fills the `parent` column in the exported CSV. Use
`External` for counting objects and `Tree` when holes matter.

![Threshold view, contour mask, and the same contours as boxes](../assets/images/contours_mask.jpg)

---

## Blobs

**Tab:** Structures

### What it does

`cv2.SimpleBlobDetector` — finds roughly convex regions and filters them by area, circularity
and convexity. Where contours give you every shape, blobs give you the round ones.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Find blobs | `blobs_on` | bool | — | `false` | |
| Min area (px) | `blob_min_area` | int | 1 … 5000 | `50` | |
| Max area (px) | `blob_max_area` | int | 2 … 50000 | `5000` | |
| Min circularity | `blob_circularity` | float | 0.0 … 1.0 | `0.0` | `0` disables the filter; `1` is a perfect circle |
| Min convexity | `blob_convexity` | float | 0.0 … 1.0 | `0.0` | `0` disables; low values allow dents |
| Dark blobs on light | `blob_dark` | bool | — | `true` | The OpenCV default polarity |

#### Effect analysis

**Min and max area** are a band, not a floor — a blob larger than the maximum is discarded as
firmly as one smaller than the minimum, which surprises people who expect the maximum to be a
cap. If nothing is detected, widen the band before touching anything else.

**Circularity 0 → 1** is `4πA/P²`: 1 is a circle, ~0.78 a square, and a long thin shape tends
to 0. Anything above about 0.8 rejects everything that is not nearly round.

**Convexity 0 → 1** is the blob's area over its convex hull's area. It rejects shapes with
bites taken out of them — two overlapping objects detected as one, typically. Low values
tolerate dents; high values demand a clean outline.

**Dark blobs on light** flips the polarity. If your objects are bright on a dark background —
which is the usual case for a thermal image or a fluorescence micrograph — untick it, or you
will find the gaps between your objects instead of the objects.

![Blobs with area 50–5000 and 500–50000](../assets/images/blobs.jpg)

---

## Motion

**Tab:** Motion · **Menu:** `Motion`

![The Motion tab](../assets/images/tab_motion.png){ width="400" }

### What it does

The only feature that measures the time axis, which makes it the only one with state behind
it. Six algorithms, all reporting the same thing: a 0–255 motion image, which one shared
**Sensitivity** threshold then cuts into a mask.

| Algorithm | What it is | When to use it |
|---|---|---|
| `MOG2` | Gaussian mixture background model | General purpose, adapts to gradual change |
| `KNN` | K-nearest-neighbour background model | Same job as MOG2, better on sparse foreground |
| `Farneback` | Dense optical flow | When the *shape* of the moving thing matters |
| `Lucas-Kanade` | Sparse flow at tracked corners, each vector splatted as a disc | Fast, but a disc is not a segmentation |
| `Frame difference` | Plain absolute difference | Simplest possible, no model, no adaptation |
| `Three-frame difference` | Minimum of two consecutive differences | Drops the ghost a plain difference leaves *behind* the object |

Because all six normalise to the same 0–255 image, **the knobs mean the same thing across all
of them** and switching algorithm is not re-learning the panel. Optical flow is scaled on the
way in — 8 px/frame reads as full scale, via `motion.FLOW_GAIN` if that needs calibrating for
a slow wide-angle scene.

![The same 40 frames through all six algorithms, shown as Motion mask](../assets/images/motion_algorithms.jpg)

### Shared controls

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Algorithm | `motion_algo` | choice | `None`, `MOG2`, `KNN`, `Farneback`, `Lucas-Kanade`, `Frame difference`, `Three-frame difference` | `None` | |
| Sensitivity | `motion_threshold` | int | 1 … 255 | `25` | Grey levels of change that count as motion. Lower finds more |
| Noise removal | `motion_open` | int | 0 … 15 | `3` | Morphological open kernel. `0` or `1` disables it |

#### Effect analysis

**Sensitivity 1 → 255.** At 1 almost every pixel that changed at all is foreground, including
sensor noise and compression artefacts. At 255 nothing is. Note that it has **no effect on
MOG2 and KNN**, which report a binary decision rather than a magnitude — for those two, the
model's own parameters are the sensitivity.

![Sensitivity 5, 25, 80 and 200 on MOG2](../assets/images/motion_sensitivity.jpg)

**Noise removal 0 → 15.** A morphological opening: erode then dilate, which deletes anything
thinner than the kernel and leaves everything else roughly its original size. It is the first
thing to reach for when the mask is speckled. Past about 9 it starts eating the thin parts of
real objects.

![Noise removal 0, 3, 9 and 15 on a frame difference](../assets/images/motion_open.jpg)

### Background subtraction — MOG2 and KNN

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Learning rate | `motion_learning` | float | −1.0 … 1.0 | `-1.0` | `-1` lets OpenCV pick from History; higher forgets the background faster |
| MOG2 history | `mog_history` | int | 1 … 2000 | `500` | Frames the model is built from |
| MOG2 variance | `mog_var` | float | 1 … 100 | `16.0` | Lower is more sensitive |
| MOG2 shadows | `mog_shadows` | bool | — | `true` | Detect shadows (they are never counted as motion) |
| KNN history | `knn_history` | int | 1 … 2000 | `500` | |
| KNN distance | `knn_dist` | float | 10 … 2000 | `400.0` | Squared distance to a neighbour |
| KNN shadows | `knn_shadows` | bool | — | `true` | |

#### Effect analysis

**History 1 → 2000.** How much past the model averages over. Short histories adapt fast, which
means a slow-moving object is absorbed into the background and disappears; long histories
remember a scene that no longer exists, so a camera adjustment lights up the whole frame for
hundreds of frames. **A plume that never moves eventually *becomes* background** — that
behaviour is what History and Learning rate exist to control.

**Learning rate −1 → 1.** `-1` derives the rate from History, which is what you want almost
always. `0` freezes the model — nothing is ever learned after the first frames, useful when
you have clean background footage to prime with. `1` relearns the background from every
single frame, which makes everything except the very fastest motion invisible.

**MOG2 variance 1 → 100.** The threshold on squared Mahalanobis distance for a pixel to match
its background model. Lower is more sensitive and noisier.

**Shadows.** Detected shadows are found but **never counted** — a shadow is the moving thing's
effect on the background, not the moving thing. Untick to spend nothing looking for them.

### Optical flow — Farneback and Lucas-Kanade

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Pyramid scale | `fb_pyr_scale` | float | 0.1 … 0.9 | `0.5` | Each level this fraction of the last |
| Pyramid levels | `fb_levels` | int | 1 … 8 | `3` | More levels catch faster motion |
| Window (px) | `fb_winsize` | int | 3 … 51 | `15` | Bigger is smoother and less precise |
| Iterations | `fb_iterations` | int | 1 … 10 | `3` | Refinement passes per level |
| LK max points | `lk_max_points` | int | 1 … 1000 | `200` | Corners tracked per frame |
| LK window (px) | `lk_win` | int | 3 … 51 | `15` | Also the size of the disc each tracked point paints |

!!! danger "Farneback costs 30–60 ms a frame at 640×512"

    It runs off the GUI thread, but playback will drop frames.

#### Effect analysis

**Pyramid levels 1 → 8.** Flow is estimated coarse-to-fine. One level can only track motion
smaller than the window; each additional level roughly doubles the displacement that can be
tracked, at a cost. If fast objects come out with zero flow, this is the knob.

**Window 3 → 51.** The neighbourhood each flow vector is estimated over. Small windows are
precise and noisy and fail on textureless regions; large windows are smooth, robust, and blur
the motion boundary between two objects moving differently.

**Pyramid scale 0.1 → 0.9.** How much each pyramid level shrinks. 0.5 halves each time — the
conventional choice. Values near 0.9 build many nearly-identical levels, which is slow and
gains little; near 0.1 the levels are so far apart that the coarse estimate does not guide the
fine one well.

**LK max points and window.** Lucas-Kanade is *sparse* — it tracks corners, so its mask is a
disc per tracked point rather than the outline of anything. Use Farneback when the shape of
the moving thing matters. The window doubles as the disc radius, so raising it produces a
smoother-looking but less honest mask.

### Heatmap

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Overlay the heatmap on the view | `heat_on` | bool | — | `false` | Composites onto whichever view is showing |
| Opacity | `heat_opacity` | float | 0.0 … 1.0 | `0.5` | |
| Window (frames) | `heat_window` | int | 1 … 200 | `20` | How far back the heat is averaged |
| Floor | `heat_threshold` | float | 0.0 … 1.0 | `0.05` | Fraction of full scale below which a pixel stays cold |

`Motion heatmap` is an exponential average of the motion over the last N frames, painted with
`COLORMAP_JET` and **weighted per pixel by its own heat**, so cold areas stay as the frame
instead of washing blue. Blue is rare motion, red is constant motion.

#### Effect analysis

**Window 1 → 200.** At 1 the heatmap is this frame's motion and nothing else — it flickers
with every frame. At 200 it is a long-exposure photograph of where motion happened, settling
over several seconds and reacting slowly to change. It is an exponential average rather than a
true N-frame window, so the tail is soft rather than a hard cutoff.

![Heat window of 3, 20 and 60 frames on dense optical flow](../assets/images/motion_heatmap.jpg)

**Floor 0.0 → 1.0.** At 0 every pixel gets some colour, including pure noise, and the frame
turns blue. Raising it keeps the cold parts of the image as the original frame, which is what
makes the overlay readable at all.

### Moving objects

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Min area (px) | `motion_min_area` | int | 0 … 5000 | `50` | Contours smaller than this are noise |
| Bounding boxes | `motion_boxes` | bool | — | `true` | |
| Label area and speed | `motion_metrics` | bool | — | `false` | Text on every box |
| Max travel (px/frame) | `motion_max_travel` | int | 1 … 500 | `60` | Further than this and two blobs are not the same object |

![Boxes, boxes with labels, and the heatmap composited over the source](../assets/images/motion_boxes.jpg)

#### Effect analysis

**Max travel 1 → 500.** Speed is measured by matching each blob to the nearest centroid in the
previous frame; this is the radius beyond which no match is made. Too low and fast objects
report zero speed because they were never matched; too high and unrelated blobs get paired
across the frame and report nonsense.

!!! warning "Speed is not tracking"

    Boxes carry area and pixels-per-frame speed, matched by nearest centroid between frames.
    That answers *"how fast is something moving here"*, **not** *"where did object 7 go"* —
    there is no track identity, so two blobs that cross swap speeds.

### The three state rules

`MotionState` is owned by whoever drives the frames — the worker has one, an export has its
own — and is reset by three things, all of which happen in normal use:

1. **The same frame twice does not advance it.** Dragging a knob while paused re-analyses the
   frame on screen over and over; feeding a background model the same image fifty times
   teaches it that image *is* the background, so a still frame would fade to nothing while
   you tuned it. The thresholds stay live though — only the carried state is pinned.
2. **A seek or a backwards step resets it.** The previous frame is no longer the previous
   frame, and differencing across the jump lights up the whole image.
3. **A changed model resets it** — a different algorithm, or a resized region, leaves a model
   of the wrong kind or the wrong shape.

The region needs no special handling: `adjust` crops before any feature runs, so the frame
this module sees *is* the region, and the heatmap is confined to it for free.

---

## Export

**Menu:** `File → Export analysis…` · **Shortcut:** ++ctrl+s++

![The export dialog](../assets/images/dialog_export.png)

### What it does

Re-runs the chain over **every frame** of the open source with the current settings and writes
the results to a folder. It runs on its own thread with its own motion state, so exporting
while the window plays disturbs neither.

### How to use it

1. Tick what you want.
2. Choose an output folder — OK stays disabled until you have both.
3. Watch the frame counter in the status bar.

| Option | Field value | Writes |
|---|---|---|
| Settings | `settings` | `settings.json` — every control's value, and no measurements |
| CSV tables | `csv` | `metrics.csv` plus `contours.csv`, `keypoints.csv`, `blobs.csv`, `lines.csv`, `corners.csv`, `motion.csv`, `histogram.csv` |
| Overlays | `overlays` | `overlays/frame_%06d.png` — the composited frames |
| Objects | `objects` | `objects/frame_%06d_%02d.png` — every moving object, cropped |

#### Why the settings ship alongside the numbers

A metrics table without the parameters that produced it is not reproducible, so the parameters
go in the same folder — and the file is in the same shape the application's own cache uses, so
++ctrl+l++ reads it straight back. Ticking **Settings** on its own reads no frames at all, so
it is instant.

`metrics.csv` is one row per frame. The per-object CSVs are one row per contour, keypoint,
blob, line, corner or moving object, each carrying the frame it came from. Rows are
**streamed, not accumulated**: a 900-frame clip with SIFT on produces close to half a million
keypoint rows, which would cost more memory than the video.

Object crops come out of the **raw** frame rather than the composite, so what lands on disk is
the object as the camera saw it and not a picture of a box drawn round it.

!!! tip

    With HOG on, an export costs roughly a quarter of a second per frame. The dialog says so;
    it is not stuck.

---

## Dataset → Analyse

**Menu:** `Dataset → Analyse…` · **Shortcut:** ++ctrl+d++ · **Needs:** `uv sync --group dataset`

![The dataset analysis dialog](../assets/images/dialog_analyse.png)

### What it does

Everything else in the application shows you what the current settings *do*. This is one of
the two parts that knows what they *should* do, because it is one of the two with ground
truth.

It takes a COCO segmentation dataset — an `instances_*.json` and the folder of images it
describes — and surveys **what actually separates the annotated pixels from their
background**. COCO needs no extra dependency: annotations are plain JSON, polygons are
`cv2.fillPoly`, and RLE decodes in about thirty lines, including the compressed form most
export tools write.

### How to use it

1. Point it at the annotations file. The images folder is guessed from it — beside the JSON,
   or in a sibling named after the split — and you can correct the guess.
2. Choose an output folder.
3. Optionally restrict to one class by name. Leave it blank for all of them; a wrong name is
   rejected with the list of valid ones.
4. Set how many images to decode for the pixel metrics.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Annotations | `ann_path` | path | — | — | The `instances_*.json` |
| Images folder | `images_dir` | path | — | — | Where the images it names live |
| Output folder | `out_dir` | path | — | — | Five PNGs and a `summary.json` land here |
| Images to sample | `n` | int | 1 … 100000 | `150` | Images decoded for the pixel metrics |
| Class | `category` | text | — | blank | Blank means every class |

### Two passes, and why

The survey runs in two passes because they cost three orders of magnitude apart.

- **Every annotation in the file** is cheap, so all of them are used: area ratios, aspect
  ratio, scale variance, mask complexity (`P²/4πA`), class co-occurrence, and inter-class
  bounding-box overlap.
- **Pixel metrics need images decoded**, so they run over a sample: colour histograms in
  RGB/HSV/LAB, contrast, LBP texture, Sobel and Canny edge density, a radial FFT profile, and
  an occupancy heatmap.

Each pixel metric is measured **twice on the same frame** — once under the mask, once under
its complement. A histogram of annotated pixels alone says almost nothing; the useful quantity
is the *difference* from the background they have to be told apart from, and taking both from
one frame cancels exposure and scene content out of the comparison.

#### Effect analysis

**Images to sample 1 → 100000.** Only the pixel metrics pay for this — the annotation
statistics always cover the whole file. Small samples are fast and noisy; a few hundred images
is usually enough for the histograms to stop moving. It is a linear cost: every image is
decoded once.

**Class filter.** Restricting to one class turns "what separates annotations from background"
into "what separates *this* class from everything else, including the other classes", which is
usually the more actionable question.

### What you get

Five figures and a `summary.json`, opened in a dashboard when the job finishes.

| Figure | Shows |
|---|---|
| `colour.png` | RGB, HSV and LAB histograms, mask (solid) vs background (dashed), area-normalised |
| `texture.png` | LBP histogram, Sobel and Canny edge density, contrast — mask vs background |
| `spatial.png` | Occupancy heatmap and radial frequency profile — where objects are and at what spatial frequencies |
| `geometry.png` | Area ratio, aspect ratio, scale variance and mask complexity per class |
| `classes.png` | Class co-occurrence and inter-class bounding-box overlap |

![Colour: annotated pixels against their own background, in three spaces](../assets/images/dataset_colour.png)

![Texture and edges under the mask and under its complement](../assets/images/dataset_texture.png)

![Where the objects are, and at what spatial frequencies](../assets/images/dataset_spatial.png)

![Per-class geometry over every annotation in the file](../assets/images/dataset_geometry.png)

![Class co-occurrence and bounding-box overlap](../assets/images/dataset_classes.png)

!!! failure "It refuses to produce an empty report"

    If not one sampled image could be measured, the job raises rather than writing five clean,
    blank, entirely convincing figures. Nothing about a blank chart looks wrong, which is
    exactly the problem with producing one.

---

## Dataset → Optimise

**Menu:** `Dataset → Optimise…` · **Shortcut:** ++ctrl+shift+d++ · **Needs:** `uv sync --group dataset`

![The optimiser dialog](../assets/images/dialog_optimise.png)

### What it does

Searches for the settings that best reproduce the ground-truth masks, using an Optuna TPE
sampler over twelve parameters, scoring each candidate against the dataset's real annotations.

### How to use it

1. Give it the same three paths the survey wants.
2. Set the number of trials and the images each trial is scored over.
3. Set the three objective weights.
4. Run it. Trial zero is **whatever is on screen**, so the search starts from the tuning you
   did by hand and the result is always comparable against it.
5. When it finishes, pick a trade-off from the front and press **Apply** — or **Cancel** and
   keep what you had.

`Choose result…` on the dialog reopens a past run's `front.json` and applies one of its
trade-offs without searching again.

| Name | Field | Type | Range | Default | Description |
|---|---|---|---|---|---|
| Annotations / Images / Output | `ann_path`, `images_dir`, `out_dir` | path | — | — | As above |
| Images to sample | `n` | int | 1 … 100000 | `50` | Images **every trial** is scored over |
| Class | `category` | text | — | blank | |
| Trials | `trials` | int | 5 … 5000 | `100` | |
| α IoU | `weights[0]` | float | 0 … 100 | `1.0` | Overlap between predicted and true mask |
| β recall | `weights[1]` | float | 0 … 100 | `0.5` | Share of the true mask that was found |
| γ spill | `weights[2]` | float | 0 … 100 | `0.5` | Share of the background wrongly included |

### The objective

```
f(θ) = α·IoU(Mθ, Mgt) + β·|Mθ ∩ Mgt|/|Mgt| − γ·|Mθ \ Mgt|/|I \ Mgt|
```

IoU alone would do for a benchmark. **β pays for coverage**, so a timid threshold that finds a
clean sliver of every object cannot win. **γ charges for spilled background**, normalised by
how much background there is, so over-segmenting costs the same whether the objects are large
or small.

The search is genuinely **multi-objective**: Optuna maximises IoU and recall and minimises
spill as three separate directions, and what comes back is a Pareto front of non-dominated
trade-offs rather than one winner. `f(θ)` above is then used to *rank* that front for display,
which is what the weights are for.

!!! warning "γ needs raising on small objects"

    Its penalty is divided by the background, and when objects are ~1% of the frame the
    background is nearly everything — so a mask covering ten times the ground truth is charged
    almost nothing. On the sample plume set, default weights score a 9.9%-coverage mask at
    0.5126 and a tight 1.6% one at 0.5156: half a percent apart for a threefold difference in
    IoU, which is far too flat for the sampler to climb. At **γ = 5** the same search returns
    IoU 0.30 instead of 0.09.

    The result reports IoU, recall, spill and coverage separately for exactly this reason, and
    flags any trade-off whose mask covers more than three times the ground truth as
    **oversegmented**.

### What it searches, and what it does not

Twelve parameters, and the reason is structural. `Mθ` is the `Contour mask`, and there is one
route to it:

```
adjust.apply() ─▶ canvases["Threshold"] ─▶ structure._contours() ─▶ "Contour mask"
```

| Searched | Range |
|---|---|
| `brightness` | −100 … 100 |
| `contrast` | 0.5 … 3.0 |
| `saturation` | 0.0 … 3.0 |
| `gamma` | 0.3 … 3.0 |
| `color_space` | the five |
| `blur_kind` | the three |
| `blur` | 0 … 31 |
| `threshold_kind` | the six |
| `threshold` | 0 … 255 |
| `adaptive_block` | 3 … 51 |
| `contour_mode` | the three |
| `contour_min_area` | 0 … 5000 |

HOG, LBP, SIFT, ORB, Canny, Hough, Harris and the blob detector **cannot move the score by a
pixel**, because they produce descriptors, keypoints and overlays rather than a mask.
Searching them would not be more thorough; it would be twenty-three dimensions of noise at a
second a trial.

`contours_on` is pinned **on**, since it is what makes a mask at all, and `roi_on` pinned
**off**, since a ground-truth mask covers the whole frame.

Proposed floats are snapped to `0.01`, which is what a slider can hold. Otherwise the winner
would quietly become a slightly different setting the moment **Apply** put it into a control,
and the score printed beside it would not be the score you had.

#### Effect analysis

**Trials 5 → 5000.** TPE needs perhaps twenty trials before its model beats random sampling,
so anything under that is effectively a random search. The cost is `trials × images` full
chain runs; trials run on a process pool with one core left free for the GUI.

**Images 1 … 100000.** Every trial pays for this one, unlike a survey. Small samples make the
score noisy and the winner overfitted to a handful of frames; the sample is decoded **once**
and held for the whole study, so re-drawing it per trial cannot make the objective stochastic.

### What you get

![The Pareto front, ranked by f(θ), with Apply](../assets/images/dialog_pareto.png)

The dialog shows every non-dominated trade-off with its `f(θ)`, IoU, recall, spill, coverage
and the settings that differ from your baseline, and the header reports the baseline score so
you can see whether the search beat hand tuning at all. Three files land in the output folder:

| File | Contents |
|---|---|
| `best_settings.json` | The top-ranked trade-off, in the same shape an export writes — ++ctrl+l++ reads it back |
| `front.csv` | The front, flattened for a spreadsheet |
| `front.json` | The whole front, which is what `Choose result…` reopens |

---

## ROS bag extraction

**Menu:** `Rosbag → Extract from ROS bag…` · **Shortcut:** ++ctrl+shift+e++ · **Needs:** `uv sync --group rosbag`

![The ROS bag dialog](../assets/images/dialog_rosbag.png)

### What it does

Dumps every message on a ROS 2 bag's image topic to PNG or JPG, so a recording becomes a
folder of frames this application — or a labelling tool — can open.

It has its own menu rather than being a third `Dataset` verb, because a bag is not a COCO
dataset; it is an input a COCO dataset gets built *from*.

### How to use it

1. Choose a `.db3` file. The topic list is read from the file itself, immediately, without
   decoding any messages — a bare `.db3` with no `metadata.yaml` beside it reads fine.
2. Pick the image topic. If there is exactly one it is already selected.
3. Choose an output folder and a format.
4. When it finishes, the confirmation offers **Open folder**.

| Name | Field | Type | Values | Default | Description |
|---|---|---|---|---|---|
| Bag | `bag_path` | path | `*.db3` | — | A ROS 2 bag |
| Topic | `topic` | choice | the bag's image topics | first | Read from the file |
| Output folder | `out_dir` | path | — | — | |
| Format | `fmt` | choice | `png`, `jpg` | `png` | |

#### Effect analysis

**Format.** `png` is lossless and roughly 5–10× larger; `jpg` is lossy and fast. If the frames
are going to become training data or ground truth, use `png` — you cannot un-compress a JPEG
artefact later, and thresholding is exactly the operation that turns one into a spurious
contour.

Both `sensor_msgs/msg/Image` and `sensor_msgs/msg/CompressedImage` are supported, and every
message on the chosen topic is written as one frame.
