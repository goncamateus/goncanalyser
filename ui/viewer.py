"""The image label, with a rubber band for selecting a region.

Two jobs beyond painting a pixmap:

* **Map a widget click to an image pixel.** The pixmap is scaled to fit with
  `KeepAspectRatio` and centred, so one axis carries a letterbox offset. Getting
  this wrong puts the selection somewhere other than where it was drawn, which is
  the kind of bug that looks like an off-by-a-bit rather than an error — hence
  `_demo` below.
* **Drag out a rectangle**, using `QRubberBand` rather than custom painting.

Selection is armed, not always-on: a click is otherwise indistinguishable from a
click meant for anything else, and an accidental drag would silently re-crop the
analysis.
"""

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QRubberBand, QSizePolicy


class Viewer(QLabel):
    """Shows frames, and can have a rectangle dragged on it."""

    selected = pyqtSignal(int, int, int, int)  # x, y, w, h in *image* pixels
    # Double-clicking the empty placeholder is the obvious thing to try when the
    # window opens with nothing in it; only fires while there is no source, so it
    # cannot throw away a loaded frame by accident.
    open_requested = pyqtSignal()

    def __init__(self):
        super().__init__(
            "Double-click here to open a video or image\nCtrl+O / dataset folder Ctrl+Shift+O"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.source_size = QSize(0, 0)  # frame pixels, set by the window
        self._arming = False
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin = QPoint()

    # --- painting -----------------------------------------------------------

    def show_image(self, image: QImage) -> None:
        self.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # --- selecting ----------------------------------------------------------

    def arm(self, on: bool = True) -> None:
        """Next drag draws a rectangle. Disarms itself once one is drawn."""
        self._arming = on and not self.source_size.isEmpty()
        self.setCursor(
            Qt.CursorShape.CrossCursor if self._arming else Qt.CursorShape.ArrowCursor
        )

    @property
    def armed(self) -> bool:
        return self._arming

    def to_image(self, point: QPoint) -> QPoint:
        """Widget coordinates -> image pixel, clamped to the image.

        Clamped rather than rejected: a drag that runs off the edge of the widget
        is a perfectly clear "select out to the border", and refusing it would
        make the corners of the image hard to reach.
        """
        iw, ih = self.source_size.width(), self.source_size.height()
        if iw <= 0 or ih <= 0:
            return QPoint(0, 0)
        scale = min(self.width() / iw, self.height() / ih)
        if scale <= 0:
            return QPoint(0, 0)
        ox = (self.width() - iw * scale) / 2
        oy = (self.height() - ih * scale) / 2
        x = int((point.x() - ox) / scale)
        y = int((point.y() - oy) / scale)
        return QPoint(min(max(0, x), iw - 1), min(max(0, y), ih - 1))

    def mousePressEvent(self, event) -> None:
        if not self._arming or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._origin = event.pos()
        self._band.setGeometry(QRect(self._origin, QSize()))
        self._band.show()

    def mouseDoubleClickEvent(self, event) -> None:
        if self.source_size.isEmpty() and event.button() == Qt.MouseButton.LeftButton:
            return self.open_requested.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._band.isVisible():
            self._band.setGeometry(QRect(self._origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event) -> None:
        if not self._band.isVisible():
            return super().mouseReleaseEvent(event)
        self._band.hide()
        self.arm(False)

        start, end = self.to_image(self._origin), self.to_image(event.pos())
        # normalized() so dragging up-left works as well as down-right.
        rect = QRect(start, end).normalized()
        self.selected.emit(rect.x(), rect.y(), rect.width() + 1, rect.height() + 1)


def _demo() -> None:
    """The mapping is the whole risk here: check both letterbox orientations."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    viewer = Viewer()
    # The layout minimum would silently clamp the resizes below and make every
    # expected number wrong; the mapping itself is what is under test here.
    viewer.setMinimumSize(0, 0)

    # Wide widget, 4:3 image -> bars on the left and right.
    viewer.resize(800, 300)
    viewer.source_size = QSize(400, 300)  # scale 1.0, ox = 200, oy = 0
    assert viewer.to_image(QPoint(200, 0)) == QPoint(0, 0), viewer.to_image(QPoint(200, 0))
    assert viewer.to_image(QPoint(300, 150)) == QPoint(100, 150)
    # Off the edges clamps into the image rather than going negative or over.
    assert viewer.to_image(QPoint(0, 0)) == QPoint(0, 0)
    assert viewer.to_image(QPoint(799, 299)) == QPoint(399, 299)

    # Tall widget, same image -> bars on the top and bottom, and a real scale.
    viewer.resize(400, 600)
    viewer.source_size = QSize(400, 300)  # scale 1.0, ox = 0, oy = 150
    assert viewer.to_image(QPoint(0, 150)) == QPoint(0, 0), viewer.to_image(QPoint(0, 150))
    assert viewer.to_image(QPoint(40, 190)) == QPoint(40, 40)

    # Scaled down by 2, letterboxed horizontally.
    viewer.resize(600, 150)
    viewer.source_size = QSize(400, 300)  # scale 0.5, ox = 200, oy = 0
    assert viewer.to_image(QPoint(200, 0)) == QPoint(0, 0)
    assert viewer.to_image(QPoint(300, 50)) == QPoint(200, 100)

    # Every corner of the widget maps inside the image, at any aspect.
    for w, h in ((800, 300), (400, 600), (600, 150), (137, 991)):
        viewer.resize(w, h)
        for px, py in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, h // 2)):
            got = viewer.to_image(QPoint(px, py))
            assert 0 <= got.x() < 400 and 0 <= got.y() < 300, (w, h, px, py, got)

    # No frame yet: must answer rather than divide by zero.
    viewer.source_size = QSize(0, 0)
    assert viewer.to_image(QPoint(10, 10)) == QPoint(0, 0)
    viewer.arm(True)
    assert not viewer.armed, "arming with no frame loaded should not take"

    # Double-click opens a file only while empty, never over a loaded frame.
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    asks = []
    viewer.open_requested.connect(lambda: asks.append(1))

    def double_click() -> None:
        viewer.mouseDoubleClickEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonDblClick,
                QPointF(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    double_click()
    assert asks == [1], "double-click on the empty placeholder should ask to open"
    viewer.source_size = QSize(400, 300)
    double_click()
    assert asks == [1], "double-click over a loaded frame should not open a dialog"

    print("viewer ok")
    del app


if __name__ == "__main__":
    _demo()
