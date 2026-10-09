"""The buddy's window on Windows and Linux (Qt / PySide6)."""

import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QRectF, Qt

from .buddy import Area, Buddy, Canvas, rgba

TEXT_FLAGS = Qt.TextWordWrap | Qt.AlignCenter


class QtCanvas(Canvas):
    def __init__(self, painter: QtGui.QPainter):
        self.p = painter

    @staticmethod
    def _color(color):
        return QtGui.QColor.fromRgbF(*rgba(color))

    @staticmethod
    def _path(shape):
        path = QtGui.QPainterPath()
        for cmd in shape.cmds:
            if cmd[0] == "M":
                path.moveTo(cmd[1], cmd[2])
            elif cmd[0] == "L":
                path.lineTo(cmd[1], cmd[2])
            elif cmd[0] == "C":
                path.cubicTo(*cmd[1:])
            else:
                path.closeSubpath()
        return path

    def _font(self, size, bold=False):
        font = QtGui.QFont("Helvetica")
        font.setPointSizeF(size)
        font.setBold(bold)
        return font

    def save(self):
        self.p.save()

    def restore(self):
        self.p.restore()

    def translate(self, dx, dy):
        self.p.translate(dx, dy)

    def rotate(self, degrees):
        self.p.rotate(degrees)

    def scale(self, factor):
        self.p.scale(factor, factor)

    def fill_stroke(self, shape, fill=None, outline=None, width=0):
        if outline:
            pen = QtGui.QPen(self._color(outline), width)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            self.p.setPen(pen)
        else:
            self.p.setPen(Qt.NoPen)
        self.p.setBrush(self._color(fill) if fill else Qt.NoBrush)
        self.p.drawPath(self._path(shape))

    def clip(self, shape):
        self.p.setClipPath(self._path(shape), Qt.IntersectClip)

    def fill_rect(self, x, y, w, h, color):
        self.p.fillRect(QRectF(x, y, w, h), self._color(color))

    def text(self, x, y, text, size, color, bold=False):
        font = self._font(size, bold)
        self.p.setFont(font)
        self.p.setPen(self._color(color))
        self.p.drawText(QtCore.QPointF(x, y + QtGui.QFontMetricsF(font).ascent()), text)

    def measure(self, text, size, max_width):
        rect = QtGui.QFontMetrics(self._font(size)).boundingRect(
            QtCore.QRect(0, 0, int(max_width), 1000), TEXT_FLAGS, text)
        return rect.width(), rect.height()

    def text_box(self, x, y, w, h, text, size, color):
        self.p.setFont(self._font(size))
        self.p.setPen(self._color(color))
        self.p.drawText(QRectF(x, y, w, h), TEXT_FLAGS, text)


class QtPropWindow(QtWidgets.QWidget):
    """A tiny see-through window for a toy (ball, butterfly); clicks pass through it."""

    def __init__(self, prop):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
                         | Qt.WindowTransparentForInput | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(prop.W, prop.H)
        self.prop = prop
        self.move(int(prop.x), int(prop.y))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        self.prop.draw(QtCanvas(p))
        p.end()


class QtBuddyWindow(QtWidgets.QWidget):
    def __init__(self, buddy: Buddy):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)  # see-through: only the buddy shows
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(buddy.name)
        self.setFixedSize(buddy.W, buddy.H)
        self.buddy = buddy
        self.move(int(buddy.x), int(buddy.y))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(Buddy.FRAME * 1000))

    def _tick(self):
        self.buddy.tick()
        self.move(int(self.buddy.x), int(self.buddy.y))
        self.update()
        self._sync_props()

    def _sync_props(self):
        """Open, move and close the little windows for the toys on screen."""
        if not hasattr(self, "prop_windows"):
            self.prop_windows = {}
        for prop in list(self.prop_windows):
            if prop not in self.buddy.props:
                self.prop_windows.pop(prop).close()
        for prop in self.buddy.props:
            window = self.prop_windows.get(prop)
            if window is None:
                window = self.prop_windows[prop] = QtPropWindow(prop)
                window.show()
            window.move(int(prop.x), int(prop.y))
            window.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)  # clear the last frame completely
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        self.buddy.draw(QtCanvas(p), time.monotonic())
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.globalPosition()
            self.buddy.press(pos.x(), pos.y())

    def mouseMoveEvent(self, event):
        pos = event.globalPosition()
        self.buddy.drag(pos.x(), pos.y())
        self.move(int(self.buddy.x), int(self.buddy.y))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.buddy.release()

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)
        for item in self.buddy.menu_items():
            if item is None:
                menu.addSeparator()
                continue
            label, checked, callback = item
            action = menu.addAction(label)
            if checked is None:
                action.triggered.connect(lambda _=False, cb=callback: cb())
            else:
                action.setCheckable(True)
                action.setChecked(checked)
                action.toggled.connect(callback)
        menu.exec(event.globalPos())


class QtHost:
    """Creates the Qt app; the same small interface as the Mac host."""

    def __init__(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        g = QtGui.QGuiApplication.primaryScreen().availableGeometry()  # without taskbar
        self.area = Area(g.x(), g.y(), g.x() + g.width(), g.y() + g.height())
        self.window = None

    def show(self, buddy: Buddy):
        buddy.on_quit = self.quit
        self.window = QtBuddyWindow(buddy)
        self.window.show()

    def run(self):
        self.app.exec()

    def quit(self):
        self.app.quit()
