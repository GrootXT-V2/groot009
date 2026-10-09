"""Groot the desktop robot.

A little robot walks and plays around your screen. Say "Hey Groot" (or click
it) and it stops to listen and talk. Say "stop" or "you can stop" (or click it
again) and it goes back to playing.

Run with:  python -m groot --gui
"""

import math
import queue
import random
import re
import sys
import threading
import time

from .voice import i_am_groot

STOP_PHRASES = {
    "stop", "stop it", "stop listening", "stop talking", "that's all", "thats all",
    "that is all", "goodbye", "bye", "bye bye", "go to sleep", "sleep", "exit", "quit",
    "shut up", "be quiet", "thank you that's all", "thanks that's all",
    "you can stop", "you can stop now", "ok stop", "okay stop", "that's enough",
    "thats enough", "you can go", "you can go now", "go play", "go and play",
}

# Speech recognition often hears "Groot" as one of these
GROOT_SOUNDS = {"groot", "grut", "grute", "groote", "grooot", "gruit", "group", "groups",
                "root", "grout", "gru", "grew", "brute", "groove"}
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "a", "yo", "hay", "he", "hei", "oi"}


def _clean(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


def is_stop_command(text: str) -> bool:
    cleaned = re.sub(r"^(hey groot|groot)\s+", "", _clean(text))
    if cleaned in STOP_PHRASES or cleaned.startswith("stop "):
        return True
    words = cleaned.split()
    while words and words[-1] in ("now", "please", "groot", "buddy"):
        words.pop()
    # short phrases ending in "stop", like "okay you can stop now" (but not "don't stop")
    return bool(words) and words[-1] == "stop" and len(words) <= 5 and "don't" not in words


def find_wake_word(text: str):
    """If the text starts with "Hey Groot", return what was said after it
    ('' if nothing). Return None if Groot wasn't called."""
    words = _clean(text).split()
    for i, word in enumerate(words[:4]):
        if word not in GROOT_SOUNDS:
            continue
        greeted = i > 0 and words[i - 1] in GREETINGS
        if word == "groot" or greeted:
            return " ".join(words[i + 1:])
    return None


class Session:
    """Listens in the background: waits for "Hey Groot" while asleep, then
    has a conversation (listen -> think -> speak) until told to stop."""

    def __init__(self, brain, speaker, listen, on_state, on_text, name="Groot", groot_mode=False):
        self.brain = brain
        self.speaker = speaker
        self.listen = listen
        self.on_state = on_state
        self.on_text = on_text
        self.name = name
        self.groot_mode = groot_mode  # only say "I am Groot" out loud; show the real answer
        self._awake = threading.Event()
        self._quit = threading.Event()
        self._greet = False
        self._first_command = None

    @property
    def active(self) -> bool:
        return self._awake.is_set()

    def toggle(self) -> None:
        if self.active:
            self.stop()
        else:
            self.start()

    def start(self, first_command: str = None) -> None:
        if self.active:
            return
        self._first_command = first_command
        self._greet = True
        self._awake.set()
        self.on_state("listening")

    def stop(self) -> None:
        self._awake.clear()
        self.speaker.stop()
        self.on_state("idle")
        self.on_text("")

    def quit(self) -> None:
        self._quit.set()
        self.stop()

    def launch(self) -> None:
        threading.Thread(target=self.run_forever, daemon=True).start()

    def run_forever(self) -> None:
        while not self._quit.is_set():
            try:
                if self._awake.is_set():
                    self._conversation_turn()
                else:
                    self._wake_word_turn()
            except Exception as exc:
                print(f"[error: {exc}]")
                time.sleep(1)

    def _wake_word_turn(self) -> None:
        heard = self.listen(timeout=2)
        if self._awake.is_set() or not heard:
            return
        command = find_wake_word(heard)
        if command is not None:
            print(f"Heard: {heard}")
            self.start(first_command=command or None)

    def _conversation_turn(self) -> None:
        if self._greet:
            self._greet = False
            command, self._first_command = self._first_command, None
            if command:
                self._handle(command)
            else:
                self._say("Hi! I'm listening.")
            return
        self.on_state("listening")
        self.on_text("Listening...")
        heard = self.listen(timeout=2)
        if heard and self._awake.is_set():
            self._handle(heard)

    def _handle(self, heard: str) -> None:
        self.on_text(f"You: {heard}")
        if is_stop_command(heard):
            self._say("Okay! I'll go play. Say hey Groot if you need me.")
            self.stop()
            return
        self.on_state("thinking")
        try:
            answer = self.brain.reply(heard)
        except Exception as exc:
            print(f"[error: {exc}]")
            answer = "Sorry, something went wrong. Please try again."
        self._say(answer)

    def _say(self, text: str) -> None:
        if not self._awake.is_set():
            return
        self.on_state("speaking")
        self.on_text(f"{self.name}: {text}")
        self.speaker.say(i_am_groot(text) if self.groot_mode else text)


# ---------------------------------------------------------------- the robot

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


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


class Robot:
    """The always-on-top robot window that wanders around the screen."""

    W, H = 240, 310
    TICK_MS = 40
    SPEED = 2.4  # pixels per tick while walking

    def __init__(self, root, name="Groot"):
        import tkinter as tk

        self.root = root
        self.name = name
        self.session = None
        self.state = "loading"
        self.caption = "Getting ready..."
        self.caption_until = float("inf")
        self.events = queue.Queue()

        # animation state
        self.t = 0.0
        self.action = {"name": "rest", "start": time.monotonic(), "until": time.monotonic() + 2}
        self.next_blink = time.monotonic() + 3
        self.blink_until = 0.0
        self.look = (0.0, 0.0)
        self.dragging = False
        self.mouth = [0.3] * 5

        root.title(name)
        root.overrideredirect(True)  # no title bar
        root.attributes("-topmost", True)  # stay above other windows
        bg = self._transparent_background()
        self.sw, self.sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.x = float(self.sw - self.W - 40)
        self.y = float(self.sh - self.H - 80)
        root.geometry(f"{self.W}x{self.H}+{int(self.x)}+{int(self.y)}")

        self.canvas = tk.Canvas(root, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack()

        self.stay_still = tk.BooleanVar(value=False)
        self.tree_voice = tk.BooleanVar(value=False)
        self.groot_mode = tk.BooleanVar(value=False)
        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="Talk / Stop", command=self.toggle)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Stay still", variable=self.stay_still)
        self.menu.add_checkbutton(label="Little Groot voice", variable=self.tree_voice,
                                  command=self._apply_settings)
        self.menu.add_checkbutton(label='"I am Groot" mode', variable=self.groot_mode,
                                  command=self._apply_settings)
        self.menu.add_separator()
        self.menu.add_command(label=f"Quit {name}", command=self.quit)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        for button in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.canvas.bind(button, self._show_menu)

        self._tick()

    def _transparent_background(self) -> str:
        if sys.platform == "darwin":
            try:
                self.root.attributes("-transparent", True)
                self.root.config(bg="systemTransparent")
                return "systemTransparent"
            except Exception:
                pass
        if sys.platform == "win32":
            try:
                self.root.attributes("-transparentcolor", "#010101")
                self.root.config(bg="#010101")
                return "#010101"
            except Exception:
                pass
        return "#1e1e1e"

    # ---- thread-safe updates (background threads put, the UI thread applies)

    def set_state(self, state: str) -> None:
        self.events.put(("state", state))

    def set_text(self, text: str, seconds: float = None) -> None:
        self.events.put(("text", (text, seconds)))

    def set_session(self, session) -> None:
        self.events.put(("session", session))

    # ---- mouse

    def _press(self, event):
        self._start = (event.x_root, event.y_root, self.x, self.y)
        self._moved = False

    def _drag(self, event):
        sx, sy, wx, wy = self._start
        dx, dy = event.x_root - sx, event.y_root - sy
        if abs(dx) + abs(dy) > 4:
            self._moved = True
            self.dragging = True
        self.x, self.y = wx + dx, wy + dy
        self._place()

    def _release(self, event):
        self.dragging = False
        if not getattr(self, "_moved", True):
            self.toggle()
        else:
            self._new_action("rest")

    def _show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def _apply_settings(self):
        if self.session is not None:
            self.session.groot_mode = self.groot_mode.get()
            self.session.speaker.tree_voice = self.tree_voice.get()

    def toggle(self):
        if self.session is not None:
            self.session.toggle()

    def quit(self):
        if self.session is not None:
            self.session.quit()
        self.root.destroy()

    # ---- behaviour

    def _new_action(self, name=None):
        now = time.monotonic()
        if name is None:
            name = random.choices(
                ["walk", "rest", "look", "wave", "jump", "dance"],
                weights=[40, 20, 15, 10, 10, 5],
            )[0]
        action = {"name": name, "start": now}
        if name == "walk":
            action["target"] = (
                random.uniform(10, self.sw - self.W - 10),
                random.uniform(40, self.sh - self.H - 60),
            )
            action["until"] = now + 20
        else:
            action["until"] = now + {"rest": random.uniform(2, 4), "look": 2.5, "wave": 2,
                                     "jump": 1.2, "dance": 3}[name]
        self.action = action

    def _place(self):
        self.x = min(max(self.x, 0), self.sw - self.W)
        self.y = min(max(self.y, 25), self.sh - self.H)
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

    def _update_behaviour(self, now):
        """Move the robot and return its pose for this frame."""
        pose = {"bob": 0.0, "legs": 0.0, "left_arm": 115.0, "right_arm": 65.0, "lift": 0.0}
        awake = self.state not in ("idle", "loading", "error")

        if self.dragging:  # picked up: arms flail a little
            pose.update(left_arm=200 + 10 * math.sin(self.t * 6), right_arm=-20 - 10 * math.sin(self.t * 6))
            self.look = (0, -4)
            return pose

        if awake or self.stay_still.get():
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

    # ---- main loop

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
                self.tree_voice.set(value.speaker.tree_voice)
                self.groot_mode.set(value.groot_mode)

        now = time.monotonic()
        self.t += self.TICK_MS / 1000
        if now > self.next_blink:
            self.blink_until = now + 0.15
            self.next_blink = now + random.uniform(2.5, 6)
        pose = self._update_behaviour(now)
        self._draw(pose, now)
        self.root.after(self.TICK_MS, self._tick)

    # ---- drawing

    def _draw(self, pose, now):
        c = self.canvas
        c.delete("all")
        cx = self.W / 2
        oy = pose["bob"] - pose["lift"]  # vertical offset of the whole robot
        glow = EYE_COLORS.get(self.state, EYE_COLORS["idle"])

        # legs and feet
        for side, phase in ((-1, pose["legs"]), (1, -pose["legs"])):
            lx = cx + side * 18
            up = 0 if self.dragging else max(0.0, phase) * 7
            rounded_rect(c, lx - 10, 248 + oy - up, lx + 10, 284 + oy - up, 8, fill=WHITE, outline=SHADE, width=2)
            c.create_line(lx - 8, 268 + oy - up, lx + 8, 268 + oy - up, fill="#e0b84a", width=2)
            rounded_rect(c, lx - 15, 280 + oy - up, lx + 15, 298 + oy - up, 8, fill=DARK, outline=DARK)

        # arms (drawn behind the body)
        for shoulder_x, angle in ((cx - 36, pose["left_arm"]), (cx + 36, pose["right_arm"])):
            sy = 212 + oy
            rad = math.radians(angle)
            hx, hy = shoulder_x + 38 * math.cos(rad), sy + 38 * math.sin(rad)
            c.create_line(shoulder_x, sy, hx, hy, fill=SHADE, width=17, capstyle="round")
            c.create_line(shoulder_x, sy, hx, hy, fill=WHITE, width=13, capstyle="round")
            c.create_oval(shoulder_x - 8, sy - 8, shoulder_x + 8, sy + 8, fill=DARK, outline=DARK)
            c.create_oval(hx - 9, hy - 9, hx + 9, hy + 9, fill=DARK, outline=DARK)

        # body
        c.create_rectangle(cx - 14, 188 + oy, cx + 14, 202 + oy, fill=DARK, outline=DARK)  # neck
        rounded_rect(c, cx - 38, 196 + oy, cx + 38, 256 + oy, 24, fill=WHITE, outline=SHADE, width=2)
        c.create_arc(cx - 24, 214 + oy, cx + 24, 248 + oy, start=200, extent=140, style="arc",
                     outline=SHADE, width=2)
        d, ly = 5, 214 + oy  # little chest light
        c.create_polygon(cx, ly - d, cx + d, ly, cx, ly + d, cx - d, ly,
                         fill=glow if self.state == "speaking" else "#f0a030", outline="")

        # head
        rounded_rect(c, cx - 66, 98 + oy, cx + 66, 196 + oy, 40, fill=WHITE, outline=SHADE, width=2)
        rounded_rect(c, cx - 30, 110 + oy, cx + 30, 117 + oy, 3, fill=DARK, outline=DARK)  # forehead slit
        for side in (-1, 1):  # headphones
            hx = cx + side * 70
            rounded_rect(c, hx - 9, 126 + oy, hx + 9, 172 + oy, 8, fill=DARK, outline=DARK)
            c.create_line(hx - 3 * side, 132 + oy, hx - 3 * side, 166 + oy, fill=glow, width=2)

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
                c.create_line(ex - 18, ey, ex + 18, ey, fill=EYE_DARK, width=4, capstyle="round")
                continue
            ry = 23 * open_amount
            c.create_oval(ex - 25, ey - ry - 2, ex + 25, ey + ry + 2, fill=glow, outline="")
            c.create_oval(ex - 20, ey - ry + 3, ex + 20, ey + ry - 3, fill=EYE_DARK, outline="")
            px, py = ex + look_x, ey + look_y * open_amount
            c.create_oval(px - 13, py - 13 * open_amount, px + 13, py + 13 * open_amount, outline=glow, width=2)
            c.create_oval(px - 10, py - 10 * open_amount, px + 10, py + 10 * open_amount, fill="#000000", outline="")
            c.create_oval(px - 6, py - 7, px - 1, py - 2, fill="white", outline="")

        # mouth: a little light bar that moves when speaking
        my = 180 + oy
        if self.state == "speaking":
            self.mouth = [max(0.15, min(1.0, m + random.uniform(-0.35, 0.35))) for m in self.mouth]
            for i, level in enumerate(self.mouth):
                bx = cx - 12 + i * 6
                c.create_line(bx, my - 5 * level, bx, my + 5 * level, fill=glow, width=3, capstyle="round")
        else:
            rounded_rect(c, cx - 8, my - 2, cx + 8, my + 2, 2, fill=DARK, outline=DARK)

        # sleepy zzz while resting
        if resting:
            z = (now * 0.8) % 1
            c.create_text(cx + 55, 95 + oy - 20 * z, text="z", fill="#8fa3b5",
                          font=("Helvetica", int(10 + 6 * z), "bold"))

        self._draw_caption(now)

    def _draw_caption(self, now):
        if not self.caption or now > self.caption_until:
            return
        c = self.canvas
        cx = self.W / 2
        caption = self.caption if len(self.caption) <= 110 else self.caption[:107] + "..."
        text_id = c.create_text(cx, 48, text=caption, fill="#1d232b", width=self.W - 30,
                                font=("Helvetica", 11), justify="center")
        x1, y1, x2, y2 = c.bbox(text_id)
        box = rounded_rect(c, x1 - 10, y1 - 7, x2 + 10, y2 + 7, 12, fill="white", outline=SHADE, width=1)
        tail = c.create_polygon(cx - 8, y2 + 6, cx + 8, y2 + 6, cx, y2 + 16, fill="white", outline="")
        c.tag_lower(tail, text_id)
        c.tag_lower(box, tail)


def run_gui(config, brain_kind: str) -> None:
    try:
        import tkinter as tk
    except ImportError:
        sys.exit(
            "The desktop robot needs Tkinter.\n"
            "On Mac run:  brew install python-tk\n"
            "then delete the .venv folder and set it up again."
        )

    from .__main__ import make_brain
    from .skills import Skills
    from .voice import Listener, Speaker

    root = tk.Tk()
    robot = Robot(root, name=config.name)

    def load():
        # Microphone calibration and loading the brain take a few seconds,
        # so do it in the background while the robot shows "Getting ready..."
        try:
            speaker = Speaker(rate=config.voice_rate, voice=config.voice, tree_voice=config.tree_voice,
                              pitch=config.voice_pitch, engine=config.tts,
                              edge_voice=config.edge_voice, edge_pitch=config.edge_pitch)

            def announce(text):  # used by timers
                robot.set_text(f"{config.name}: {text}", seconds=8)
                speaker.say(text)

            skills = Skills(config.data_dir, default_city=config.city, announce=announce)
            brain = make_brain(config, brain_kind, skills)
            robot.set_text("Checking microphone...")
            ears = Listener(engine=config.stt_engine, whisper_model=config.whisper_model)
            session = Session(brain, speaker, lambda timeout=None: ears.listen(timeout=timeout),
                              robot.set_state, robot.set_text, name=config.name,
                              groot_mode=config.i_am_groot)
            robot.set_session(session)
            robot.set_state("idle")
            robot.set_text('Say "Hey Groot" or click me!', seconds=6)
            session.launch()
            print(f'{config.name} is ready. Say "Hey Groot" or click the robot; right-click it to quit.')
        except Exception as exc:
            print(f"[error starting {config.name}: {exc}]")
            robot.set_state("error")
            robot.set_text(f"Couldn't start: {exc}")

    threading.Thread(target=load, daemon=True).start()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
