"""A floating Groot bubble: click to start talking, click again (or say "stop") to stop.

Run with:  python -m groot --gui
"""

import math
import queue
import re
import sys
import threading

from .voice import i_am_groot

STOP_PHRASES = {
    "stop", "stop it", "stop listening", "stop talking", "that's all", "thats all",
    "that is all", "goodbye", "bye", "bye bye", "go to sleep", "sleep", "exit", "quit",
    "shut up", "be quiet", "thank you that's all", "thanks that's all",
}


def is_stop_command(text: str) -> bool:
    cleaned = re.sub(r"[^\w\s']", "", text.lower()).strip()
    cleaned = re.sub(r"^(groot|hey groot)\s+", "", cleaned)
    return cleaned in STOP_PHRASES or cleaned.startswith("stop ")


class Session:
    """One conversation: listen -> think -> speak, until stopped.

    Runs in a background thread so the bubble stays responsive.
    """

    def __init__(self, brain, speaker, listen, on_state, on_text, name="Groot", groot_mode=False):
        self.groot_mode = groot_mode  # only say "I am Groot" out loud; show the real answer
        self.brain = brain
        self.speaker = speaker
        self.listen = listen
        self.on_state = on_state
        self.on_text = on_text
        self.name = name
        self._current = None  # Event for the running conversation, if any

    @property
    def active(self) -> bool:
        return self._current is not None and self._current.is_set()

    def toggle(self) -> None:
        if self.active:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.active:
            return
        running = threading.Event()
        running.set()
        self._current = running
        threading.Thread(target=self._run, args=(running,), daemon=True).start()

    def stop(self) -> None:
        if self._current is not None:
            self._current.clear()
        self.speaker.stop()
        self.on_state("idle")
        self.on_text("Click me to talk")

    def _say(self, running, text: str) -> None:
        if not running.is_set():
            return
        self.on_state("speaking")
        self.on_text(f"{self.name}: {text}")
        self.speaker.say(i_am_groot(text) if self.groot_mode else text)

    def _run(self, running) -> None:
        try:
            self._say(running, "Hi! I'm listening.")
            while running.is_set():
                self.on_state("listening")
                self.on_text("Listening...")
                heard = self.listen(timeout=2)
                if not running.is_set():
                    break
                if not heard:
                    continue
                self.on_text(f"You: {heard}")
                if is_stop_command(heard):
                    self._say(running, "Okay, talk to you later.")
                    break
                self.on_state("thinking")
                try:
                    answer = self.brain.reply(heard)
                except Exception as exc:
                    print(f"[error: {exc}]")
                    answer = "Sorry, something went wrong. Please try again."
                self._say(running, answer)
        finally:
            running.clear()
            if self._current is running:
                self.on_state("idle")
                self.on_text("Click me to talk")


class Bubble:
    """The little always-on-top window."""

    WIDTH, HEIGHT = 230, 150
    RADIUS = 34
    COLORS = {  # (fill, ring)
        "loading": ("#2b2f33", "#6b7278"),
        "idle": ("#2b2f33", "#8a9299"),
        "listening": ("#14583a", "#3ddc84"),
        "thinking": ("#5c430c", "#f5b82e"),
        "speaking": ("#123d6b", "#4aa3ff"),
        "error": ("#5c1515", "#ff5c5c"),
    }

    def __init__(self, root, name="Groot"):
        import tkinter as tk

        self.root = root
        self.name = name
        self.session = None
        self.state = "loading"
        self.caption = "Getting ready..."
        self.phase = 0.0
        self.events = queue.Queue()

        root.title(name)
        root.overrideredirect(True)  # no title bar
        root.attributes("-topmost", True)  # stay above other windows
        bg = self._transparent_background()
        x = root.winfo_screenwidth() - self.WIDTH - 30
        y = root.winfo_screenheight() - self.HEIGHT - 90
        root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        self.canvas = tk.Canvas(root, width=self.WIDTH, height=self.HEIGHT, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        self.tree_voice = tk.BooleanVar(value=False)
        self.groot_mode = tk.BooleanVar(value=False)
        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="Talk / Stop", command=self.toggle)
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Groot voice (deep tree voice)", variable=self.tree_voice,
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

    def set_text(self, text: str) -> None:
        self.events.put(("text", text))

    def set_session(self, session) -> None:
        self.events.put(("session", session))

    # ---- mouse

    def _press(self, event):
        self._start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._moved = False

    def _drag(self, event):
        sx, sy, wx, wy = self._start
        dx, dy = event.x_root - sx, event.y_root - sy
        if abs(dx) + abs(dy) > 4:
            self._moved = True
        self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _release(self, event):
        if not getattr(self, "_moved", True):
            self.toggle()

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
            self.session.stop()
        self.root.destroy()

    # ---- drawing

    def _tick(self):
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "state":
                self.state = value
            elif kind == "text":
                self.caption = value
            elif kind == "session":
                self.session = value
                self.tree_voice.set(value.speaker.tree_voice)
                self.groot_mode.set(value.groot_mode)
        self.phase += 0.15
        self._draw()
        self.root.after(50, self._tick)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        fill, ring = self.COLORS.get(self.state, self.COLORS["idle"])
        cx, cy, r = self.WIDTH / 2, 50, self.RADIUS

        if self.state in ("listening", "speaking"):
            speed = 1.0 if self.state == "listening" else 2.0
            for i in range(2):
                grow = (math.sin(self.phase * speed - i * 1.5) + 1) / 2 * 10
                c.create_oval(cx - r - 4 - grow, cy - r - 4 - grow, cx + r + 4 + grow, cy + r + 4 + grow,
                              outline=ring, width=2)
        elif self.state in ("thinking", "loading"):
            start = (self.phase * 60) % 360
            c.create_arc(cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7, start=start, extent=100,
                         style="arc", outline=ring, width=4)

        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=ring, width=3)
        c.create_text(cx, cy, text="🌱", font=("Helvetica", 30))

        caption = self.caption if len(self.caption) <= 90 else self.caption[:87] + "..."
        text_id = c.create_text(cx, 112, text=caption, fill="white", width=self.WIDTH - 24,
                                font=("Helvetica", 11), justify="center")
        x1, y1, x2, y2 = c.bbox(text_id)
        box = c.create_rectangle(x1 - 8, y1 - 4, x2 + 8, y2 + 4, fill="#1e1e1e", outline="#444444")
        c.tag_lower(box, text_id)


def run_gui(config, brain_kind: str) -> None:
    try:
        import tkinter as tk
    except ImportError:
        sys.exit(
            "The floating bubble needs Tkinter.\n"
            "On Mac run:  brew install python-tk\n"
            "then delete the .venv folder and set it up again."
        )

    from .__main__ import make_brain
    from .skills import Skills
    from .voice import Listener, Speaker

    root = tk.Tk()
    bubble = Bubble(root, name=config.name)

    def load():
        # Microphone calibration and loading the brain take a few seconds,
        # so do it in the background while the bubble shows "Getting ready..."
        try:
            speaker = Speaker(rate=config.voice_rate, voice=config.voice, tree_voice=config.tree_voice)

            def announce(text):  # used by timers
                bubble.set_text(f"{config.name}: {text}")
                speaker.say(text)

            skills = Skills(config.data_dir, default_city=config.city, announce=announce)
            brain = make_brain(config, brain_kind, skills)
            bubble.set_text("Checking microphone...")
            ears = Listener(engine=config.stt_engine, whisper_model=config.whisper_model)
            session = Session(brain, speaker, lambda timeout=None: ears.listen(timeout=timeout),
                              bubble.set_state, bubble.set_text, name=config.name,
                              groot_mode=config.i_am_groot)
            bubble.set_session(session)
            bubble.set_state("idle")
            bubble.set_text("Click me to talk")
            print(f"{config.name} is ready. Click the bubble to talk; right-click it to quit.")
        except Exception as exc:
            print(f"[error starting {config.name}: {exc}]")
            bubble.set_state("error")
            bubble.set_text(f"Couldn't start: {exc}")

    threading.Thread(target=load, daemon=True).start()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
