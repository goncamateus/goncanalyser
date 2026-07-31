"""Entry point: ask for something to look at, then open the window on it.

The file dialog *is* the startup screen — there is no empty-window state to
design around and no CLI to keep in sync. A path can still be passed as an
argument to skip the dialog, which is what you want when you are re-running the
same clip twenty times in a row. A folder argument works too.
"""

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from core.source import FrameSource, SourceError
from ui.dialogs import open_source
from ui.main_window import MainWindow


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
