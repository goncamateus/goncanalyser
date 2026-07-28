"""Entry point: ask for a video file, then open the window on it.

The file dialog *is* the startup screen — there is no empty-window state to
design around and no CLI to keep in sync. A path can still be passed as an
argument to skip the dialog, which is what you want when you are re-running the
same clip twenty times in a row.
"""

import sys

from PyQt6.QtWidgets import QApplication, QFileDialog

from gui.main_window import MainWindow

VIDEO_FILTER = "Video (*.mp4 *.mov *.avi *.mkv *.m4v);;All files (*)"


def pick_video() -> str:
    """Modal open dialog. Returns "" when the user cancels."""
    path, _ = QFileDialog.getOpenFileName(None, "Open video", "", VIDEO_FILTER)
    return path


def main() -> int:
    # QApplication must exist before any widget, including the file dialog.
    app = QApplication(sys.argv)

    path = sys.argv[1] if len(sys.argv) > 1 else pick_video()
    if not path:
        return 0  # cancelled: quit quietly, an empty window would be useless

    window = MainWindow(path)
    window.resize(1280, 760)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
