# Image and video controls

Playback, frame scrubbing, viewer scaling, region selection, batch image processing, and the
full keyboard and mouse reference.

## The transport bar

Everything for moving through a source sits in one row under the image.

![The window, with the transport bar under the viewer](../assets/images/window_overview.png)

| Control | What it does |
|---|---|
| `View` | Which stage of the chain is on screen. Ten options — see [Overview → The ten views](overview.md#the-ten-views) |
| ◀ | Step back one frame. Pauses playback |
| **Play** / **Pause** | Toggles playback. The label is the action, not the state |
| ▶ | Step forward one frame. Pauses playback |
| Seek slider | Scrub to any frame. Ranges `0` to `frames − 1` |
| Frame number | The index currently displayed |

### Playing and pausing

++space++ toggles playback from anywhere in the window, and so does the button. Playback runs
at the source's own frame rate when the chain can keep up, and drops frames when it cannot —
HOG and dense optical flow are the two that make it not keep up.

While paused, **the controls stay live**. Dragging a knob re-analyses the frame on screen, so
tuning is a paused activity by design: you get the full frame rate of your own reaction time
rather than the video's. The worker skips the chain entirely when paused on a frame nobody
re-tuned, so a paused window costs nothing.

### Stepping

++period++ steps forward, ++comma++ steps back. Both pause first — stepping while playing is
not a coherent request, and the button label follows.

!!! note "Stepping backwards resets the motion state"

    Rule 2 of the [three state rules](features.md#the-three-state-rules): the previous frame
    is no longer the previous frame, so differencing across the jump would light up the whole
    image. A background model rebuilds from the new position. Nothing else in the chain is
    affected — only motion carries state.

### Scrubbing

The seek slider covers the whole source. Dragging it emits a seek per position, and the worker
takes the latest — so scrubbing quickly does not queue up work. As with a backwards step, a
seek resets the motion state.

The slider and the frame label are updated *by* the worker as it advances, with signals muted
so that echoing the position back does not read as a user seek and fight the handle you are
dragging.

### A single image has no transport

Open one image and the ◀, Play, ▶ and slider all disable themselves. There is nothing to
scrub, step through or play, and leaving them live would be four controls that do nothing. The
`View` picker and every tab still work normally.

## Viewer scaling — and what is not here

The frame is scaled to fit the viewer with `KeepAspectRatio` and a smooth transformation, and
centred, so one axis carries a letterbox. The viewer has a minimum size of 640×360 and takes
all the space the window gives it.

!!! warning "There is no zoom or pan"

    This is a deliberate statement of scope, not an omission from this page. The viewer fits
    the frame to the window and that is all it does — there is no zoom control, no wheel
    handler, no drag-to-pan, and no 1:1 pixel mode.

    Two things do the job people usually want zoom for:

    - **Resize the window** (or maximise it). The frame is re-scaled on every resize, so a
      larger window is a larger image, at full smoothing.
    - **Draw a region.** It does not magnify, but it does restrict the analysis to the part
      you care about — which is the thing you were going to zoom in to check — and it makes
      the expensive features an order of magnitude faster while you do.

    If you need to inspect individual pixels, export overlays and open them in an image
    viewer.

## Region of interest

**Image Adjustment → Selection**, with two interchangeable ways to set the same rectangle.

![A region: inside it is analysed, outside it is the raw frame](../assets/images/window_region.png)

### Drawing it with the mouse

1. Go to the **Adjust** tab and press **Draw region on the image**.
2. The cursor over the viewer becomes a crosshair — the drag is now *armed*.
3. Drag a rectangle on the image. Any direction works; up-left is normalised the same as
   down-right.
4. On release the four spinboxes fill in, **Limit analysis to a region** ticks itself, the
   status bar reports `region x, y  w×h`, and the drag disarms.

Selection is **armed, not always-on**. A click on the viewer is otherwise indistinguishable
from a click meant for anything else, and an accidental drag would silently re-crop the
analysis without anyone noticing.

A drag that runs off the edge of the widget is clamped into the image rather than rejected —
running off the edge is a perfectly clear "select out to the border", and refusing it would
make the corners hard to reach.

### Typing it

| Box | Field | Step | Meaning |
|---|---|---|---|
| X | `roi_x` | 10 | Left edge, px |
| Y | `roi_y` | 10 | Top edge, px |
| W | `roi_w` | 10 | Width. **`0` means out to the right edge** |
| H | `roi_h` | 10 | Height. **`0` means out to the bottom edge** |

The arrows step by 10 because a region is a number you know or nudge, not one you sweep. All
four are capped at the source's dimensions, so a rectangle cannot be typed off-frame. **Reset
to the full frame** zeroes all four without disturbing any other tab.

The mouse and the boxes stay in sync — they are two interfaces to one rectangle, not two
rectangles.

### When Draw is unavailable

The button disables itself, with a tooltip saying why, when:

- the `View` is `Histogram` — that is a 512×256 plot, not the frame, and a rectangle drawn on
  a chart would mean nothing; or
- no source is open yet.

Switching to the Histogram view while a drag is armed disarms it.

## Batch image processing

A folder is a source. Point the application at one and every image in it becomes a frame:

```bash
uv run python main.py frames/
```

or **File → Open image folder…** (++ctrl+shift+o++).

| Behaviour | Detail |
|---|---|
| Which files | Every file whose extension is `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp` or `.ppm` |
| Order | Sorted by path, so `frame_001` … `frame_010` behave |
| Transport | Fully live — Play runs through the folder, ◀ ▶ step, the slider scrubs |
| Frame size | Images may differ in size; each is analysed as it comes |
| Empty folder | Refused with `no images in <path>` rather than opening blank |

Two things make this the batch workflow rather than just a viewer:

1. **Tuning carries across the whole folder.** Set the controls once, and every image is
   analysed with the same settings — which is the point of a batch.
2. **Export re-runs the entire source.** ++ctrl+s++ writes one `metrics.csv` row per image,
   per-object rows carrying the frame index they came from, and — if ticked — one overlay PNG
   per image. `metrics.csv` also carries each frame's **file name**, so a row can be traced
   back to the image it came from.

!!! tip "Swapping the source keeps your tuning"

    Opening a different file or folder does **not** reset the controls. Tuning is the thing
    you carry from one image to the next, so a new source reuses the window rather than
    opening a second one.

## Dataset job controls

A dataset survey, an optimisation or a bag extraction runs on its own thread behind a
**modeless** window — you can keep working while it runs.

| Control | What it does |
|---|---|
| **Hide** | Puts the window away and **leaves the work running** |
| **Cancel** | Stops the job. Cooperative, so it takes effect at the end of the step in flight — one trial, or one image |
| The pie in the status bar | Shows progress for as long as the job runs. **Click it to bring the window back** |

The two buttons sound alike and are not. Hiding cannot lose track of work that takes ten
minutes, because the pie stays in the corner and clicking it reopens the window.

The job's messages go to their own label beside the pie rather than sharing `showMessage` with
the frame worker — which writes there on every frame, a hundred a second even while paused,
and would wipe anything a job had to say before it could be read.

Closing the application cancels a running job rather than waiting for it.

## Keyboard reference

!!! info "macOS"

    Qt maps ++ctrl++ in a shortcut onto ++cmd++, so every `Ctrl+…` below is `⌘…` on macOS.
    This is the portable spelling, not a Windows-ism.

### Transport

| Keys | Action |
|---|---|
| ++space++ | Play / pause |
| ++period++ | Step forward one frame |
| ++comma++ | Step back one frame |

### File

| Keys | Action |
|---|---|
| ++ctrl+o++ | Open image or video… |
| ++ctrl+shift+o++ | Open image folder… |
| ++ctrl+l++ | Load settings… |
| ++ctrl+s++ | Export analysis… |
| ++ctrl+r++ | Reset all controls — press again to undo |
| ++ctrl+comma++ | Preferences… |
| ++ctrl+w++ | Close window |
| ++ctrl+q++ | Quit |

### Dataset and bags

| Keys | Action |
|---|---|
| ++ctrl+d++ | Dataset → Analyse… |
| ++ctrl+shift+d++ | Dataset → Optimise… |
| ++ctrl+shift+e++ | Rosbag → Extract from ROS bag… |

### Reset is also an A/B compare

++ctrl+r++ does not ask for confirmation — a shortcut that stops to ask is not worth having.
It stashes the previous values instead, so a mistyped ++ctrl+r++ costs one more keystroke
rather than the last twenty minutes of tuning. Press it again and your tuning comes back, and
it keeps toggling between defaults and your last settings.

That makes it the fastest way to answer "is this actually better than the default?".

## Mouse reference

| Action | Where | Result |
|---|---|---|
| Left-drag | On the image, **after** pressing Draw | Selects a region. Disarms afterwards |
| Left-click | The progress pie in the status bar | Reopens a hidden dataset job window |
| Scroll | A control tab | Scrolls that tab only — each has its own scroll area |
| Left-click | A menu bar analysis entry | Raises that tab. Never opens a second window |
| Drag | The seek slider | Scrubs the source |

Everything else is a standard Qt control: sliders drag and accept arrow keys, spinboxes type
and step, combos open with ++space++ or a click.

## Menus at a glance

| Menu | Entries |
|---|---|
| `File` | Open image or video…, Open image folder…, Load settings…, Export analysis…, Reset all controls, Preferences…, Close window, Quit |
| `Image Adjustment` · `Global` · `Local` · `Structures` · `Motion` | Each raises its tab |
| `Dataset` | Analyse…, Optimise… |
| `Rosbag` | Extract from ROS bag… |

![Preferences: where the settings cache lives, and a reset](../assets/images/dialog_preferences.png)

**File → Preferences** shows the path of the settings cache — `~/.config/analyser/settings.json`
on Linux, `~/Library/Preferences/analyser/settings.json` on macOS — and offers the same reset
as ++ctrl+r++.
