"""Groot the desktop buddy: how it behaves and how it's drawn.

This file doesn't depend on any window system. A window (native AppKit on
Mac, Qt elsewhere) calls tick() about 30 times a second, moves itself to
(buddy.x, buddy.y), and asks the buddy to draw() itself on a Canvas.
"""

import math
import queue
import random
import time
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
        self.W = int(max(DESIGN_W * size, 190))
        self.H = int(self.CAPTION_H + DESIGN_H * size)
        self.speed = 1.6 * max(size, 0.4)  # walking speed in pixels per frame
        self.on_quit = lambda: None  # set by the window

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
        self._press = None
        self._moved = False
        self.step = 0.0  # walking cycle
        self.turn = 0.0  # -1 facing left, 0 facing you, 1 facing right
        self.fall_speed = 0.0
        self.activity = None  # something you asked Groot to do, like playing football
        self.props = []  # toys on screen (each gets its own little window)

        self.set_area(area)
        self.x = float(area.right - self.W - 30)
        self.y = self.floor

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

    def tick(self, now=None):
        """Advance one frame. The window then moves to (x, y) and redraws."""
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
            elif kind == "perform":
                self._start_activity(value)
            elif kind == "session":
                self.session = value
                self.little_voice = value.speaker.tree_voice
                self.groot_mode = value.groot_mode

        now = time.monotonic() if now is None else now
        self.t += self.FRAME
        if now > self.next_blink:
            self.blink_until = now + 0.15
            self.next_blink = now + random.uniform(2.5, 6)
        self.pose = self._update_behaviour(now)
        if self.state == "speaking":
            self.mouth = [max(0.15, min(1.0, m + random.uniform(-0.35, 0.35))) for m in self.mouth]

    # ---- drawing

    # ---- on-screen activities

    def _start_activity(self, name):
        self._end_activity(wave=False)
        if name not in ACTIVITIES:
            return
        now = time.monotonic()
        self.activity = {"name": name, "start": now, "until": now + ACTIVITIES[name], "kick_until": 0.0,
                         "kick_dir": 1, "jump_start": -10.0, "target": None, "retarget": 0.0}
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
        if wave:
            self._new_action("wave")

    def _do_activity(self, now, pose, awake):
        a = self.activity
        name = a["name"]
        elapsed = now - a["start"]
        facing = 0.0
        if now > a["until"] or (name == "sleep" and awake):
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
        self.step += speed * 0.12 / max(self.scale, 0.4)
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
        c.translate(self.W / 2 - (DESIGN_LEFT + DESIGN_W / 2) * self.scale, self.CAPTION_H - DESIGN_TOP * self.scale)
        c.scale(self.scale)
        lean = self.pose.get("lean", 0.0)
        if lean:  # tilt the whole body around its feet
            c.translate(CX, 298)
            c.rotate(lean)
            c.translate(-CX, -298)
        if self.style == "robot":
            self._draw_robot(c, now)
        else:
            self._draw_tree(c, now)
        c.restore()
        self._draw_caption(c, now)

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
