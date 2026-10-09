"""Groot the desktop robot.

A little robot walks and plays around your screen. Say "Hey Groot" (or click
it) and it stops to listen and talk. Say "stop" or "you can stop" (or click it
again) and it goes back to playing.

Run with:  python -m groot --gui
"""

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

# Speech recognition often hears "Groot" as one of these (Google loves "hey Google")
GROOT_SOUNDS = {"groot", "grut", "grute", "groote", "grooot", "gruit", "group", "groups",
                "root", "route", "grout", "gru", "grew", "brute", "brood", "groove", "google",
                "great", "grow", "grows", "grove", "crude", "cute", "goot", "good", "true"}
GREETINGS = {"hey", "hi", "hello", "ok", "okay", "a", "yo", "hay", "he", "hei", "oi", "hai", "eh"}


def _sounds_like_groot(word: str) -> bool:
    return word in GROOT_SOUNDS or (word.startswith("gr") and len(word) <= 7)


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
        if not _sounds_like_groot(word):
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
        skills = getattr(self.brain, "skills", None)
        if skills is not None:
            skills.pending = None  # never keep an unconfirmed email/message around
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
        # Shown in Terminal so you can see what the microphone picked up
        print(f"[heard] {heard}" + ("  -> waking up!" if command is not None else ""))
        if command is not None:
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
        skills = getattr(self.brain, "skills", None)
        confirmed = skills.handle_confirmation(heard) if skills is not None else None
        if confirmed is not None:  # the user answered yes/no to sending something
            self._say(confirmed)
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


def start_notification_watcher(session, speaker, robot):
    """Read new notifications aloud; hold them while you're talking to Groot."""
    from .notifications import NotificationWatcher, Notifications, summarize

    held = []

    def announce(new):
        if session.active:
            held.extend(new)
            return
        batch = held + new
        held.clear()
        if not batch:
            return
        text = summarize(batch)
        print(f"[notification] {text}")
        robot.set_text(text, seconds=12)
        speaker.say(text)

    watcher = NotificationWatcher(Notifications(), announce)
    watcher.start()
    return watcher


ACTIVITY_WORDS = {
    "football": "play football with a ball on the screen",
    "butterfly": "chase a butterfly",
    "dance": "dance",
    "jump": "jump up and down",
    "wave": "wave hello",
    "sleep": "take a nap (until the user talks again)",
    "run": "run around",
    "stop": "stop the current activity",
}

BUDDY_TOOLS = [
    {"name": "perform_action",
     "description": "Make your little body on the user's screen do something fun, because the user asked "
                    "(e.g. 'play football', 'let's dance', 'chase a butterfly', 'go to sleep'). Options: "
                    + "; ".join(f"{name} = {what}" for name, what in ACTIVITY_WORDS.items()),
     "input_schema": {"type": "object", "properties": {
         "activity": {"type": "string", "enum": list(ACTIVITY_WORDS)}}, "required": ["activity"]}},
]


class BuddyActions:
    """Lets the brain make the desktop buddy act things out."""

    def __init__(self, buddy):
        self.buddy = buddy

    def perform_action(self, activity: str) -> str:
        if activity not in ACTIVITY_WORDS:
            return f"I can't do {activity} yet. I can: {', '.join(ACTIVITY_WORDS)}."
        self.buddy.perform(activity)
        if activity == "stop":
            return "Stopped."
        return f"Now doing it on the screen: {ACTIVITY_WORDS[activity]}."


def make_host():
    """The window system: Apple's AppKit on Mac, Qt everywhere else."""
    if sys.platform == "darwin":
        try:
            from .mac_window import MacHost
        except ImportError:
            sys.exit("The desktop buddy needs PyObjC on Mac.\nRun:  pip install -r requirements.txt")
        return MacHost()
    try:
        from .qt_window import QtHost
    except ImportError:
        sys.exit("The desktop buddy needs PySide6.\nRun:  pip install -r requirements.txt")
    return QtHost()


def run_gui(config, brain_kind: str) -> None:
    import signal

    from .__main__ import make_brain
    from .buddy import Buddy
    from .skills import Skills
    from .voice import Listener, Speaker

    host = make_host()
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # let Ctrl+C in Terminal quit
    robot = Buddy(name=config.name, size=config.robot_size, style=config.robot_style, area=host.area)
    host.show(robot)

    def load():
        # Microphone calibration and loading the brain take a few seconds,
        # so do it in the background while the robot shows "Getting ready..."
        try:
            speaker = Speaker(rate=config.voice_rate, voice=config.voice, tree_voice=config.tree_voice,
                              pitch=config.voice_pitch, engine=config.tts,
                              edge_voice=config.edge_voice, edge_pitch=config.edge_pitch,
                              dramatic=config.dramatic_voice, edge_rate=config.edge_rate)

            def announce(text):  # used by timers
                robot.set_text(f"{config.name}: {text}", seconds=8)
                speaker.say(text)

            skills = Skills(config.data_dir, default_city=config.city, announce=announce,
                            slack_token=config.slack_token)
            skills.integrations.append((BuddyActions(robot), BUDDY_TOOLS))
            brain = make_brain(config, brain_kind, skills)
            robot.set_text("Checking microphone...")
            ears = Listener(engine=config.stt_engine, whisper_model=config.whisper_model)
            session = Session(brain, speaker, lambda timeout=None: ears.listen(timeout=timeout),
                              robot.set_state, robot.set_text, name=config.name,
                              groot_mode=config.i_am_groot)
            robot.set_session(session)
            if config.read_notifications and sys.platform == "darwin":
                robot.set_watcher(start_notification_watcher(session, speaker, robot))
            robot.set_state("idle")
            robot.set_text('Say "Hey Groot" or click me!', seconds=6)
            session.launch()
            print(f'{config.name} is ready. Say "Hey Groot" or click the robot; right-click it to quit.')
        except Exception as exc:
            print(f"[error starting {config.name}: {exc}]")
            robot.set_state("error")
            robot.set_text(f"Couldn't start: {exc}")

    threading.Thread(target=load, daemon=True).start()
    host.run()
