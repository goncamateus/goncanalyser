"""Entry point: ask for something to look at, then open the window on it.

The file dialog *is* the startup screen — there is no empty-window state to
design around and no CLI to keep in sync. A path can still be passed as an
argument to skip the dialog, which is what you want when you are re-running the
same clip twenty times in a row. A folder argument works too.
"""

import sys

# LOAD-BEARING, AND IT LOOKS LIKE IT IS NOT. Do not move this below the PyQt
# import and do not delete it as unused.
#
# matplotlib's `ft2font` and PyQt6 each ship their own libfreetype. Whichever
# loads first wins the symbols for the whole process, and matplotlib's extension
# is the one that cannot survive being given the other's: every chart the dataset
# report draws then dies inside `savefig` with
#
#     FT_Render_Glyph … failed with error 0x62: raster overflow
#
# Qt claims FreeType when it builds its first widget, not when it is imported —
# so importing matplotlib anywhere after `MainWindow` exists is already too late,
# including from inside a worker thread, which is where the report would naturally
# do it. Claiming it here, first, costs a fraction of a second and is the whole
# fix. `dataset/` may then be imported lazily wherever it likes.
#
# Absent whenever the optional `dataset` group is not installed — which is the
# normal state of the packaged desktop build, and is not an error.
try:
    import matplotlib.ft2font  # noqa: F401
except ImportError:
    pass

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core.source import FrameSource, SourceError  # noqa: E402
from ui.dialogs import open_source  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    # QApplication must exist before any widget, including the file dialog.
    app = QApplication(sys.argv)
    # Names the per-platform config directory the settings cache lives in.
    app.setApplicationName("analyser")

    path = sys.argv[1] if len(sys.argv) > 1 else open_source(None)
    if not path:
        return 0  # cancelled: quit quietly, an empty window would be useless

    try:
        source = FrameSource(path)
    except SourceError as exc:
        QMessageBox.critical(None, "Cannot open", str(exc))
        return 1

    window = MainWindow(source)
    window.resize(1400, 820)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
