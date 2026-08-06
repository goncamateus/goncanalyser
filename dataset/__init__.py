"""Ground truth: what a COCO segmentation dataset says is foreground.

The rest of the app has no notion of a correct answer. It shows what the current
settings produce and leaves the judging to whoever is looking. This package is the
other half — a corpus of annotated masks, and the two things worth doing with one:

* `stats`    — measure what actually separates annotated objects from their
               background, so tuning starts from evidence rather than a guess.
* `optimise` — search the settings that best reproduce those masks.

Kept Qt-free for the same reason `features/*` is: both entry points are batch jobs
over hundreds of images, and both must be runnable from a plain script.

`matplotlib` and `optuna` live in the `dataset` dependency group, so nothing here
may be imported at module scope by anything the app loads at launch — the frozen
desktop bundle does not carry them. `ui.main_window.analyse_dataset` imports this
package inside the slot and reports the missing group as a message.
"""
