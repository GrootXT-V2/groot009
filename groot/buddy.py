"""Groot the desktop buddy: how it behaves and how it's drawn.

This file doesn't depend on any window system. A window (native AppKit on
Mac, Qt elsewhere) calls tick() about 30 times a second, moves itself to
(buddy.x, buddy.y), and asks the buddy to draw() itself on a Canvas.
"""

import math
import queue
import random
import time
from pathlib import Path
from collections import namedtuple

# The part of the screen the buddy may use, in top-left-origin screen coordinates
Area = namedtuple("Area", "left top right bottom")

# The character is designed on a 240 x 310 grid; this part of it holds the character
DESIGN_LEFT, DESIGN_TOP, DESIGN_W, DESIGN_H = 20, 70, 200, 232
CX = 120  # horizontal center of the design grid

# Tree creature colors
BARK = "#b9693e"
BARK_LIGHT = "#d9915f"
BARK_DARK = "#7f4426"
VINE = "#55b83f"
VINE_DARK = "#3b8a2c"
LEAF_COLORS = {  # the leaves change color with Groot's mood
    "loading": "#8fa07e",
    "idle": "#63c24a",
    "listening": "#3ee86f",
    "thinking": "#f0b232",
    "speaking": "#63c24a",
    "error": "#c65a3a",
}

# Fox colors
FUR = "#f0832f"
FUR_LIGHT = "#ffa45a"
FUR_LINE = "#a24a12"
CREAM = "#fff3e3"
SOCK = "#3a2a26"
EAR_INSIDE = "#ffd0b8"
FOX_GLOW = {"listening": "#3ee86f", "thinking": "#f5c542"}

# Elegant flat-style fox colors
FOX_ORANGE = "#dc7435"
FOX_SHADE = "#c96128"
FOX_RUST = "#c0452c"
FOX_CREAM = "#f7f0df"
FOX_LEG = "#2a1a14"
FOX_SOCK = "#5a4b44"  # walking fox's dark grey-brown socks

# Realistic red fox colors
RF_BACK = "#9f4318"      # darker rust along the back
RF_SIDE = "#c9662b"      # rich orange sides
RF_LIGHT = "#e2924f"     # lighter flanks and cheeks
RF_WHITE = "#f4eee5"     # throat, chest, belly, tail tip
RF_GREY = "#b9aca0"      # greyish underside of the tail
RF_BLACK = "#231a16"     # leg "stockings", ear backs, nose
RF_EYE = "#d99a2b"       # amber eyes

# The atlas is packed into padded cells with identical nose, ear and paw anchors.
FOX_SPRITE_GROUNDS = (456 / 512,) * 16

# Robot colors
WHITE = "#f4f6f8"
SHADE = "#c9d1d9"
DARK = "#2b2f36"
EYE_DARK = "#0d1726"
EYE_COLORS = {
    "loading": "#7d8790",
    "idle": "#49b6ff",
    "listening": "#3ddc84",
    "thinking": "#f5b82e",
    "speaking": "#5ff0ff",
    "error": "#ff5c5c",
}


# ------------------------------------------------------------------ drawing

def rgba(color):
    """'#rrggbb' or ('#rrggbb', alpha) -> (r, g, b, a) floats from 0 to 1."""
    alpha = 1.0
    if isinstance(color, tuple):
        color, alpha = color
    color = color.lstrip("#")
    return (int(color[0:2], 16) / 255, int(color[2:4], 16) / 255, int(color[4:6], 16) / 255, alpha)


def darker(color: str, factor: float = 1.3) -> str:
    r, g, b, _ = rgba(color)
    return "#%02x%02x%02x" % tuple(int(v * 255 / factor) for v in (r, g, b))


class Shape:
    """A path made of straight lines and curves (quadratic curves become cubic)."""

    def __init__(self, x, y):
        self.cmds = [("M", x, y)]
        self.last = (x, y)

    def line(self, x, y):
        self.cmds.append(("L", x, y))
        self.last = (x, y)
        return self

    def cubic(self, c1x, c1y, c2x, c2y, x, y):
        self.cmds.append(("C", c1x, c1y, c2x, c2y, x, y))
        self.last = (x, y)
        return self

    def quad(self, cx, cy, x, y):
        x0, y0 = self.last
        return self.cubic(x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0),
                          x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y), x, y)

    def close(self):
        self.cmds.append(("Z",))
        return self


KAPPA = 0.5523  # for drawing circles with cubic curves


def oval_shape(x1, y1, x2, y2):
    cx, cy, rx, ry = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2, (y2 - y1) / 2
    kx, ky = rx * KAPPA, ry * KAPPA
    return (Shape(cx + rx, cy)
            .cubic(cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry)
            .cubic(cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy)
            .cubic(cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry)
            .cubic(cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy).close())


def rounded_rect_shape(x1, y1, x2, y2, r):
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    k = r * (1 - KAPPA)
    return (Shape(x1 + r, y1).line(x2 - r, y1)
            .cubic(x2 - k, y1, x2, y1 + k, x2, y1 + r).line(x2, y2 - r)
            .cubic(x2, y2 - k, x2 - k, y2, x2 - r, y2).line(x1 + r, y2)
            .cubic(x1 + k, y2, x1, y2 - k, x1, y2 - r).line(x1, y1 + r)
            .cubic(x1, y1 + k, x1 + k, y1, x1 + r, y1).close())


class Canvas:
    """Drawing commands. A window system provides the few primitives at the bottom."""

    def rrect(self, x1, y1, x2, y2, r, fill, outline=None, width=0):
        self.fill_stroke(rounded_rect_shape(x1, y1, x2, y2, r), fill, outline, width)

    def sprite(self, path, frame, columns, rows, x, y, w, h, opacity=1.0):
        """Draw one atlas cell. Return False when raster drawing is unavailable."""
        return False

    def oval(self, x1, y1, x2, y2, fill=None, outline=None, width=0):
        self.fill_stroke(oval_shape(x1, y1, x2, y2), fill, outline, width)

    def line(self, x1, y1, x2, y2, color, width):
        self.fill_stroke(Shape(x1, y1).line(x2, y2), None, color, width)

    def polygon(self, points, fill):
        shape = Shape(*points[0])
        for point in points[1:]:
            shape.line(*point)
        self.fill_stroke(shape.close(), fill)

    def arc(self, x1, y1, x2, y2, start, extent, color, width):
        """Part of an ellipse; angles in degrees, counter-clockwise from 3 o'clock."""
        cx, cy, rx, ry = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2, (y2 - y1) / 2
        steps = 16
        points = [(cx + rx * math.cos(math.radians(start + extent * i / steps)),
                   cy - ry * math.sin(math.radians(start + extent * i / steps))) for i in range(steps + 1)]
        shape = Shape(*points[0])
        for point in points[1:]:
            shape.line(*point)
        self.fill_stroke(shape, None, color, width)

    def gradient(self, shape, start, end, stops, outline=None, width=0):
        """Fill a shape with a straight (horizontal or vertical) color gradient."""
        (x1, y1), (x2, y2) = start, end
        vertical = abs(y2 - y1) > abs(x2 - x1)
        a, b = (y1, y2) if vertical else (x1, x2)
        bands = 40
        self.save()
        self.clip(shape)
        for i in range(bands):
            pos = (i + 0.5) / bands
            color = _gradient_color(stops, pos)
            lo = a + (b - a) * i / bands
            hi = a + (b - a) * (i + 1) / bands + 0.6  # overlap a little so there are no gaps
            if vertical:
                self.fill_rect(-1000, lo, 3000, hi - lo, color)
            else:
                self.fill_rect(lo, -1000, hi - lo, 3000, color)
        self.restore()
        if outline:
            self.fill_stroke(shape, None, outline, width)

    # primitives a window system must provide
    def save(self): raise NotImplementedError
    def restore(self): raise NotImplementedError
    def translate(self, dx, dy): raise NotImplementedError
    def rotate(self, degrees): raise NotImplementedError
    def scale(self, factor): raise NotImplementedError
    def scale_xy(self, sx, sy): raise NotImplementedError  # e.g. (-1, 1) mirrors left-right
    def fill_stroke(self, shape, fill=None, outline=None, width=0): raise NotImplementedError
    def clip(self, shape): raise NotImplementedError
    def fill_rect(self, x, y, w, h, color): raise NotImplementedError
    def text(self, x, y, text, size, color, bold=False): raise NotImplementedError  # (x, y) = top-left
    def measure(self, text, size, max_width): raise NotImplementedError  # -> (width, height)
    def text_box(self, x, y, w, h, text, size, color): raise NotImplementedError  # wrapped and centered


def _gradient_color(stops, pos):
    for (p1, c1), (p2, c2) in zip(stops, stops[1:]):
        if p1 <= pos <= p2:
            t = (pos - p1) / (p2 - p1) if p2 > p1 else 0
            a, b = rgba(c1), rgba(c2)
            return "#%02x%02x%02x" % tuple(int((a[i] + (b[i] - a[i]) * t) * 255) for i in range(3))
    return stops[-1][1]


# ------------------------------------------------------------------ the buddy


# How long each on-screen activity lasts, in seconds
ACTIVITIES = {"football": 30, "butterfly": 25, "dance": 8, "jump": 4, "wave": 4, "sleep": 45, "run": 12}


class Prop:
    """A toy that moves around the screen in its own little window (a ball, a butterfly)."""

    def __init__(self, kind, cx, cy, radius):
        self.kind = kind
        self.cx, self.cy = cx, cy  # center, in screen coordinates
        self.r = radius
        self.W = self.H = int(radius * 2 + 10)
        self.vx = self.vy = 0.0
        self.angle = 0.0  # how far the ball has rolled, in degrees
        self.t = 0.0

    @property
    def x(self):
        return self.cx - self.W / 2

    @property
    def y(self):
        return self.cy - self.H / 2

    def draw(self, c: "Canvas", now=None):
        c.save()
        c.translate(self.W / 2, self.H / 2)
        if self.kind == "ball":
            self._draw_ball(c)
        else:
            self._draw_butterfly(c)
        c.restore()

    def _draw_ball(self, c):
        r = self.r
        c.rotate(self.angle)
        c.oval(-r, -r, r, r, "#ffffff")
        c.save()
        c.clip(oval_shape(-r, -r, r, r))
        c.polygon(_pentagon(0, 0, r * 0.36, -90), "#22262c")
        for k in range(5):  # patches around the edge
            a = math.radians(-54 + 72 * k)
            c.polygon(_pentagon(r * 0.92 * math.cos(a), r * 0.92 * math.sin(a), r * 0.3, -54 + 72 * k + 180),
                      "#22262c")
            seam_a = math.radians(-90 + 72 * k)
            c.line(r * 0.36 * math.cos(seam_a), r * 0.36 * math.sin(seam_a),
                   r * 0.7 * math.cos(seam_a), r * 0.7 * math.sin(seam_a), "#9aa3ad", 1)
        c.restore()
        c.oval(-r, -r, r, r, None, "#2b2f36", 1.5)

    def _draw_butterfly(self, c):
        flap = 0.25 + 0.75 * abs(math.sin(self.t * 14))
        s = self.r / 14
        for side in (-1, 1):
            c.oval(side * 1, -12 * s, side * (1 + 13 * flap * s), 1 * s, "#ff8fb8", "#c24d7a", 1)
            c.oval(side * 1, -1 * s, side * (1 + 9 * flap * s), 9 * s, "#ffc75f", "#c2852d", 1)
        c.rrect(-1.6 * s, -9 * s, 1.6 * s, 9 * s, 1.6 * s, "#3a2a24")
        c.line(0, -9 * s, -4 * s, -15 * s, "#3a2a24", 1)
        c.line(0, -9 * s, 4 * s, -15 * s, "#3a2a24", 1)


def _pentagon(cx, cy, r, rotation):
    return [(cx + r * math.cos(math.radians(rotation + 72 * i)), cy + r * math.sin(math.radians(rotation + 72 * i)))
            for i in range(5)]


class Buddy:
    CAPTION_H = 64  # room above the character for its speech bubble
    GRAVITY = 1.2
    FRAME = 1 / 30

    def __init__(self, name="Groot", size=0.6, style="tree", area=Area(0, 0, 1440, 900)):
        self.name = name
        self.scale = size
        self.style = style  # "tree" (little tree creature) or "robot"
        # the walking fox is long (body plus a streaming tail), so it gets a wider box
        self.design_left, self.design_w = (-20, 280) if style in ("fox", "flat-fox") else (DESIGN_LEFT, DESIGN_W)
        self.W = int(max(self.design_w * size, 190))
        self.H = int(self.CAPTION_H + DESIGN_H * size)
        self.speed = 1.6 * max(size, 0.4)  # walking speed in pixels per frame
        self.on_quit = lambda: None  # set by the window

        self.session = None
        self.watcher = None  # reads new notifications aloud (Mac)
        self.state = "loading"
        self.emotion = "calm"
        self.emotion_until = 0.0
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
        self._press = None
        self._moved = False
        self.step = 0.0  # walking cycle
        self.turn = 0.0  # -1 facing left, 0 facing you, 1 facing right
        self.fall_speed = 0.0
        self.activity = None  # something you asked Groot to do, like playing football
        self.face_right = False  # side-view characters remember which way they face
        self.props = []  # toys on screen (each gets its own little window)
        self._fox_mode = "sleep"
        self._fox_corner = "right"
        self._fox_destination = None
        self._fox_departure = 0.0

        self.set_area(area)
        self.x = float(area.right - self.W - 30)
        self.y = self.floor
        if self.style == "fox":
            self.x = self._fox_corner_x("right")

    def set_area(self, area: Area) -> None:
        self.area = area
        self.floor = float(area.bottom - self.H)  # Groot walks along the bottom of the screen

    # ---- thread-safe updates (background threads put, the window thread applies)

    def set_state(self, state: str) -> None:
        self.events.put(("state", state))

    def set_text(self, text: str, seconds: float = None) -> None:
        self.events.put(("text", (text, seconds)))

    def set_session(self, session) -> None:
        self.events.put(("session", session))

    def set_watcher(self, watcher) -> None:
        self.events.put(("watcher", watcher))

    def perform(self, activity: str) -> None:
        """Start an on-screen activity (football, butterfly, dance, ...) or 'stop'."""
        self.events.put(("perform", activity))

    def end_conversation(self) -> None:
        """Called by the voice thread only when a conversation ends."""
        self.events.put(("conversation_end", None))

    # ---- mouse (positions in top-left-origin screen coordinates)

    def press(self, gx, gy):
        self._press = (gx, gy, self.x, self.y)
        self._moved = False

    def drag(self, gx, gy):
        if self._press is None:
            return
        sx, sy, wx, wy = self._press
        dx, dy = gx - sx, gy - sy
        if abs(dx) + abs(dy) > 4:
            self._moved = True
            self.dragging = True
        self.x, self.y = wx + dx, wy + dy
        self._place()

    def release(self):
        if self._press is None:
            return
        self._press = None
        self.dragging = False
        if self._moved:
            self.fall_speed = 0.0  # let go: Groot falls back down to the floor
            self._new_action("rest")
        else:
            self.toggle()

    def menu_items(self):
        """Right-click menu: (label, checked or None, callback) entries; None = separator."""
        items = [("Talk / Stop", None, lambda _=None: self.toggle()), None]
        for label, attr in (("Stay still", "stay_still"), ("Little Groot voice", "little_voice"),
                            ('"I am Groot" mode', "groot_mode")):
            items.append((label, getattr(self, attr), lambda checked, a=attr: self._set_option(a, checked)))
        if self.watcher is not None:
            items.append(("Read notifications aloud", self.watcher.enabled,
                          lambda checked: setattr(self.watcher, "enabled", checked)))
        items += [None, (f"Quit {self.name}", None, lambda _=None: self.quit())]
        return items

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
        self.on_quit()

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
            target = min(max(self.x + distance, a.left), a.right - self.W)
            if abs(target - self.x) < 60:  # at an edge: walk the other way
                target = min(max(self.x - distance, a.left), a.right - self.W)
            action["target"] = target
            action["until"] = now + 30
        else:
            action["until"] = now + {"rest": random.uniform(2, 4), "look": 2.5, "wave": 2,
                                     "jump": 1.2, "dance": 3}[name]
        self.action = action

    def _place(self):
        a = self.area
        self.x = min(max(self.x, a.left), a.right - self.W)
        self.y = min(max(self.y, a.top), self.floor)

    def set_emotion(self, emotion, seconds=8):
        if emotion in ("calm", "curious", "focused", "happy", "concerned", "annoyed"):
            self.events.put(("emotion", (emotion, seconds)))

    def _fox_emotion(self, now):
        if self.state in ("idle", "loading"):
            return "calm"
        if now < self.emotion_until:
            return self.emotion
        return {"listening": "curious", "thinking": "focused",
                "error": "concerned"}.get(self.state, "calm")

    def _fox_corner_x(self, side):
        left = float(self.area.left)
        right = max(left, float(self.area.right - self.W))
        margin = min(16.0, (right - left) / 2)
        return left + margin if side == "left" else right - margin

    def _nearest_fox_corner(self):
        return min(("left", "right"), key=lambda side: abs(self.x - self._fox_corner_x(side)))

    def _return_fox_to_corner(self, side):
        self.activity = None
        self.props = []
        self._fox_mode = "return"
        self._fox_destination = side
        self._fox_departure = self.t

    def _update_fox_behaviour(self, now, pose, awake):
        if awake:
            self._fox_mode = "awake"
            self._fox_destination = None
            self._stand_until = 0.0
        if self.activity is not None:
            if self._sleeping() and not awake:
                self._return_fox_to_corner(self._nearest_fox_corner())
            else:
                return self._do_activity(now, pose, awake)
        if self._fox_mode == "awake":
            if self.state == "waiting" and not self.stay_still:
                side = getattr(self, "_fox_roam_side", None)
                if side is None or abs(self.x - self._fox_corner_x(side)) < 2:
                    side = "left" if self._nearest_fox_corner() == "right" else "right"
                    self._fox_roam_side = side
                self._walk_toward(self._fox_corner_x(side), 0.8, pose)
                pose["bob"] = pose["lean"] = 0.0
                return pose
            # Sit still while hearing, thinking, or answering.
            self.look = (0, 0)
            return pose
        if self._fox_mode == "sleep":
            if abs(self.x - self._fox_corner_x(self._fox_corner)) <= 1:
                self.x = self._fox_corner_x(self._fox_corner)
                return pose
            # After a drag or screen resize, walk to the nearest safe corner.
            self._return_fox_to_corner(self._nearest_fox_corner())
        side = self._fox_destination
        target = self._fox_corner_x(side)
        if abs(target - self.x) < 1:
            self.x = target
            self._fox_corner = side
            self._fox_destination = None
            self._fox_mode = "sleep"
            self._stand_until = 0.0
            self.face_right = side == "left"
            return pose
        self._walk_toward(target, 2.0, pose, self.t - self._fox_departure)
        pose["bob"] = pose["lean"] = 0.0
        return pose

    def _update_behaviour(self, now):
        """Move the character and return its pose for this frame."""
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
        if self.fall_speed > 0:  # just landed
            self.fall_speed = 0.0
            self._new_action("rest")

        if self.style == "fox":
            return self._update_fox_behaviour(now, pose, awake)

        if self.activity is not None:
            return self._do_activity(now, pose, awake)

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
                    self.step += speed * (2 * math.pi * 0.62 / 30 if self.style == "fox" else 0.12) / max(self.scale, 0.4)
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

    def tick(self, now=None):
        """Advance one frame. The window then moves to (x, y) and redraws."""
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "state":
                self.state = value
                if value == "idle":
                    self.emotion_until = 0.0
            elif kind == "emotion":
                self.emotion, seconds = value
                self.emotion_until = time.monotonic() + seconds
            elif kind == "text":
                text, seconds = value
                self.caption = text
                self.caption_until = time.monotonic() + seconds if seconds else float("inf")
            elif kind == "watcher":
                self.watcher = value
            elif kind == "perform":
                self._start_activity(value)
            elif kind == "session":
                self.session = value
                self.little_voice = value.speaker.tree_voice
                self.groot_mode = value.groot_mode
            elif kind == "conversation_end" and self.style == "fox":
                side = "left" if self._nearest_fox_corner() == "right" else "right"
                self._return_fox_to_corner(side)

        now = time.monotonic() if now is None else now
        self.t += self.FRAME
        if now > self.next_blink:
            self.blink_until = now + 0.15
            self.next_blink = now + random.uniform(2.5, 6)
        previous_x = self.x
        self.pose = self._update_behaviour(now)
        if self.style == "fox":
            moving = abs(self.x - previous_x) > 0.0001
            self.pose["walking"] = moving
            if moving:
                self.face_right = self.x > previous_x
                self.pose["lean"] = 0.0
                self.pose["bob"] = 0.0
            elif self.activity is None:
                self.pose["bob"] = self.pose["lean"] = self.pose["lift"] = 0.0
        if self.state == "speaking":
            self.mouth = [max(0.15, min(1.0, m + random.uniform(-0.35, 0.35))) for m in self.mouth]

    # ---- drawing

    # ---- on-screen activities

    def _start_activity(self, name):
        self._end_activity(wave=False)
        if self.style == "fox" and name == "stop":
            self._return_fox_to_corner(self._nearest_fox_corner())
            return
        if name not in ACTIVITIES:
            return
        now = time.monotonic()
        self.activity = {"name": name, "start": now, "until": now + ACTIVITIES[name], "kick_until": 0.0,
                         "kick_dir": 1, "jump_start": -10.0, "target": None, "retarget": 0.0}
        if self.style == "fox":
            self._fox_mode = "awake"
            self._fox_destination = None
        if name == "sleep":
            self.activity["settled"] = self.state == "idle"
        center = self.x + self.W / 2
        toward_middle = 1 if center < (self.area.left + self.area.right) / 2 else -1
        if name == "football":
            r = 10 + 10 * self.scale
            self.props = [Prop("ball", center + toward_middle * 90, self.area.bottom - r - 2, r)]
        elif name == "butterfly":
            self.props = [Prop("butterfly", center + toward_middle * 120, self.floor + self.H * 0.2, 19)]

    def _end_activity(self, wave=True):
        self.activity = None
        self.props = []
        if wave and self.style != "fox":
            self._new_action("wave")

    def _do_activity(self, now, pose, awake):
        a = self.activity
        name = a["name"]
        elapsed = now - a["start"]
        facing = 0.0
        if name == "sleep" and not a.get("settled", True) and not awake:
            # Finish acknowledging the sleep command before starting the nap.
            a.update(settled=True, start=now, until=now + ACTIVITIES["sleep"])
            elapsed = 0.0
        if now > a["until"] or (name == "sleep" and awake and a.get("settled", True)):
            self._end_activity(wave=name != "sleep")
            return pose

        if name == "football":
            facing = self._play_football(now, pose, a)
        elif name == "butterfly":
            facing = self._chase_butterfly(now, pose, a)
        elif name == "run":
            if a["target"] is None or abs(a["target"] - self.x) < 6:
                a["target"] = self.area.left + 10 if self.x > (self.area.left + self.area.right - self.W) / 2 \
                    else self.area.right - self.W - 10
            facing = self._walk_toward(a["target"], 2.6, pose, elapsed)
        elif name == "dance":
            pose["bob"] = 3 * math.sin(elapsed * 9)
            pose["left_arm"] = 150 + 35 * math.sin(elapsed * 9)
            pose["right_arm"] = 30 - 35 * math.sin(elapsed * 9)
            pose["lean"] = 6 * math.sin(elapsed * 4.5)
            pose["legs"] = 0.6 * math.sin(elapsed * 9)
        elif name == "jump":
            pose["lift"] = 26 * abs(math.sin(elapsed * math.pi / 0.7))
            pose["left_arm"], pose["right_arm"] = 165, 15
        elif name == "wave":
            pose["right_arm"] = -55 + 25 * math.sin(elapsed * 10)
            pose["left_arm"] = 235 - 25 * math.sin(elapsed * 10) if elapsed > 2 else 112
        elif name == "sleep":
            pose["bob"] = 1.2 * math.sin(elapsed * 1.5)  # slow breathing
            pose["lean"] = 3
        self.turn += (facing - self.turn) * 0.15
        return pose

    def _walk_toward(self, target_x, speed_factor, pose, elapsed=1.0):
        """Take one step toward target_x (window x). Returns the direction faced."""
        dx = target_x - self.x
        if abs(dx) < 1:
            return 0.0
        direction = 1 if dx > 0 else -1
        speed = min(abs(dx), self.speed * speed_factor * min(1.0, elapsed / 0.4))
        self.x += direction * speed
        self._place()
        self.step += speed * (2 * math.pi * 0.62 / 30 if self.style == "fox" else 0.12) / max(self.scale, 0.4)
        swing = math.sin(self.step)
        pose["legs"] = swing
        pose["bob"] = -2.5 * abs(swing)
        pose["lean"] = 5 * direction
        pose["left_arm"] = 112 - 18 * swing
        pose["right_arm"] = 68 - 18 * swing
        self.look = (4 * direction, 0)
        return direction

    def _ball_physics(self, ball):
        a = self.area
        ground = a.bottom - ball.r - 2
        ball.vy += 0.6
        ball.cx += ball.vx
        ball.cy += ball.vy
        if ball.cy >= ground:
            ball.cy = ground
            ball.vy = -ball.vy * 0.45 if abs(ball.vy) > 2 else 0.0
            ball.vx *= 0.97  # rolling slows down
        if ball.cx - ball.r < a.left:
            ball.cx, ball.vx = a.left + ball.r, abs(ball.vx) * 0.7
        elif ball.cx + ball.r > a.right:
            ball.cx, ball.vx = a.right - ball.r, -abs(ball.vx) * 0.7
        ball.angle += math.degrees(ball.vx / ball.r)

    def _play_football(self, now, pose, a):
        ball = self.props[0]
        self._ball_physics(ball)
        center = self.x + self.W / 2
        dx = ball.cx - center
        direction = 1 if dx > 0 else -1
        reach = ball.r + 24 * self.scale
        on_ground = ball.cy >= self.area.bottom - ball.r - 2.5
        if now < a["kick_until"]:  # kicking!
            pose["legs"] = 1.4
            pose["lean"] = -4 * a["kick_dir"]
            pose["left_arm"], pose["right_arm"] = 140, 40
            return a["kick_dir"]
        if abs(dx) > reach:
            return self._walk_toward(ball.cx - self.W / 2 - direction * reach * 0.8, 2.2, pose)
        if on_ground and abs(ball.vx) < 3:
            # kick it - toward the middle of the screen if the ball is near an edge
            kick = direction
            if ball.cx + kick * 220 > self.area.right or ball.cx + kick * 220 < self.area.left:
                kick = -kick
            ball.vx = kick * random.uniform(7, 13)
            ball.vy = -random.uniform(3, 9)
            a["kick_until"] = now + 0.25
            a["kick_dir"] = kick
            return kick
        self.look = (5 * direction, -1)  # watch the ball
        pose["left_arm"], pose["right_arm"] = 140, 40  # cheer
        return 0.0

    def _chase_butterfly(self, now, pose, a):
        fly = self.props[0]
        fly.t += self.FRAME
        if a["target"] is None or now > a["retarget"]:
            center = self.x + self.W / 2
            a["target"] = (min(max(center + random.uniform(-260, 260), self.area.left + 30), self.area.right - 30),
                           self.area.bottom - random.uniform(self.H * 0.55, self.H * 1.4))
            a["retarget"] = now + random.uniform(1.5, 3)
        tx, ty = a["target"]
        fly.cx += (tx - fly.cx) * 0.03 + math.sin(fly.t * 5) * 1.2
        fly.cy += (ty - fly.cy) * 0.03 + math.cos(fly.t * 7) * 1.5
        center = self.x + self.W / 2
        dx = fly.cx - center
        direction = 1 if dx > 0 else -1
        jumping = now - a["jump_start"] < 0.7
        if jumping:
            pose["lift"] = 30 * math.sin((now - a["jump_start"]) * math.pi / 0.7)
            pose["left_arm"], pose["right_arm"] = 200, -20  # reaching up
            self.look = (3 * direction, -6)
            return direction
        if abs(dx) > 30:
            facing = self._walk_toward(fly.cx - self.W / 2, 1.8, pose)
            self.look = (4 * direction, -5)
            return facing
        if random.random() < 0.04:
            a["jump_start"] = now  # try to catch it!
        self.look = (3 * direction, -6)
        return 0.0

    def draw(self, c: Canvas, now=None):
        if not self.pose:
            return
        now = time.monotonic() if now is None else now
        c.save()
        # the character is designed on a 240 x 310 grid; scale it into the window
        c.translate(self.W / 2 - (self.design_left + self.design_w / 2) * self.scale,
                    self.CAPTION_H - DESIGN_TOP * self.scale)
        c.scale(self.scale)
        lean = self.pose.get("lean", 0.0)
        if self.style == "fox" and self._fox_curled_up(now):
            lean = 0.0  # sleeping body rests flat on the floor
        if lean:  # tilt the whole body around its feet
            c.translate(CX, 298)
            c.rotate(lean)
            c.translate(-CX, -298)
        if self.style == "robot":
            self._draw_robot(c, now)
        elif self.style == "fox":
            if not self._draw_fox_sprite(c, now):
                self._draw_fox(c, now, realistic=True)
        elif self.style == "flat-fox":
            self._draw_fox(c, now, realistic=False)
        elif self.style == "cute-fox":
            self._draw_cute_fox(c, now)
        else:
            self._draw_tree(c, now)
        c.restore()
        self._draw_caption(c, now)

    def _fox_sprite_frame(self, now):
        """Choose registered poses using travelled distance for the gait."""
        if self.pose.get("walking", False):
            self._stand_until = now + 0.8
            return int((self.step % math.tau) / math.tau * 8) % 8
        if self.dragging:
            return 8
        # One seated drawing prevents the body shifting between speech poses.
        return 12

    def _draw_fox_sprite(self, c, now):
        if self._fox_curled_up(now) and self._draw_sleeping_fox(c):
            self._draw_sleep_marks(c)
            return True
        path = Path(__file__).with_name("assets") / "red-white-serious-fox.png"
        if not path.is_file():
            return False
        frame = self._fox_sprite_frame(now)
        c.save()
        if self.face_right:
            c.translate(2 * CX, 0)
            c.scale_xy(-1, 1)
        # Register each pose's actual paw baseline to the desktop floor.
        size = 300
        ground = 298 - self.pose.get("lift", 0)
        # Every frame has its own transparent gutter and the same registration.
        # Do not clip to generated grid cells: that used to cut through tail tips.
        drawn = c.sprite(str(path), frame, 4, 4, CX - size / 2,
                         ground - size * FOX_SPRITE_GROUNDS[frame], size, size)
        c.restore()
        if drawn:
            self._draw_fox_emotion(c, now)
        return drawn

    def _draw_fox_emotion(self, c, now):
        mood = self._fox_emotion(now)
        # Small expressive marks; keep the registered body completely still.
        marks = {"curious": ("?", "#e4b955"), "focused": ("...", "#8fb0d6"),
                 "happy": ("♥", "#df7979"), "concerned": ("!", "#82b9d2"),
                 "annoyed": ("!", "#d84a39")}
        if mood not in marks:
            return
        mark, color = marks[mood]
        x = 170 if self.face_right else 57
        c.text(x, 99 + 1.5 * math.sin(self.t * 2), mark, 21, color, bold=True)

    def _fox_curled_up(self, now):
        """Sleep only on the floor in the selected corner, until called."""
        if (self.dragging or self.pose.get("walking", False)
                or self.state not in ("idle", "loading") or self.y < self.floor - 0.5):
            return False
        return (self._fox_mode == "sleep"
                and abs(self.x - self._fox_corner_x(self._fox_corner)) <= 1)

    def _draw_sleep_marks(self, c):
        # Draw after mirroring the fox so letters remain readable on either side.
        for i in range(3):
            phase = (self.t / 3 + i / 3) % 1
            c.text(CX + 18 + phase * 22, 170 - phase * 42, "Z",
                   12 + phase * 6, ("#523e50", 0.9 - 0.5 * phase), bold=True)

    def _draw_sleeping_fox(self, c):
        path = Path(__file__).with_name("assets") / "red-white-fox-sleeping.png"
        if not path.is_file():
            return False
        width, height = 250, 250 * 0.7142857142857143
        ground = 298
        c.save()
        if self.face_right:
            c.translate(2 * CX, 0)
            c.scale_xy(-1, 1)
        # Breathe about fifteen times a minute, anchored to the floor.
        c.translate(CX, ground)
        c.scale_xy(1, 1 + 0.015 * math.sin(self.t * math.tau / 4))
        c.translate(-CX, -ground)
        drawn = c.sprite(str(path), 0, 1, 1, CX - width / 2,
                         ground - height * 0.8641509433962264, width, height)
        c.restore()
        return drawn

    def _eye_open_amount(self, now, sleepy):
        if self._sleeping():
            return 0.1
        if now < self.blink_until:
            return 0.1
        if self.dragging:
            return 1.15  # surprised!
        return sleepy if self._resting() else 1.0

    def _sleeping(self):
        return self.activity is not None and self.activity["name"] == "sleep"

    def _resting(self):
        if self.activity is not None:
            return self._sleeping()  # wide awake while playing
        return self.state == "idle" and self.action["name"] == "rest" and not self.dragging

    def _zzz(self, c, now, x, y, color):
        z = (now * 0.8) % 1
        size = int(10 + 6 * z)
        c.text(x, y - 20 * z - size, "z", size, color, bold=True)

    def _draw_robot(self, c, now):
        pose = self.pose
        cx = CX
        oy = pose["bob"] - pose["lift"]
        glow = EYE_COLORS.get(self.state, EYE_COLORS["idle"])
        turn = self.turn

        for side, phase in ((-1, pose["legs"]), (1, -pose["legs"])):
            lx = cx + side * 17 + turn * 6 * phase
            up = 0 if self.dragging else max(0.0, phase) * 8
            dangle = 6 if self.dragging else 0
            top = 248 + oy
            foot = 280 + oy - up + dangle
            c.rrect(lx - 10, top, lx + 10, foot + 4, 8, WHITE, SHADE, 2)
            c.line(lx - 7, (top + foot) / 2 + 2, lx + 7, (top + foot) / 2 + 2, "#e0b84a", 2)
            toe = turn * 5
            c.rrect(lx - 15 + toe, foot, lx + 15 + toe, foot + 18, 8, DARK)

        for shoulder_x, angle in ((cx - 36, pose["left_arm"]), (cx + 36, pose["right_arm"])):
            sy = 212 + oy
            rad = math.radians(angle)
            hx, hy = shoulder_x + 38 * math.cos(rad), sy + 38 * math.sin(rad)
            c.line(shoulder_x, sy, hx, hy, SHADE, 17)
            c.line(shoulder_x, sy, hx, hy, WHITE, 13)
            c.oval(shoulder_x - 8, sy - 8, shoulder_x + 8, sy + 8, DARK)
            c.oval(hx - 9, hy - 9, hx + 9, hy + 9, DARK)

        c.rrect(cx - 14, 188 + oy, cx + 14, 202 + oy, 2, DARK)  # neck
        c.rrect(cx - 38, 196 + oy, cx + 38, 256 + oy, 24, WHITE, SHADE, 2)
        c.arc(cx - 24, 214 + oy, cx + 24, 248 + oy, 200, 140, SHADE, 2)  # belly smile
        d, ly = 5, 214 + oy
        c.polygon([(cx, ly - d), (cx + d, ly), (cx, ly + d), (cx - d, ly)],
                  glow if self.state == "speaking" else "#f0a030")

        fx = turn * 9
        for side in (-1, 1):  # headphones: the one on the far side tucks behind the head
            hx = cx + side * 70 - turn * 6 + (side * turn > 0) * side * -4
            c.rrect(hx - 10, 124 + oy, hx + 10, 174 + oy, 9, DARK)
        c.rrect(cx - 66, 98 + oy, cx + 66, 196 + oy, 42, WHITE, SHADE, 2)
        for side in (-1, 1):
            if side * turn > 0.5:
                continue
            hx = cx + side * 74 - turn * 6
            c.line(hx, 134 + oy, hx, 164 + oy, glow, 2)
        c.rrect(cx - 30 + fx, 110 + oy, cx + 30 + fx, 117 + oy, 3, DARK)

        open_amount = self._eye_open_amount(now, 0.75)
        look_x, look_y = self.look
        for side in (-1, 1):
            ex, ey = cx + side * 30 + fx, 148 + oy
            if open_amount < 0.2:
                c.line(ex - 18, ey, ex + 18, ey, EYE_DARK, 4)
                continue
            ry = 23 * open_amount
            c.oval(ex - 25, ey - ry - 2, ex + 25, ey + ry + 2, glow)
            c.oval(ex - 20, ey - ry + 3, ex + 20, ey + ry - 3, EYE_DARK)
            px, py = ex + look_x, ey + look_y * open_amount
            c.oval(px - 13, py - 13 * open_amount, px + 13, py + 13 * open_amount, None, glow, 2)
            c.oval(px - 10, py - 10 * open_amount, px + 10, py + 10 * open_amount, "#000000")
            c.oval(px - 6, py - 7, px - 1, py - 2, "#ffffff")

        my = 180 + oy
        if self.state == "speaking":
            for i, level in enumerate(self.mouth):
                bx = cx - 12 + i * 6 + fx
                c.line(bx, my - 5 * level, bx, my + 5 * level, glow, 3)
        else:
            c.rrect(cx - 8 + fx, my - 2, cx + 8 + fx, my + 2, 2, DARK)

        if self._resting():
            self._zzz(c, now, cx + 52, 98 + oy, "#8fa3b5")

    # ---- the little tree creature

    def _leaf(self, c, x, y, length, width, angle, color):
        """A leaf growing from (x, y), pointing at `angle` degrees."""
        c.save()
        c.translate(x, y)
        c.rotate(angle)
        shape = Shape(0, 0).quad(length * 0.45, -width, length, 0).quad(length * 0.45, width, 0, 0).close()
        c.fill_stroke(shape, color, VINE_DARK, 1.2)
        c.line(1, 0, length * 0.85, 0, darker(color), 1)
        c.restore()

    def _vine(self, c, *points, width=3.2):
        """A curvy vine through the given points (start, then groups of 3 for curves)."""
        shape = Shape(*points[0])
        for i in range(1, len(points) - 2, 3):
            shape.cubic(*points[i], *points[i + 1], *points[i + 2])
        c.fill_stroke(shape, None, VINE_DARK, width + 1.6)
        c.fill_stroke(shape, None, VINE, width)

    def _limb(self, c, x1, y1, x2, y2, width):
        c.line(x1, y1, x2, y2, BARK_DARK, width + 3)
        c.line(x1, y1, x2, y2, BARK, width)
        c.line(x1 - 1, y1, x2 - 1, y2, BARK_LIGHT, max(2, width / 4))

    def _draw_tree(self, c, now):
        pose = self.pose
        cx = CX
        oy = pose["bob"] - pose["lift"]
        leaf = LEAF_COLORS.get(self.state, LEAF_COLORS["idle"])
        turn = self.turn
        fx = turn * 8  # face slides toward where Groot is walking
        sway = math.sin(self.t * 2.2)

        # legs: bark limbs with little vine anklets
        for side, phase in ((-1, pose["legs"]), (1, -pose["legs"])):
            hip_x = cx + side * 10
            up = 0 if self.dragging else max(0.0, phase) * 8
            dangle = 6 if self.dragging else 0
            foot_x = cx + side * 15 + turn * 6 * phase
            foot_y = 284 + oy - up + dangle
            self._limb(c, hip_x, 250 + oy, foot_x, foot_y, 12)
            c.oval(foot_x - 12 + turn * 4, foot_y - 3, foot_x + 12 + turn * 4, foot_y + 9, BARK, BARK_DARK, 2)
            self._vine(c, (foot_x - 7, foot_y - 12), (foot_x - 2, foot_y - 8), (foot_x + 3, foot_y - 15),
                       (foot_x + 7, foot_y - 10), width=2.2)

        # body: a little tapered trunk with a vine across it
        body = (Shape(cx - 9, 196 + oy).line(cx + 9, 196 + oy)
                .cubic(cx + 14, 215 + oy, cx + 20, 240 + oy, cx + 16, 256 + oy)
                .line(cx - 16, 256 + oy)
                .cubic(cx - 20, 240 + oy, cx - 14, 215 + oy, cx - 9, 196 + oy).close())
        c.gradient(body, (cx - 18, 0), (cx + 18, 0), [(0, BARK), (0.4, BARK_LIGHT), (1, BARK)], BARK_DARK, 2)
        c.line(cx - 4, 222 + oy, cx - 6, 246 + oy, BARK_DARK, 1.2)  # bark grain
        c.line(cx + 6, 214 + oy, cx + 7, 236 + oy, BARK_DARK, 1.2)
        self._vine(c, (cx - 12, 204 + oy), (cx - 2, 214 + oy), (cx + 4, 226 + oy), (cx + 15, 240 + oy), width=2.6)
        self._leaf(c, cx + 13, 238 + oy, 12, 5, 20 + 10 * sway, leaf)

        # arms: thin branches with little twiggy hands
        for shoulder_x, angle in ((cx - 12, pose["left_arm"]), (cx + 12, pose["right_arm"])):
            sy = 208 + oy
            rad = math.radians(angle)
            hx, hy = shoulder_x + 40 * math.cos(rad), sy + 40 * math.sin(rad)
            self._limb(c, shoulder_x, sy, hx, hy, 9)
            c.oval(hx - 6, hy - 6, hx + 6, hy + 6, BARK, BARK_DARK, 1.5)
            for finger in (-35, 0, 35):
                f = rad + math.radians(finger)
                c.line(hx, hy, hx + 9 * math.cos(f), hy + 9 * math.sin(f), BARK_DARK, 3.5)

        # head: a big tree stump with a jagged top
        tops = [(-60, 118), (-56, 96), (-42, 108), (-31, 88), (-15, 101), (-2, 84), (12, 99),
                (26, 86), (39, 103), (54, 93), (60, 117)]
        head = Shape(cx + tops[0][0], tops[0][1] + oy)
        for dx, y in tops[1:]:
            head.line(cx + dx, y + oy)
        head.cubic(cx + 67, 150 + oy, cx + 62, 186 + oy, cx + 38, 199 + oy)
        head.quad(cx, 211 + oy, cx - 38, 199 + oy)
        head.cubic(cx - 62, 186 + oy, cx - 67, 150 + oy, cx - 60, 118 + oy).close()
        c.gradient(head, (0, 84 + oy), (0, 210 + oy), [(0, "#9a7a3e"), (0.25, BARK_LIGHT), (1, BARK)],
                   BARK_DARK, 2.2)
        for x1, y1, x2, y2 in ((-31, 90, -35, 112), (-2, 86, 2, 108), (26, 88, 22, 110), (-48, 104, -52, 124)):
            c.line(cx + x1, y1 + oy, cx + x2, y2 + oy, BARK_DARK, 1.4)  # bark cracks

        # sprout on top, swaying gently
        tip_x = cx + 4 + 4 * sway
        c.fill_stroke(Shape(cx - 2, 86 + oy).quad(cx - 6, 72 + oy, tip_x, 64 + oy), None, VINE_DARK, 3)
        self._leaf(c, tip_x, 64 + oy, 14, 6, -150 + 8 * sway, leaf)
        self._leaf(c, tip_x, 64 + oy, 14, 6, -30 + 8 * sway, leaf)

        # vines across the face
        self._vine(c, (cx - 60, 132 + oy), (cx - 30, 112 + oy), (cx + 10 + fx, 136 + oy), (cx + 60, 122 + oy))
        self._vine(c, (cx - 58, 150 + oy), (cx - 48, 170 + oy), (cx - 54, 184 + oy), (cx - 40, 197 + oy), width=2.6)
        self._leaf(c, cx + 30 + fx, 126 + oy, 11, 5, -60, leaf)

        # eyes: big shiny dark eyes framed by leaves
        open_amount = self._eye_open_amount(now, 0.72)
        look_x, look_y = self.look
        wiggle = 6 * math.sin(self.t * 9) if self.state == "speaking" else 0
        for side in (-1, 1):
            ex, ey = cx + side * 26 + fx, 152 + oy
            self._leaf(c, ex + side * 4, ey - 6, 40, 17, (205 if side < 0 else -25) + side * wiggle, leaf)
            if self.state == "listening":  # a soft glow while listening
                c.oval(ex - 22, ey - 25, ex + 22, ey + 25, (leaf, 0.35))
            if open_amount < 0.2:
                c.line(ex - 14, ey, ex + 14, ey, "#1b1410", 4)
                continue
            rx, ry = 16, 19 * open_amount
            ox, oy2 = look_x * 0.6, look_y * 0.6
            c.oval(ex - rx + ox, ey - ry + oy2, ex + rx + ox, ey + ry + oy2, "#140f0c", BARK_DARK, 1.5)
            c.oval(ex - 9 + ox, ey - 12 * open_amount + oy2, ex - 2 + ox, ey - 5 * open_amount + oy2, "#ffffff")
            c.oval(ex + 4 + ox, ey + 4 * open_amount + oy2, ex + 7 + ox, ey + 7 * open_amount + oy2, "#d8d8d8")

        # rosy cheeks and mouth
        for side in (-1, 1):
            c.oval(cx + side * 40 - 8 + fx, 172 + oy, cx + side * 40 + 8 + fx, 180 + oy, ("#e0785a", 0.43))
        mx, my = cx + fx * 1.1, 186 + oy
        if self.state == "speaking":
            opening = 2 + 7 * sum(self.mouth) / len(self.mouth)
            c.oval(mx - 7, my - opening / 2, mx + 7, my + opening / 2, "#3a1d12", BARK_DARK, 1.2)
        else:
            c.arc(mx - 9, my - 7, mx + 9, my + 3, 200, 140, BARK_DARK, 2.2)

        if self._resting():
            self._zzz(c, now, cx + 50, 84 + oy, "#7f9a6a")

    # ---- the fox

    def _fox_limb(self, c, x1, y1, x2, y2, width):
        c.line(x1, y1, x2, y2, FUR_LINE, width + 3)
        c.line(x1, y1, x2, y2, FUR, width)

    def _draw_cute_fox(self, c, now):
        pose = self.pose
        cx = CX
        oy = pose["bob"] - pose["lift"]
        turn = self.turn
        fx = turn * 8  # face slides toward where the fox is walking
        side = -1 if turn > 0.3 else 1  # the tail trails behind: on the left when walking right

        # bushy tail, swishing
        swish = 10 * math.sin(self.t * 3) + (18 if self.state == "listening" else 0)
        c.save()
        c.translate(cx + side * 14, 246 + oy)
        c.rotate(side * (-30 + swish))
        tail = (Shape(0, -7).cubic(side * 24, -34, side * 62, -34, side * 82, -10)
                .cubic(side * 74, 10, side * 40, 20, 0, 9).close())
        c.fill_stroke(tail, FUR, FUR_LINE, 2)
        tip = (Shape(side * 60, -24).cubic(side * 70, -27, side * 82, -20, side * 82, -10)
               .cubic(side * 78, 0, side * 70, 6, side * 60, 9)
               .cubic(side * 65, -2, side * 65, -14, side * 60, -24).close())
        c.fill_stroke(tip, CREAM, FUR_LINE, 1.5)
        c.restore()

        # legs with dark socks
        for leg_side, phase in ((-1, pose["legs"]), (1, -pose["legs"])):
            hip_x = cx + leg_side * 12
            up = 0 if self.dragging else max(0.0, phase) * 8
            dangle = 6 if self.dragging else 0
            foot_x = cx + leg_side * 15 + turn * 6 * phase
            foot_y = 286 + oy - up + dangle
            self._fox_limb(c, hip_x, 246 + oy, foot_x, foot_y - 8, 13)
            c.line(foot_x - turn * 2, foot_y - 12, foot_x, foot_y - 2, SOCK, 12)
            c.oval(foot_x - 11 + turn * 4, foot_y - 6, foot_x + 11 + turn * 4, foot_y + 6, SOCK)

        # body with a cream tummy
        c.oval(cx - 27, 194 + oy, cx + 27, 260 + oy, FUR, FUR_LINE, 2)
        c.oval(cx - 16 + fx * 0.4, 206 + oy, cx + 16 + fx * 0.4, 254 + oy, CREAM)

        # arms with dark paws
        for shoulder_x, angle in ((cx - 18, pose["left_arm"]), (cx + 18, pose["right_arm"])):
            sy = 210 + oy
            rad = math.radians(angle)
            hx, hy = shoulder_x + 34 * math.cos(rad), sy + 34 * math.sin(rad)
            self._fox_limb(c, shoulder_x, sy, hx, hy, 10)
            c.oval(hx - 7, hy - 7, hx + 7, hy + 7, SOCK)

        # head: tilts when thinking
        c.save()
        tilt = 7 * math.sin(self.t * 1.2) if self.state == "thinking" else 0
        if tilt:
            c.translate(cx, 196 + oy)
            c.rotate(tilt)
            c.translate(-cx, -196 - oy)

        # ears (perk up while listening)
        perk = -8 if self.state == "listening" else 2 * math.sin(self.t * 1.7)
        for ear_side in (-1, 1):
            base_x = cx + ear_side * 34 + fx * 0.5
            c.save()
            c.translate(base_x, 116 + oy)
            c.rotate(ear_side * (12 + perk))
            c.fill_stroke(Shape(-18, 6).line(-2, -44).line(18, 6).close(), FUR, FUR_LINE, 2)
            c.fill_stroke(Shape(-10, 2).line(-2, -30).line(10, 2).close(), EAR_INSIDE)
            c.fill_stroke(Shape(-9, -24).line(-2, -44).line(7, -24).close(), SOCK)  # dark tips
            c.restore()

        # head shape with fluffy cheeks
        head = (Shape(cx, 102 + oy).cubic(cx + 42, 102 + oy, cx + 62, 124 + oy, cx + 62, 150 + oy)
                .line(cx + 74, 172 + oy).line(cx + 54, 174 + oy)
                .cubic(cx + 44, 192 + oy, cx + 22, 202 + oy, cx, 202 + oy)
                .cubic(cx - 22, 202 + oy, cx - 44, 192 + oy, cx - 54, 174 + oy)
                .line(cx - 74, 172 + oy).line(cx - 62, 150 + oy)
                .cubic(cx - 62, 124 + oy, cx - 42, 102 + oy, cx, 102 + oy).close())
        c.gradient(head, (0, 102 + oy), (0, 202 + oy), [(0, FUR_LIGHT), (0.6, FUR), (1, FUR)], FUR_LINE, 2.2)
        mask = (Shape(cx - 52 + fx, 160 + oy).cubic(cx - 36 + fx, 150 + oy, cx - 12 + fx, 154 + oy, cx + fx, 166 + oy)
                .cubic(cx + 12 + fx, 154 + oy, cx + 36 + fx, 150 + oy, cx + 52 + fx, 160 + oy)
                .line(cx + 66, 171 + oy).line(cx + 48, 173 + oy)
                .cubic(cx + 38, 190 + oy, cx + 18, 199 + oy, cx + fx * 0.5, 199 + oy)
                .cubic(cx - 18, 199 + oy, cx - 38, 190 + oy, cx - 48, 173 + oy)
                .line(cx - 66, 171 + oy).close())
        c.fill_stroke(mask, CREAM)

        # eyes
        open_amount = self._eye_open_amount(now, 0.65)
        look_x, look_y = self.look
        glow = FOX_GLOW.get(self.state)
        for eye_side in (-1, 1):
            ex, ey = cx + eye_side * 24 + fx, 146 + oy
            if glow:
                c.oval(ex - 17, ey - 19, ex + 17, ey + 19, (glow, 0.3))
            if open_amount < 0.2:
                c.arc(ex - 11, ey - 6, ex + 11, ey + 4, 200, 140, SOCK, 3)  # happy closed eyes
                continue
            rx, ry = 11, 14 * open_amount
            ox, oy2 = look_x * 0.5, look_y * 0.5
            c.oval(ex - rx + ox, ey - ry + oy2, ex + rx + ox, ey + ry + oy2, "#1a1210")
            c.oval(ex - 6 + ox, ey - 9 * open_amount + oy2, ex - 1 + ox, ey - 4 * open_amount + oy2, "#ffffff")
            c.oval(ex + 3 + ox, ey + 3 * open_amount + oy2, ex + 5 + ox, ey + 5 * open_amount + oy2, "#dddddd")

        # nose, mouth and cheeks
        nx, ny = cx + fx * 1.2, 168 + oy
        c.fill_stroke(Shape(nx - 7, ny - 3).cubic(nx - 7, ny - 7, nx + 7, ny - 7, nx + 7, ny - 3)
                      .cubic(nx + 6, ny + 2, nx + 2, ny + 5, nx, ny + 5)
                      .cubic(nx - 2, ny + 5, nx - 6, ny + 2, nx - 7, ny - 3).close(), "#2a1d1a")
        c.oval(nx - 3, ny - 5, nx + 1, ny - 3, "#6b5a55")  # shine
        if self.state == "speaking":
            opening = 2 + 7 * sum(self.mouth) / len(self.mouth)
            c.oval(nx - 6, ny + 7, nx + 6, ny + 7 + opening, "#7a2e2a", SOCK, 1.2)
        else:
            c.arc(nx - 8, ny + 1, nx, ny + 10, 200, 140, SOCK, 1.8)  # little "w" smile
            c.arc(nx, ny + 1, nx + 8, ny + 10, 200, 140, SOCK, 1.8)
        for cheek_side in (-1, 1):
            c.oval(cx + cheek_side * 40 - 7 + fx, 172 + oy, cx + cheek_side * 40 + 7 + fx, 179 + oy, ("#ff8a7a", 0.4))
        c.restore()

        if self._resting():
            self._zzz(c, now, cx + 54, 84 + oy, "#c58a5a")

    # ---- the elegant fox (flat illustration style, seen from the side)

    def _fox_tail(self, c, x, y, angle, size=1.0):
        """Big tail growing from (x, y), pointing up and turned by `angle` degrees."""
        c.save()
        c.translate(x, y)
        c.rotate(angle)
        c.scale(size)
        tail = (Shape(0, 0).cubic(40, 0, 52, -36, 44, -68).cubic(40, -84, 32, -94, 24, -98)
                .cubic(28, -80, 26, -58, 18, -38).cubic(12, -22, 6, -10, 0, 0).close())
        c.fill_stroke(tail, FOX_RUST)
        c.polygon([(24, -98), (38, -88), (46, -68), (39, -70), (42, -59), (34, -64), (33, -53),
                   (27, -62), (26, -72), (28, -84)], FOX_CREAM)  # white tip with a jagged edge
        c.restore()

    def _fox_head(self, c, now, dx, dy, awake, relaxed=True, size=1.0):
        """Head in profile, facing left; (118, 150) + (dx, dy) is where it joins the neck."""
        c.save()
        c.translate(dx, dy)
        if size != 1.0:
            c.translate(118, 150)
            c.scale(size)
            c.translate(-118, -150)
        if self.state == "thinking":  # tilt the head while thinking
            c.translate(120, 140)
            c.rotate(-8 + 3 * math.sin(self.t * 1.5))
            c.translate(-120, -140)
        perk = -10 if self.state == "listening" else 2 * math.sin(self.t * 1.3)
        for base_x, tip_x, color in ((126, 132, FOX_SHADE), (112, 116, FOX_ORANGE)):  # back ear, front ear
            c.save()
            c.translate(base_x + 8, 104)
            c.rotate(perk)
            c.translate(-base_x - 8, -104)
            c.polygon([(base_x - 6, 106), (tip_x, 66), (base_x + 16, 104)], color)
            if color == FOX_ORANGE:
                c.polygon([(base_x - 1, 102), (tip_x + 1, 80), (base_x + 9, 102)], FOX_RUST)
            c.restore()
        head = (Shape(140, 118).cubic(134, 100, 118, 94, 104, 100).cubic(92, 106, 78, 118, 60, 131)
                .line(57, 135).cubic(70, 142, 82, 146, 91, 146).line(98, 152).line(104, 147)
                .line(112, 155).line(118, 149).cubic(132, 146, 142, 134, 140, 118).close())
        c.fill_stroke(head, FOX_ORANGE)
        muzzle = (Shape(58, 135).cubic(76, 134, 96, 131, 110, 137).line(116, 150).line(106, 146)
                  .line(99, 152).line(92, 146).cubic(80, 146, 68, 142, 58, 135).close())
        c.fill_stroke(muzzle, FOX_CREAM)
        c.oval(54, 130, 62, 137, FOX_LEG)  # nose

        # eye: calm and closed while relaxing, open when talking with you
        ex, ey = 96, 118
        open_amount = self._eye_open_amount(now, 0.0 if not awake else 1.0)
        if relaxed and not awake and now >= self.blink_until and not self.dragging and self.activity is None:
            open_amount = 0.1  # relaxed, like in a calm illustration
        glow = FOX_GLOW.get(self.state)
        if glow:
            c.oval(ex - 10, ey - 9, ex + 10, ey + 9, (glow, 0.3))
        if open_amount < 0.2:
            c.arc(ex - 8, ey - 4, ex + 8, ey + 4, 190, 160, FOX_RUST, 2.4)
        else:
            look_x, look_y = self.look
            ox, oy2 = -abs(look_x) * 0.3, look_y * 0.3
            c.oval(ex - 5 + ox, ey - 6 * open_amount + oy2, ex + 5 + ox, ey + 6 * open_amount + oy2, FOX_LEG)
            c.oval(ex - 3 + ox, ey - 4 * open_amount + oy2, ex + ox, ey - 1 * open_amount + oy2, "#ffffff")
        if self.state == "speaking":
            opening = 1 + 6 * sum(self.mouth) / len(self.mouth)
            c.polygon([(62, 138), (84, 141), (66, 140 + opening)], "#5a1f18")
        c.restore()

    def _draw_fox(self, c, now, realistic=True):
        pose = self.pose
        oy = pose["bob"] - pose["lift"]
        awake = self.state in ("listening", "thinking", "speaking")
        if not pose.get("walking", False) and abs(self.turn) > 0.5:
            self.face_right = self.turn > 0
        if pose.get("walking", abs(pose["legs"]) > 0.01):
            self._stand_until = now + 0.6  # keep standing a moment so it doesn't flicker
        standing = now < getattr(self, "_stand_until", 0.0)

        c.save()
        if getattr(self, "face_right", False):  # drawn facing left; mirror to face right
            c.translate(2 * CX, 0)
            c.scale_xy(-1, 1)
        swish = 6 * math.sin(self.t * 2.4) + (8 if self.state == "listening" else 0)
        if realistic:
            (self._real_fox_standing if standing else self._real_fox_sitting)(c, now, pose, oy, swish, awake)
        elif standing:
            self._fox_standing(c, now, pose, oy, swish, awake)
        else:
            self._fox_sitting(c, now, pose, oy, swish, awake)
        c.restore()
        if self._resting():
            self._zzz(c, now, CX + 40, 84 + oy, "#c58a5a")

    def _fox_sitting(self, c, now, pose, oy, swish, awake):
        self._fox_tail(c, 142, 294 + oy, swish)
        body = (Shape(112, 150 + oy).cubic(150, 160 + oy, 172, 215 + oy, 168, 262 + oy)
                .cubic(166, 288 + oy, 150, 298 + oy, 124, 298 + oy).line(104, 298 + oy)
                .cubic(98, 270 + oy, 92, 232 + oy, 96, 205 + oy).cubic(98, 180 + oy, 100, 165 + oy, 112, 150 + oy)
                .close())
        c.fill_stroke(body, FOX_ORANGE)
        c.fill_stroke(Shape(148, 236 + oy).cubic(162, 250 + oy, 164, 276 + oy, 150, 292 + oy)
                      .cubic(158, 270 + oy, 156, 252 + oy, 148, 236 + oy).close(), FOX_SHADE)  # haunch shading
        bib = (Shape(82, 148 + oy).cubic(102, 156 + oy, 118, 180 + oy, 117, 214 + oy)
               .cubic(116, 236 + oy, 110, 250 + oy, 104, 254 + oy).cubic(98, 236 + oy, 94, 212 + oy, 94, 192 + oy)
               .cubic(93, 174 + oy, 88, 160 + oy, 82, 148 + oy).close())
        c.fill_stroke(bib, FOX_CREAM)
        # front legs; one paw lifts to wave
        waving = ((self.activity is not None and self.activity["name"] == "wave")
                  or (self.activity is None and not awake and self.action["name"] == "wave"))
        for i, (top_x, paw_x) in enumerate(((108, 100), (120, 116))):
            if waving and i == 0:
                lift = 8 * math.sin(self.t * 10)
                c.line(top_x, 232 + oy, 84, 222 + oy + lift, FOX_LEG, 7)
                c.oval(76, 216 + oy + lift, 90, 226 + oy + lift, FOX_LEG)
                continue
            dangle = 6 if self.dragging else 0
            c.line(top_x, 232 + oy, paw_x, 292 + oy + dangle, FOX_LEG, 7)
            c.oval(paw_x - 12, 289 + oy + dangle, paw_x + 5, 298 + oy + dangle, FOX_LEG)
        self._fox_head(c, now, 0, oy, awake)

    @staticmethod
    def _knee(hip, foot, upper, lower, bend):
        """Where the knee goes for a two-part leg from hip to foot (bend = +1 or -1)."""
        (hx, hy), (fx, fy) = hip, foot
        dx, dy = fx - hx, fy - hy
        dist = min(math.hypot(dx, dy), upper + lower - 0.01)
        cos_a = max(-1.0, min(1.0, (upper ** 2 + dist ** 2 - lower ** 2) / (2 * upper * dist)))
        angle = math.atan2(dy, dx) + bend * math.acos(cos_a)
        return hx + upper * math.cos(angle), hy + upper * math.sin(angle)

    def _fox_leg(self, c, hip, foot, bend, far, kicking=False):
        knee = self._knee(hip, foot, 30, 34, bend)
        fur = FOX_SHADE if far else FOX_ORANGE
        sock = "#3d322d" if far else FOX_SOCK
        c.line(hip[0], hip[1], knee[0], knee[1], fur, 13)
        c.line(knee[0], knee[1], foot[0], foot[1], sock, 8)
        c.oval(foot[0] - 9, foot[1] - 3, foot[0] + 3, foot[1] + 4, sock)

    def _fox_standing(self, c, now, pose, oy, swish, awake):
        """Walking (or standing) on four jointed legs, body level, tail streaming behind."""
        walking = abs(pose["legs"]) > 0.01
        kicking = self.activity is not None and now < self.activity.get("kick_until", 0)
        step = self.step if walking else 0.0
        bob = -1.6 * abs(math.sin(step * 2)) if walking else 0.0
        oy += bob
        ground = 291

        # long tail streaming behind, gently waving
        wave = 6 * math.sin(self.t * 2.6) + swish * 0.4
        tail = (Shape(172, 204 + oy).cubic(196, 186 + oy + wave * 0.3, 228, 190 + oy + wave * 0.6, 258, 202 + oy + wave)
                .cubic(240, 224 + oy + wave * 0.6, 206, 228 + oy + wave * 0.3, 176, 224 + oy).close())
        c.fill_stroke(tail, FOX_ORANGE)
        c.polygon([(232, 194 + oy + wave * 0.65), (258, 202 + oy + wave), (240, 219 + oy + wave * 0.7),
                   (243, 212 + oy + wave * 0.72), (234, 213 + oy + wave * 0.68), (237, 206 + oy + wave * 0.68),
                   (228, 205 + oy + wave * 0.62)], FOX_CREAM)

        # legs: a four-beat walk (each leg a quarter step after the last)
        legs = [  # (hip x, hip y, phase offset, knee bend, far side?)
            (148, 222, math.pi, 1, True),        # far hind leg
            (76, 224, math.pi * 1.5, -1, True),  # far front leg
        ]
        near = [(156, 224, 0.0, 1, False), (66, 226, math.pi / 2, -1, False)]
        for hip_x, hip_y, offset, bend, far in legs:
            self._fox_leg(c, (hip_x, hip_y + oy), self._paw(hip_x, offset, step, walking, ground),
                          bend, far)

        # body: long and level, with a cream throat and a speckled hip
        body = (Shape(50, 222 + oy).cubic(52, 204 + oy, 64, 196 + oy, 80, 196 + oy)
                .cubic(110, 193 + oy, 140, 195 + oy, 160, 196 + oy).cubic(180, 196 + oy, 186, 216 + oy, 178, 232 + oy)
                .cubic(168, 244 + oy, 150, 240 + oy, 140, 236 + oy).cubic(118, 232 + oy, 96, 238 + oy, 74, 240 + oy)
                .cubic(60, 240 + oy, 50, 234 + oy, 50, 222 + oy).close())
        c.fill_stroke(body, FOX_ORANGE)
        c.fill_stroke(Shape(140, 208 + oy).cubic(160, 206 + oy, 172, 220 + oy, 166, 238 + oy)
                      .cubic(156, 230 + oy, 148, 220 + oy, 140, 208 + oy).close(), FOX_SHADE)  # thigh
        for vx, vy in ((150, 206), (156, 205), (162, 207), (153, 211), (159, 211), (156, 216)):
            c.line(vx - 1.5, vy - 1.5 + oy, vx, vy + oy, FOX_CREAM, 1.2)  # little speckles
            c.line(vx, vy + oy, vx + 1.5, vy - 1.5 + oy, FOX_CREAM, 1.2)
        neck = Shape(52, 182 + oy).cubic(66, 172 + oy, 84, 184 + oy, 88, 200 + oy).line(54, 228 + oy) \
            .cubic(44, 214 + oy, 44, 194 + oy, 52, 182 + oy).close()
        c.fill_stroke(neck, FOX_ORANGE)
        c.fill_stroke(Shape(47, 189 + oy).cubic(53, 197 + oy, 53, 214 + oy, 55, 228 + oy)
                      .cubic(47, 222 + oy, 43, 207 + oy, 43, 195 + oy).close(), FOX_CREAM)  # throat

        for hip_x, hip_y, offset, bend, far in near:
            paw = self._paw(hip_x, offset, step, walking, ground)
            if kicking and hip_x < 100:
                paw = (hip_x - 30, ground - 22)  # front paw swings out to kick
            self._fox_leg(c, (hip_x, hip_y + oy), paw, bend, far)

        self._fox_head(c, now, -46, 44 + oy, awake, relaxed=False, size=0.85)

    @staticmethod
    def _paw(hip_x, offset, step, walking, ground):
        if not walking:
            return hip_x - 2, ground
        phase = step * 1.0 + offset
        stride, lift = 15, 10
        return hip_x - 2 + stride * math.cos(phase), ground - max(0.0, math.sin(phase)) * lift

    # ---- the realistic red fox (side view, facing left; mirrored to face right)

    @staticmethod
    def _zigzag(points_top, bottom_y, start_x, end_x, teeth, depth):
        """A strip whose lower edge is a fur fringe: top edge given, bottom zig-zags."""
        pts = list(points_top)
        for i in range(teeth, -1, -1):
            x = start_x + (end_x - start_x) * i / teeth
            pts.append((x, bottom_y + (depth if i % 2 else 0)))
        return pts

    @staticmethod
    def _rf_paw(hip_x, offset, step, walking, ground):
        """Plant the paw during stance, then lift and return it during swing.

        Stance speed matches the distance-based phase in the movement loop,
        keeping planted feet fixed on the desktop instead of skating.
        """
        if not walking:
            return hip_x - 2, ground
        phase = ((step + offset) / (2 * math.pi)) % 1
        if phase < 0.62:
            return hip_x - 17 + 30 * phase / 0.62, ground
        swing = (phase - 0.62) / 0.38
        ease = swing * swing * (3 - 2 * swing)
        return hip_x + 13 - 30 * ease, ground - 12 * math.sin(math.pi * swing) ** 2

    @staticmethod
    def _rf_fur(c, shape, bounds, downward=False):
        """Stable fine guard hairs, clipped to the silhouette; no frame noise."""
        left, top, right, bottom = bounds
        c.save()
        c.clip(shape)
        for row in range(int((bottom - top) / 5) + 1):
            for col in range(int((right - left) / 6) + 1):
                seed = (row * 37 + col * 19) % 23
                x = left + col * 6 + (seed % 5) * 0.6
                y = top + row * 5 + (seed % 3) * 0.7
                length = 2.5 + (seed % 4) * 0.6
                color = (RF_LIGHT if seed % 3 else RF_BACK, 0.28)
                c.line(x, y, x + (length * 0.35 if downward else length),
                       y + (length if downward else length * 0.4), color, 0.55)
        c.restore()

    def _rf_tufts(self, c, points, color, length=5, width=1.4):
        """Little fur tufts sticking out along an edge, pointing down/back."""
        for x, y in points:
            c.line(x, y, x + length * 0.5, y + length, color, width)

    def _rf_head(self, c, now, dx, dy, awake, relaxed, size=1.0):
        """A red fox head in profile facing left; (dx, dy) shifts it into place."""
        c.save()
        c.translate(dx, dy)
        if size != 1.0:  # grow or shrink around where the head meets the neck
            c.translate(84, 192)
            c.scale(size)
            c.translate(-84, -192)
        if self.state == "thinking":  # tilt the head while thinking
            c.translate(80, 180)
            c.rotate(-8 + 3 * math.sin(self.t * 1.5))
            c.translate(-80, -180)
        perk = -9 if self.state == "listening" else 2 * math.sin(self.t * 1.3)

        # tall ears with black backs (far ear first)
        for base, tip, front in (((80, 152), (90, 112), False), ((64, 154), (70, 110), True)):
            c.save()
            c.translate(base[0] + 8, base[1])
            twitch = 3 * max(0, math.sin(self.t * 0.7 + (0 if front else 2))) ** 12
            c.rotate(perk + twitch + (1.5 * math.sin(self.t * 1.1 + 1) if not front else 0))
            c.translate(-base[0] - 8, -base[1])
            outer = [(base[0] - 6, base[1] + 2), tip, (base[0] + 20, base[1] - 2)]
            c.polygon(outer, RF_BLACK if not front else RF_SIDE)
            if front:
                c.line(base[0] - 5, base[1] + 1, tip[0], tip[1], RF_BACK, 1.6)  # darker front edge
                c.polygon([(tip[0] - 4, tip[1] + 14), tip, (tip[0] + 6, tip[1] + 15)], RF_BLACK)  # black tip
            c.restore()

        # skull and long narrow snout
        head = (Shape(94, 162).cubic(92, 148, 80, 142, 68, 146).cubic(58, 150, 46, 160, 30, 168)
                .cubic(24, 171, 18, 172, 16, 175).cubic(18, 179, 24, 181, 32, 182)
                .cubic(42, 184, 50, 186, 56, 188).line(62, 194).line(66, 188).line(72, 196).line(76, 190)
                .line(82, 196).cubic(92, 188, 96, 176, 94, 162).close())
        c.gradient(head, (0, 142), (0, 196), [(0, RF_BACK), (0.35, RF_SIDE), (1, RF_LIGHT)])
        self._rf_fur(c, head, (30, 146, 94, 190))
        # white cheeks and lower jaw, with a fluffy edge
        cheek = [(20, 179), (34, 178), (48, 175), (60, 174), (70, 178), (78, 186), (82, 196), (76, 190),
                 (72, 196), (66, 188), (62, 194), (56, 188), (44, 185), (30, 183)]
        c.polygon(cheek, RF_WHITE)
        c.oval(13, 171, 21, 178, RF_BLACK)  # nose
        c.line(20, 180, 38, 180.5, "#4a2a1e", 1.2)  # mouth line
        if self.state == "speaking":
            opening = 1 + 5 * sum(self.mouth) / len(self.mouth)
            c.polygon([(21, 180), (42, 181), (26, 180 + opening)], "#5a1f18")

        # amber eye with a slit pupil and a dark tear line
        ex, ey = 56, 160
        open_amount = self._eye_open_amount(now, 1.0)
        squint = relaxed and not awake and self.activity is None and not self.dragging
        if squint and open_amount > 0.2:
            open_amount = 0.45  # a calm, half-closed look
        c.line(ex - 7, ey + 3, ex - 18, ey + 10, "#5a2c18", 2)  # tear line toward the muzzle
        if open_amount < 0.2:
            c.line(ex - 7, ey, ex + 6, ey - 1, RF_BLACK, 2)
        else:
            h = 4.5 * open_amount
            eye = Shape(ex - 7, ey).cubic(ex - 3, ey - h, ex + 3, ey - h, ex + 7, ey - 1) \
                .cubic(ex + 3, ey + h * 0.8, ex - 3, ey + h * 0.8, ex - 7, ey).close()
            c.fill_stroke(eye, RF_EYE, RF_BLACK, 1.4)
            look = -1.5 if not self.look[0] else -abs(self.look[0]) * 0.3
            c.line(ex + look, ey - h * 0.8, ex + look, ey + h * 0.7, RF_BLACK, 1.8)  # slit pupil
            c.oval(ex + 2, ey - 2.5, ex + 3.6, ey - 1, "#ffffff")
        for wy, wx in ((179, 4), (181, 8), (183, 2)):  # whiskers
            c.line(26, wy - 1, 26 - 14, wy + wx * 0.5 - 2, ("#ffffff", 0.7), 0.8)
        c.restore()

    def _rf_tail(self, c, base_x, base_y, angle, wrap=False):
        """A big bushy tail: darker on top, greyish underneath, white tip, fluffy edge."""
        c.save()
        c.translate(base_x, base_y)
        c.rotate(angle)
        if wrap:  # curled along the ground around the paws (sitting)
            outer = (Shape(0, 0).cubic(10, 16, -10, 30, -50, 32).cubic(-80, 33, -104, 28, -116, 18)
                     .cubic(-110, 10, -92, 12, -70, 13).cubic(-40, 14, -14, 8, -8, -4).close())
            tip = [(-116, 18), (-104, 27), (-96, 31), (-94, 25), (-90, 31), (-88, 22), (-84, 27), (-84, 15),
                   (-96, 12), (-108, 11)]
            c.gradient(outer, (0, 0), (0, 33), [(0, RF_BACK), (0.5, RF_SIDE), (1, RF_GREY)])
            c.polygon(tip, RF_WHITE)
        else:  # streaming out behind (standing / walking)
            wave = 3 * math.sin(self.t * 1.8 - 0.7)
            outer = (Shape(0, 0).cubic(24, -14, 52, -10 + wave * 0.5, 82, 2 + wave).cubic(70, 22 + wave, 40, 28 + wave * 0.5, 4, 22).close())
            tip = [(82, 2), (66, -6), (60, -3), (64, 2), (58, 4), (63, 9), (57, 12), (64, 15), (72, 16)]
            c.gradient(outer, (0, -14), (0, 28), [(0, RF_BACK), (0.45, RF_SIDE), (1, RF_GREY)])
            tip = [(x, y + wave * max(0, (x - 40) / 42)) for x, y in tip]
            c.polygon(tip, RF_WHITE)
            self._rf_fur(c, outer, (6, -10, 78, 25))
            self._rf_tufts(c, [(14, 22), (26, 24), (38, 25), (50, 23)], RF_GREY, 4, 1.6)
        c.restore()

    def _rf_leg(self, c, hip, foot, bend, far, hind):
        knee = self._knee(hip, foot, 30, 36, bend)
        fur = RF_BACK if far else RF_SIDE
        black = "#140e0b" if far else RF_BLACK
        c.line(hip[0], hip[1], knee[0], knee[1], fur, 15 if hind else 8)
        mid = (knee[0] + (foot[0] - knee[0]) * 0.15, knee[1] + (foot[1] - knee[1]) * 0.15)
        c.line(knee[0], knee[1], mid[0], mid[1], fur, 7)
        c.line(mid[0], mid[1], foot[0], foot[1], black, 5.5)  # black stocking
        c.oval(foot[0] - 7, foot[1] - 2.5, foot[0] + 3, foot[1] + 3, black)

    def _real_fox_standing(self, c, now, pose, oy, swish, awake):
        walking = pose.get("walking", abs(pose["legs"]) > 0.01)
        kicking = self.activity is not None and now < self.activity.get("kick_until", 0)
        step = self.step if walking else 0.0
        ground = 291

        self._rf_tail(c, 176, 204 + oy, -8 + 0.6 * swish + 4 * math.sin(self.t * 2.6))
        for hip_x, hip_y, offset, bend, hind in ((148, 220, math.pi, 1, True), (78, 222, math.pi * 1.5, -1, False)):
            self._rf_leg(c, (hip_x, hip_y + oy), self._rf_paw(hip_x, offset, step, walking, ground), bend, True, hind)

        # body: slightly arched back, deep chest, tucked belly
        body = (Shape(54, 214 + oy).cubic(52, 200 + oy, 60, 192 + oy, 74, 190 + oy)
                .cubic(96, 186 + oy, 120, 192 + oy, 140, 190 + oy).cubic(160, 188 + oy, 178, 194 + oy, 182, 208 + oy)
                .cubic(186, 222 + oy, 178, 236 + oy, 166, 238 + oy).cubic(150, 240 + oy, 140, 232 + oy, 128, 230 + oy)
                .cubic(110, 228 + oy, 92, 236 + oy, 78, 238 + oy).cubic(62, 238 + oy, 54, 228 + oy, 54, 214 + oy).close())
        c.gradient(body, (0, 186 + oy), (0, 240 + oy), [(0, RF_BACK), (0.4, RF_SIDE), (1, RF_LIGHT)])
        self._rf_fur(c, body, (54, 190 + oy, 182, 240 + oy))
        self._rf_tufts(c, [(76, 236 + oy), (88, 235 + oy), (100, 233 + oy), (112, 231 + oy)],
                       ("#f4eee5", 0.85), 4, 1.6)  # pale fluffy belly
        neck = (Shape(52, 186 + oy).cubic(64, 176 + oy, 82, 182 + oy, 88, 196 + oy).line(56, 224 + oy)
                .cubic(46, 210 + oy, 46, 194 + oy, 52, 186 + oy).close())
        c.gradient(neck, (0, 176 + oy), (0, 224 + oy), [(0, RF_BACK), (0.5, RF_SIDE), (1, RF_LIGHT)])
        c.polygon([(40, 190 + oy), (48, 196 + oy), (53, 206 + oy), (57, 216 + oy), (55, 228 + oy), (50, 222 + oy),
                   (51, 214 + oy), (45, 214 + oy), (47, 206 + oy), (41, 204 + oy), (43, 196 + oy)], RF_WHITE)  # chest
        self._rf_tufts(c, [(150, 236 + oy), (160, 237 + oy), (170, 233 + oy)], RF_SIDE, 5, 2)  # fluffy thigh

        for hip_x, hip_y, offset, bend, hind in ((156, 222, 0.0, 1, True), (66, 224, math.pi / 2, -1, False)):
            paw = self._rf_paw(hip_x, offset, step, walking, ground)
            if kicking and not hind:
                paw = (hip_x - 30, ground - 22)  # front paw swings out to kick
            self._rf_leg(c, (hip_x, hip_y + oy), paw, bend, False, hind)

        self._rf_head(c, now, 0, oy + (0.7 * math.sin(step - 0.4) if walking else 0), awake, relaxed=False)

    def _real_fox_sitting(self, c, now, pose, oy, swish, awake):
        # haunch and back, sitting upright
        body = (Shape(108, 146 + oy).cubic(146, 156 + oy, 170, 212 + oy, 166, 260 + oy)
                .cubic(164, 286 + oy, 148, 296 + oy, 124, 296 + oy).line(104, 296 + oy)
                .cubic(98, 268 + oy, 92, 230 + oy, 96, 204 + oy).cubic(98, 180 + oy, 98, 162 + oy, 108, 146 + oy).close())
        c.gradient(body, (100, 0), (170, 0), [(0, RF_LIGHT), (0.45, RF_SIDE), (1, RF_BACK)])
        c.fill_stroke(Shape(146, 232 + oy).cubic(162, 248 + oy, 164, 276 + oy, 148, 292 + oy)
                      .cubic(156, 270 + oy, 154, 250 + oy, 146, 232 + oy).close(), RF_BACK)  # haunch shading
        self._rf_fur(c, body, (98, 154 + oy, 168, 296 + oy), downward=True)
        # white chest with a fluffy fringe
        chest = [(84, 150 + oy), (98, 158 + oy), (110, 176 + oy), (116, 200 + oy), (116, 222 + oy), (110, 236 + oy),
                 (106, 230 + oy), (104, 240 + oy), (100, 230 + oy), (96, 236 + oy), (95, 222 + oy), (91, 226 + oy),
                 (93, 208 + oy), (89, 206 + oy), (92, 190 + oy), (88, 176 + oy)]
        c.polygon(chest, RF_WHITE)
        # front legs: orange at the top, black stockings below
        waving = ((self.activity is not None and self.activity["name"] == "wave")
                  or (self.activity is None and not awake and self.action["name"] == "wave"))
        for i, (top_x, paw_x) in enumerate(((104, 98), (116, 114))):
            if waving and i == 0:
                lift = 8 * math.sin(self.t * 10)
                c.line(top_x, 230 + oy, 92, 226 + oy, RF_SIDE, 9)
                c.line(92, 226 + oy, 78, 220 + oy + lift, RF_BLACK, 6)
                c.oval(70, 215 + oy + lift, 82, 224 + oy + lift, RF_BLACK)
                continue
            dangle = 6 if self.dragging else 0
            c.line(top_x, 230 + oy, (top_x + paw_x) / 2, 256 + oy, RF_SIDE if i else RF_BACK, 9)
            c.line((top_x + paw_x) / 2, 254 + oy, paw_x, 292 + oy + dangle, RF_BLACK, 6)
            c.oval(paw_x - 9, 289 + oy + dangle, paw_x + 4, 296 + oy + dangle, RF_BLACK)
        # tail wrapped around the paws
        self._rf_tail(c, 160, 262 + oy, swish * 0.3, wrap=True)
        self._rf_head(c, now, 30, -40 + oy, awake, relaxed=True, size=1.18)

    def _draw_caption(self, c, now):
        if not self.caption or now > self.caption_until:
            return
        caption = self.caption if len(self.caption) <= 110 else self.caption[:107] + "..."
        size = 11
        text_w, text_h = c.measure(caption, size, self.W - 24)
        cx = self.W / 2
        tip = self.CAPTION_H + (98 - DESIGN_TOP) * self.scale - 2
        bottom = tip - 8
        height = min(text_h + 12, bottom - 1)
        left, top, width = cx - text_w / 2 - 8, bottom - height, text_w + 16
        c.rrect(left, top, left + width, bottom, 10, "#ffffff", SHADE, 1)
        c.polygon([(cx - 6, bottom - 1), (cx + 6, bottom - 1), (cx, tip)], "#ffffff")
        c.text_box(left, top, width, height, caption, size, "#1d232b")
