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


# The robot is designed on a 240 x 310 grid; this part of it holds the robot
DESIGN_LEFT, DESIGN_TOP, DESIGN_W, DESIGN_H = 20, 70, 200, 232


class RobotWindow(QtWidgets.QWidget):
    CAPTION_H = 64  # room above the robot for its speech bubble
    TICK_MS = 33
    GRAVITY = 1.2

    def __init__(self, name="Groot", size=0.6):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)  # see-through: only the robot shows
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(name)
        self.scale = size
        self.W = int(max(DESIGN_W * size, 190))
        self.H = int(self.CAPTION_H + DESIGN_H * size)
        self.speed = 1.6 * max(size, 0.4)  # walking speed in pixels per frame
        self.setFixedSize(self.W, self.H)

        self.name = name
        self.session = None
        self.watcher = None  # reads new notifications aloud (Mac)
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
        self.step = 0.0  # walking cycle
        self.turn = 0.0  # -1 facing left, 0 facing you, 1 facing right
        self.fall_speed = 0.0

        area = QtGui.QGuiApplication.primaryScreen().availableGeometry()  # without menu bar and Dock
        self.area = area
        self.floor = float(area.bottom() - self.H + 1)  # Groot walks along the bottom of the screen
        self.x = float(area.right() - self.W - 30)
        self.y = self.floor
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

    def set_watcher(self, watcher) -> None:
        self.events.put(("watcher", watcher))

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
            self.fall_speed = 0.0  # let go: Groot falls back down to the floor
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
        if self.watcher is not None:
            action = menu.addAction("Read notifications aloud")
            action.setCheckable(True)
            action.setChecked(self.watcher.enabled)
            action.toggled.connect(lambda checked: setattr(self.watcher, "enabled", checked))
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
            distance = random.uniform(120, 500) * random.choice((-1, 1))
            target = min(max(self.x + distance, a.left()), a.right() - self.W)
            if abs(target - self.x) < 60:  # at an edge: walk the other way
                target = min(max(self.x - distance, a.left()), a.right() - self.W)
            action["target"] = target
            action["until"] = now + 30
        else:
            action["until"] = now + {"rest": random.uniform(2, 4), "look": 2.5, "wave": 2,
                                     "jump": 1.2, "dance": 3}[name]
        self.action = action

    def _place(self):
        a = self.area
        self.x = min(max(self.x, a.left()), a.right() - self.W)
        self.y = min(max(self.y, a.top()), self.floor)
        self.move(int(self.x), int(self.y))

    def _update_behaviour(self, now):
        """Move the robot and return its pose for this frame."""
        pose = {"bob": 0.0, "legs": 0.0, "left_arm": 112.0, "right_arm": 68.0, "lift": 0.0, "lean": 0.0}
        awake = self.state not in ("idle", "loading", "error")
        facing = 0.0

        if self.dragging:  # picked up: legs dangle, arms flail a little
            pose.update(left_arm=200 + 10 * math.sin(self.t * 6), right_arm=-20 - 10 * math.sin(self.t * 6))
            self.look = (0, -4)
            self.turn *= 0.8
            return pose

        if self.y < self.floor - 0.5:  # falling back down after being dropped
            self.fall_speed += self.GRAVITY
            self.y = min(self.floor, self.y + self.fall_speed)
            self._place()
            pose.update(left_arm=160, right_arm=20)
            self.look = (0, -3)
            return pose
        if self.fall_speed > 0:  # just landed: a little squash
            self.fall_speed = 0.0
            self._new_action("rest")

        if awake or self.stay_still:
            self.look = (self.look[0] * 0.8, self.look[1] * 0.8)
            if self.state == "thinking":
                self.look = (4 * math.sin(self.t * 1.5), -5)
                pose["right_arm"] = -40
            elif self.state == "speaking":
                pose["bob"] = 1.2 * math.sin(self.t * 8)
                pose["left_arm"] = 112 + 10 * math.sin(self.t * 3)
            elif self.state == "listening":
                pose["bob"] = math.sin(self.t * 2)
        else:
            name = self.action["name"]
            elapsed = now - self.action["start"]
            if now > self.action["until"]:
                self._new_action()
            elif name == "walk":
                dx = self.action["target"] - self.x
                if abs(dx) < self.speed:
                    self._new_action("rest")
                else:
                    direction = 1 if dx > 0 else -1
                    # ease in for the first half second so it doesn't start abruptly
                    speed = self.speed * min(1.0, elapsed / 0.5)
                    self.x += direction * speed
                    self._place()
                    self.step += speed * 0.12 / max(self.scale, 0.4)
                    facing = direction
                    swing = math.sin(self.step)
                    pose["legs"] = swing
                    pose["bob"] = -2.5 * abs(swing)  # up on each step
                    pose["lean"] = 4 * direction
                    pose["left_arm"] = 112 - 14 * swing
                    pose["right_arm"] = 68 - 14 * swing
                    self.look = (4 * direction, 0)
            elif name == "look":
                self.look = (6 * math.sin(elapsed * 2.5), 0)
            elif name == "wave":
                pose["right_arm"] = -55 + 25 * math.sin(elapsed * 10)
                self.look = (0, 0)
            elif name == "jump":
                pose["lift"] = 22 * max(0.0, math.sin(elapsed * math.pi / 0.6))
                pose["left_arm"] = 160
                pose["right_arm"] = 20
            elif name == "dance":
                pose["bob"] = 3 * math.sin(elapsed * 9)
                pose["left_arm"] = 150 + 35 * math.sin(elapsed * 9)
                pose["right_arm"] = 30 - 35 * math.sin(elapsed * 9)
                pose["lean"] = 5 * math.sin(elapsed * 4.5)
            else:  # rest
                self.look = (self.look[0] * 0.9, self.look[1] * 0.9)

        self.turn += (facing - self.turn) * 0.15  # turn smoothly toward where it's going
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
            elif kind == "watcher":
                self.watcher = value
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
            now = time.monotonic()
            p.save()
            # robot coordinates are on a 240 x 310 grid; scale them into the window
            p.translate(self.W / 2 - (DESIGN_LEFT + DESIGN_W / 2) * self.scale,
                        self.CAPTION_H - DESIGN_TOP * self.scale)
            p.scale(self.scale, self.scale)
            lean = self.pose.get("lean", 0.0)
            if lean:  # tilt the whole robot around its feet
                p.translate(120, 298)
                p.rotate(lean)
                p.translate(-120, -298)
            self._draw_robot(p, now)
            p.restore()
            self._draw_caption(p, now)
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

        turn = self.turn  # face and feet shift toward where Groot is walking

        # legs and feet: each step lifts one foot and moves it forward
        for side, phase in ((-1, pose["legs"]), (1, -pose["legs"])):
            lx = cx + side * 17 + turn * 6 * phase
            up = 0 if self.dragging else max(0.0, phase) * 8
            dangle = 6 if self.dragging else 0
            top = 248 + oy
            foot = 280 + oy - up + dangle
            self._rrect(p, lx - 10, top, lx + 10, foot + 4, 8, WHITE, SHADE, 2)
            self._line(p, lx - 7, (top + foot) / 2 + 2, lx + 7, (top + foot) / 2 + 2, "#e0b84a", 2)
            toe = turn * 5
            self._rrect(p, lx - 15 + toe, foot, lx + 15 + toe, foot + 18, 8, DARK)

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

        # head (the face slides sideways a little when Groot turns)
        fx = turn * 9
        for side in (-1, 1):  # headphones: the one on the far side tucks behind the head
            hx = cx + side * 70 - turn * 6 + (side * turn > 0) * side * -4
            self._rrect(p, hx - 10, 124 + oy, hx + 10, 174 + oy, 9, DARK)
        self._rrect(p, cx - 66, 98 + oy, cx + 66, 196 + oy, 42, WHITE, SHADE, 2)
        for side in (-1, 1):  # light strip on the headphones
            if side * turn > 0.5:
                continue
            hx = cx + side * 74 - turn * 6
            self._line(p, hx, 134 + oy, hx, 164 + oy, glow, 2)
        self._rrect(p, cx - 30 + fx, 110 + oy, cx + 30 + fx, 117 + oy, 3, DARK)  # forehead slit

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
            ex, ey = cx + side * 30 + fx, 148 + oy
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
                bx = cx - 12 + i * 6 + fx
                self._line(p, bx, my - 5 * level, bx, my + 5 * level, glow, 3)
        else:
            self._rrect(p, cx - 8 + fx, my - 2, cx + 8 + fx, my + 2, 2, DARK)

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
        font = QtGui.QFont("Helvetica", 11)
        p.setFont(font)
        flags = Qt.TextWordWrap | Qt.AlignCenter
        text_rect = QtGui.QFontMetrics(font).boundingRect(QtCore.QRect(0, 0, self.W - 24, 200), flags, caption)
        cx = self.W / 2
        head_top = self.CAPTION_H + (98 - DESIGN_TOP) * self.scale
        tip = head_top - 2
        bottom = tip - 8
        height = min(text_rect.height() + 12, bottom - 1)
        rect = QRectF(cx - text_rect.width() / 2 - 8, bottom - height, text_rect.width() + 16, height)
        self._rrect(p, rect.left(), rect.top(), rect.right(), rect.bottom(), 10, "#ffffff", SHADE, 1)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx - 6, bottom - 1), QtCore.QPointF(cx + 6, bottom - 1),
                                       QtCore.QPointF(cx, tip)]))
        p.setPen(QtGui.QColor("#1d232b"))
        p.drawText(rect, flags, caption)
