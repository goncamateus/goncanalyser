"""Frame capture and OpenCV processing — the half of the app that has no widgets.

Deliberately empty: importing the submodules here would drag PyQt in through
`video_thread` every time someone only wanted `pipeline`, which is the one module
that is supposed to be usable without a GUI.
"""
