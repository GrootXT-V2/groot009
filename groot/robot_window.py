"""The robot itself: a frameless, see-through, always-on-top Qt window.

Only the robot is drawn; everything around it is transparent, so it looks
like it's walking on your desktop.
"""

import math
import queue
import random
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QRectF, Qt

WHITE = "#f4f6f8"
SHADE = "#c9d1d9"
DARK = "#2b2f36"
EYE_DARK = "#0d1726"
EYE_COLORS = {  # glow color of the eyes for each mood
    "loading": "#7d8790",
    "idle": "#49b6ff",
    "listening": "#3ddc84",
    "thinking": "#f5b82e",
    "speaking": "#5ff0ff",
    "error": "#ff5c5c",
}


class RobotWindow(QtWidgets.QWidget):
    W, H = 240, 310
    TICK_MS = 40
    SPEED = 2.4  # pixels per tick while walking

    def __init__(self, name="Groot"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)  # see-through: only the robot shows
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(name)
        self.setFixedSize(self.W, self.H)

        self.name = name
        self.session = None
        self.state = "loading"
        self.caption = "Getting ready..."
        self.caption_until = float("inf")
        self.events = queue.Queue()

        # options from the right-click menu
        self.stay_still = False
        self.little_voice = False
        self.groot_mode = False

        # animation state
        self.t = 0.0
        now = time.monotonic()
        self.action = {"name": "rest", "start": now, "until": now + 2}
        self.next_blink = now + 3
        self.blink_until = 0.0
        self.look = (0.0, 0.0)
        self.mouth = [0.3] * 5
        self.pose = {}
        self.dragging = False
        self._press_pos = None

        area = QtGui.QGuiApplication.primaryScreen().availableGeometry()  # without menu bar and Dock
        self.area = area
        self.x = float(area.right() - self.W - 30)
        self.y = float(area.bottom() - self.H - 10)
        self.move(int(self.x), int(self.y))

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(self.TICK_MS)

    # ---- thread-safe updates (background threads put, the UI thread applies)

    def set_state(self, state: str) -> None:
        self.events.put(("state", state))

    def set_text(self, text: str, seconds: float = None) -> None:
        self.events.put(("text", (text, seconds)))

    def set_session(self, session) -> None:
        self.events.put(("session", session))

    # ---- mouse

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.globalPosition()
            self._press_pos = (pos.x(), pos.y(), self.x, self.y)
            self._moved = False

    def mouseMoveEvent(self, event):
        if self._press_pos is None:
            return
        pos = event.globalPosition()
        sx, sy, wx, wy = self._press_pos
        dx, dy = pos.x() - sx, pos.y() - sy
        if abs(dx) + abs(dy) > 4:
            self._moved = True
            self.dragging = True
        self.x, self.y = wx + dx, wy + dy
        self._place()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._press_pos is None:
            return
        self._press_pos = None
        self.dragging = False
        if self._moved:
            self._new_action("rest")
        else:
            self.toggle()

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Talk / Stop", self.toggle)
        menu.addSeparator()
        for label, attr in (("Stay still", "stay_still"), ("Little Groot voice", "little_voice"),
                            ('"I am Groot" mode', "groot_mode")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(getattr(self, attr))
            action.toggled.connect(lambda checked, a=attr: self._set_option(a, checked))
        menu.addSeparator()
        menu.addAction(f"Quit {self.name}", self.quit)
        menu.exec(event.globalPos())

    def _set_option(self, attr, value):
        setattr(self, attr, value)
        if self.session is not None:
            self.session.groot_mode = self.groot_mode
            self.session.speaker.tree_voice = self.little_voice

    def toggle(self):
        if self.session is not None:
            self.session.toggle()

    def quit(self):
        if self.session is not None:
            self.session.quit()
        QtWidgets.QApplication.quit()

    # ---- behaviour

    def _new_action(self, name=None):
        now = time.monotonic()
        if name is None:
            name = random.choices(["walk", "rest", "look", "wave", "jump", "dance"],
                                  weights=[40, 20, 15, 10, 10, 5])[0]
        action = {"name": name, "start": now}
        if name == "walk":
            a = self.area
            action["target"] = (random.uniform(a.left(), a.right() - self.W),
                                random.uniform(a.top(), a.bottom() - self.H))
            action["until"] = now + 20
        else:
            action["until"] = now + {"rest": random.uniform(2, 4), "look": 2.5, "wave": 2,
                                     "jump": 1.2, "dance": 3}[name]
        self.action = action

    def _place(self):
        a = self.area
        self.x = min(max(self.x, a.left()), a.right() - self.W)
        self.y = min(max(self.y, a.top()), a.bottom() - self.H)
        self.move(int(self.x), int(self.y))

    def _update_behaviour(self, now):
        """Move the robot and return its pose for this frame."""
        pose = {"bob": 0.0, "legs": 0.0, "left_arm": 115.0, "right_arm": 65.0, "lift": 0.0}
        awake = self.state not in ("idle", "loading", "error")

        if self.dragging:  # picked up: arms flail a little
            pose.update(left_arm=200 + 10 * math.sin(self.t * 6), right_arm=-20 - 10 * math.sin(self.t * 6))
            self.look = (0, -4)
            return pose

        if awake or self.stay_still:
            self.look = (self.look[0] * 0.8, self.look[1] * 0.8)
            if self.state == "thinking":
                self.look = (4 * math.sin(self.t * 1.5), -5)
                pose["right_arm"] = -40
            elif self.state == "speaking":
                pose["bob"] = 1.5 * math.sin(self.t * 8)
                pose["left_arm"] = 115 + 12 * math.sin(self.t * 3)
            elif self.state == "listening":
                pose["bob"] = math.sin(self.t * 2)
            return pose

        name = self.action["name"]
        elapsed = now - self.action["start"]
        if now > self.action["until"]:
            self._new_action()
        elif name == "walk":
            tx, ty = self.action["target"]
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            if dist < self.SPEED:
                self._new_action("rest")
            else:
                self.x += self.SPEED * dx / dist
                self.y += self.SPEED * dy / dist
                self._place()
                self.look = (5 * max(-1.0, min(1.0, dx / 60)), 0)
                pose["legs"] = math.sin(self.t * 10)
                pose["bob"] = -3 * abs(math.sin(self.t * 10))
                pose["left_arm"] = 115 + 15 * math.sin(self.t * 10)
                pose["right_arm"] = 65 + 15 * math.sin(self.t * 10)
        elif name == "look":
            self.look = (6 * math.sin(elapsed * 2.5), 0)
        elif name == "wave":
            pose["right_arm"] = -55 + 25 * math.sin(elapsed * 10)
            self.look = (0, 0)
        elif name == "jump":
            pose["lift"] = 25 * max(0.0, math.sin(elapsed * math.pi / 0.6))
            pose["left_arm"] = 160
            pose["right_arm"] = 20
        elif name == "dance":
            pose["bob"] = 4 * math.sin(elapsed * 9)
            pose["left_arm"] = 150 + 40 * math.sin(elapsed * 9)
            pose["right_arm"] = 30 - 40 * math.sin(elapsed * 9)
            pose["legs"] = 0.5 * math.sin(elapsed * 9)
        else:  # rest
            self.look = (self.look[0] * 0.9, self.look[1] * 0.9)
        return pose

    def _tick(self):
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "state":
                self.state = value
            elif kind == "text":
                text, seconds = value
                self.caption = text
                self.caption_until = time.monotonic() + seconds if seconds else float("inf")
            elif kind == "session":
                self.session = value
                self.little_voice = value.speaker.tree_voice
                self.groot_mode = value.groot_mode

        now = time.monotonic()
        self.t += self.TICK_MS / 1000
        if now > self.next_blink:
            self.blink_until = now + 0.15
            self.next_blink = now + random.uniform(2.5, 6)
        self.pose = self._update_behaviour(now)
        if self.state == "speaking":
            self.mouth = [max(0.15, min(1.0, m + random.uniform(-0.35, 0.35))) for m in self.mouth]
        self.update()  # repaint

    # ---- drawing

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)  # clear the last frame completely
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        if self.pose:
            self._draw_robot(p, time.monotonic())
            self._draw_caption(p, time.monotonic())
        p.end()

    @staticmethod
    def _pen(color=None, width=0):
        if color is None:
            return QtGui.QPen(Qt.NoPen)
        pen = QtGui.QPen(QtGui.QColor(color), width)
        pen.setCapStyle(Qt.RoundCap)
        return pen

    def _rrect(self, p, x1, y1, x2, y2, r, fill, outline=None, width=0):
        p.setPen(self._pen(outline, width))
        p.setBrush(QtGui.QColor(fill))
        p.drawRoundedRect(QRectF(x1, y1, x2 - x1, y2 - y1), r, r)

    def _oval(self, p, x1, y1, x2, y2, fill=None, outline=None, width=0):
        p.setPen(self._pen(outline, width))
        p.setBrush(QtGui.QColor(fill) if fill else Qt.NoBrush)
        p.drawEllipse(QRectF(x1, y1, x2 - x1, y2 - y1))

    def _line(self, p, x1, y1, x2, y2, color, width):
        p.setPen(self._pen(color, width))
        p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))

    def _draw_robot(self, p, now):
        pose = self.pose
        cx = self.W / 2
        oy = pose["bob"] - pose["lift"]  # vertical offset of the whole robot
        glow = EYE_COLORS.get(self.state, EYE_COLORS["idle"])

        # legs and feet
        for side, phase in ((-1, pose["legs"]), (1, -pose["legs"])):
            lx = cx + side * 18
            up = 0 if self.dragging else max(0.0, phase) * 7
            self._rrect(p, lx - 10, 248 + oy - up, lx + 10, 284 + oy - up, 8, WHITE, SHADE, 2)
            self._line(p, lx - 7, 268 + oy - up, lx + 7, 268 + oy - up, "#e0b84a", 2)
            self._rrect(p, lx - 15, 280 + oy - up, lx + 15, 298 + oy - up, 8, DARK)

        # arms (behind the body)
        for shoulder_x, angle in ((cx - 36, pose["left_arm"]), (cx + 36, pose["right_arm"])):
            sy = 212 + oy
            rad = math.radians(angle)
            hx, hy = shoulder_x + 38 * math.cos(rad), sy + 38 * math.sin(rad)
            self._line(p, shoulder_x, sy, hx, hy, SHADE, 17)
            self._line(p, shoulder_x, sy, hx, hy, WHITE, 13)
            self._oval(p, shoulder_x - 8, sy - 8, shoulder_x + 8, sy + 8, DARK)
            self._oval(p, hx - 9, hy - 9, hx + 9, hy + 9, DARK)

        # body
        self._rrect(p, cx - 14, 188 + oy, cx + 14, 202 + oy, 2, DARK)  # neck
        self._rrect(p, cx - 38, 196 + oy, cx + 38, 256 + oy, 24, WHITE, SHADE, 2)
        p.setPen(self._pen(SHADE, 2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - 24, 214 + oy, 48, 34), 200 * 16, 140 * 16)  # belly smile
        d, ly = 5, 214 + oy  # little chest light
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(glow if self.state == "speaking" else "#f0a030"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx, ly - d), QtCore.QPointF(cx + d, ly),
                                       QtCore.QPointF(cx, ly + d), QtCore.QPointF(cx - d, ly)]))

        # head
        for side in (-1, 1):  # headphones
            hx = cx + side * 70
            self._rrect(p, hx - 10, 124 + oy, hx + 10, 174 + oy, 9, DARK)
        self._rrect(p, cx - 66, 98 + oy, cx + 66, 196 + oy, 42, WHITE, SHADE, 2)
        for side in (-1, 1):  # light strip on the headphones
            hx = cx + side * 74
            self._line(p, hx, 134 + oy, hx, 164 + oy, glow, 2)
        self._rrect(p, cx - 30, 110 + oy, cx + 30, 117 + oy, 3, DARK)  # forehead slit

        # eyes
        resting = self.state == "idle" and self.action["name"] == "rest" and not self.dragging
        if now < self.blink_until:
            open_amount = 0.1
        elif self.dragging:
            open_amount = 1.15  # surprised!
        elif resting:
            open_amount = 0.75  # a bit sleepy
        else:
            open_amount = 1.0
        look_x, look_y = self.look
        for side in (-1, 1):
            ex, ey = cx + side * 30, 148 + oy
            if open_amount < 0.2:
                self._line(p, ex - 18, ey, ex + 18, ey, EYE_DARK, 4)
                continue
            ry = 23 * open_amount
            self._oval(p, ex - 25, ey - ry - 2, ex + 25, ey + ry + 2, glow)
            self._oval(p, ex - 20, ey - ry + 3, ex + 20, ey + ry - 3, EYE_DARK)
            px, py = ex + look_x, ey + look_y * open_amount
            self._oval(p, px - 13, py - 13 * open_amount, px + 13, py + 13 * open_amount, None, glow, 2)
            self._oval(p, px - 10, py - 10 * open_amount, px + 10, py + 10 * open_amount, "#000000")
            self._oval(p, px - 6, py - 7, px - 1, py - 2, "#ffffff")

        # mouth: a little light bar that moves when speaking
        my = 180 + oy
        if self.state == "speaking":
            for i, level in enumerate(self.mouth):
                bx = cx - 12 + i * 6
                self._line(p, bx, my - 5 * level, bx, my + 5 * level, glow, 3)
        else:
            self._rrect(p, cx - 8, my - 2, cx + 8, my + 2, 2, DARK)

        # sleepy zzz while resting
        if resting:
            z = (now * 0.8) % 1
            font = QtGui.QFont("Helvetica", int(10 + 6 * z))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QtGui.QColor("#8fa3b5"))
            p.drawText(QtCore.QPointF(cx + 52, 98 + oy - 20 * z), "z")

    def _draw_caption(self, p, now):
        if not self.caption or now > self.caption_until:
            return
        caption = self.caption if len(self.caption) <= 110 else self.caption[:107] + "..."
        font = QtGui.QFont("Helvetica", 12)
        p.setFont(font)
        flags = Qt.TextWordWrap | Qt.AlignCenter
        text_rect = QtGui.QFontMetrics(font).boundingRect(QtCore.QRect(0, 0, self.W - 40, 200), flags, caption)
        cx = self.W / 2
        bottom = 82
        rect = QRectF(cx - text_rect.width() / 2 - 10, bottom - text_rect.height() - 14,
                      text_rect.width() + 20, text_rect.height() + 14)
        self._rrect(p, rect.left(), rect.top(), rect.right(), rect.bottom(), 12, "#ffffff", SHADE, 1)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx - 8, bottom - 1), QtCore.QPointF(cx + 8, bottom - 1),
                                       QtCore.QPointF(cx, bottom + 10)]))
        p.setPen(QtGui.QColor("#1d232b"))
        p.drawText(rect, flags, caption)
