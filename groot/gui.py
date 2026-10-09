"""Groot the desktop robot.

The fox sleeps in a corner. Say "Fox" (or click it) to talk, then say
"stop" to send it walking to the opposite corner for another nap.

Run with:  python -m groot --gui
"""

import re
import random
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
# Google transcribed this microphone's "Hay Kurama" as khura, Kura,
# crom and Chrome. Require a clear greeting for aliases to limit false wakes.
KURAMA_SOUNDS = {"khura", "kura", "crom", "chrome", "karama", "kuruma", "karuma", "korama", "curama", "karma"}
KURAMA_GREETINGS = {"hey", "hay", "hai", "hi", "hello", "hei"}


def _sounds_like_groot(word: str) -> bool:
    return word in GROOT_SOUNDS or (word.startswith("gr") and len(word) <= 7)


def _clean(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s'\u0980-\u09ff]", " ", text.lower()).split())


def is_stop_command(text: str, name: str = "Groot") -> bool:
    command = find_wake_word(text, name)
    cleaned = _clean(text) if command is None else command
    sleep_request = re.fullmatch(
        r"(?:please )?(?:you can |you may |you should |time to )?"
        r"(?:go to sleep|go back to sleep|sleep|rest|stop|stop now|take a nap)"
        r"(?: now)?(?: please)?", cleaned)
    if sleep_request:
        return True
    if cleaned in STOP_PHRASES or cleaned.startswith("stop "):
        return True
    words = cleaned.split()
    while words and words[-1] in ("now", "please", name.lower(), "buddy"):
        words.pop()
    # short phrases ending in "stop", like "okay you can stop now" (but not "don't stop")
    return bool(words) and words[-1] == "stop" and len(words) <= 5 and "don't" not in words


def find_wake_word(text: str, name: str = "Groot"):
    """Return the command following the configured name, or None if not called."""
    words = _clean(text).split()
    name_words = _clean(name).split()
    if not name_words:
        return None
    # The wake phrase is independent of Kurama's display/personality name.
    if name_words == ["kurama"]:
        # Match complete names at the start, not mentions in ordinary chatter.
        call = re.match(
            r"^(?:(?:hey|hay|hi|hello|yo|okay|ok|হেই|হে|হাই|হ্যালো)\s+|wake up\s+)?"
            r"(?:kurama|foxy|fox|কুরামা|ফক্স|ফক্সি|(?:nine|9)\s*(?:tails|talls|tales))(?=\s|$)",
            " ".join(words))
        if call:
            return " ".join(words)[call.end():].strip()
        # The greeting may be clipped or transcribed as a separate phrase.
        if words[:1] == ["fox"]:
            return " ".join(words[1:])
        # Observed short wake transcriptions; only whole utterances qualify.
        if words in (["hypox"], ["vlogs"], ["folks"], ["foks"], ["hello", "folks"]):
            return ""
        for i in range(min(3, len(words) - 1)):
            if words[i] in {"hay", "hey", "hai", "hy", "hi", "i"} and words[i + 1] == "fox":
                return " ".join(words[i + 2:])
    if name_words != ["groot"]:
        for i in range(min(4, len(words))):
            if words[i:i + len(name_words)] == name_words:
                if i == 0 or words[i - 1] in GREETINGS:
                    return " ".join(words[i + len(name_words):])
            if (name_words == ["kurama"] and i > 0
                    and words[i - 1] in KURAMA_GREETINGS
                    and words[i] in KURAMA_SOUNDS):
                return " ".join(words[i + 1:])
        return None
    for i, word in enumerate(words[:4]):
        if not _sounds_like_groot(word):
            continue
        greeted = i > 0 and words[i - 1] in GREETINGS
        if word == "groot" or greeted:
            return " ".join(words[i + 1:])
    return None


def wake_command(text, name):
    command = find_wake_word(text, name)
    # Repeated calls in one recording are one greeting, not a question for the AI.
    while command:
        rest = find_wake_word(command, name)
        if rest is None or rest == command:
            break
        command = rest
    return command


WAKE_REPLIES = (
    ("I'm here. What's on your mind?", "You have my attention. Go on.",
     "What do you need?", "All right, I'm listening."),
    ("I heard you the first time. What is it?", "Still here. Are you going to ask something?",
     "Again? Go on, then.", "You don't need to keep calling. I'm listening."),
    ("Enough calling my name. Say what you need.", "You woke me just to do that again? Get to the point.",
     "You're testing my patience. Do you have a question?", "Oh, come on. Ask something already.")
)


class Session:
    """Listens in the background: waits for the configured name while asleep, then
    has a conversation (listen -> think -> speak) until told to stop."""

    def __init__(self, brain, speaker, listen, on_state, on_text, name="Groot", groot_mode=False,
                 on_stop=None, on_emotion=None):
        self.brain = brain
        self.speaker = speaker
        self.listen = listen
        self.on_state = on_state
        self.on_text = on_text
        self.on_stop = on_stop
        self.on_emotion = on_emotion or (lambda mood: None)
        self.name = name
        self.groot_mode = groot_mode  # only say "I am Groot" out loud; show the real answer
        self._awake = threading.Event()
        self._quit = threading.Event()
        self._greet = False
        self._first_command = None
        self._empty_calls = 0
        self._last_call_at = None
        self._recent_wake_replies = []
        self._last_activity = time.monotonic()

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
        self._last_activity = time.monotonic()
        self.on_state("listening")

    def stop(self) -> None:
        was_active = self.active
        self._awake.clear()
        self.speaker.stop()
        skills = getattr(self.brain, "skills", None)
        if skills is not None:
            skills.pending = None  # never keep an unconfirmed email/message around
        self.on_state("idle")
        self.on_text("")
        if was_active and self.on_stop is not None:
            self.on_stop()

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
        command = wake_command(heard, self.name)
        # Shown in Terminal so you can see what the microphone picked up
        print(f"[heard] {heard}" + ("  -> waking up!" if command is not None else ""), flush=True)
        if command is not None:
            self.start(first_command=command or None)

    def _conversation_turn(self) -> None:
        if self._greet:
            self._greet = False
            command, self._first_command = self._first_command, None
            if command:
                self._handle(command)
            elif self.name.lower() == "kurama":
                self._answer_call()
            else:
                self._say("Hi! I'm listening.")
            return
        if time.monotonic() - self._last_activity >= 120:
            self.stop()
            return
        self.on_state("waiting")
        self.on_text("Listening...")
        heard = self.listen(timeout=2)
        if heard and heard.strip() and self._awake.is_set():
            self._handle(heard)
        elif self.active and time.monotonic() - self._last_activity >= 120:
            self.stop()

    def speech_started(self) -> None:
        """Sit as soon as the microphone detects speech, before transcription."""
        if self.active:
            self.on_state("listening")

    def _answer_call(self) -> None:
        now = time.monotonic()
        if self._last_call_at is None or now - self._last_call_at >= 90:
            self._empty_calls = 0
        self._last_call_at = now
        self._empty_calls += 1
        self.on_emotion("annoyed" if self._empty_calls >= 3 else "curious")
        replies = WAKE_REPLIES[min(self._empty_calls - 1, 2)]
        choices = [line for line in replies if line not in self._recent_wake_replies[-3:]]
        reply = random.choice(choices)
        self._recent_wake_replies = (self._recent_wake_replies + [reply])[-3:]
        self._say(reply)

    def _handle(self, heard: str) -> None:
        self.speech_started()
        self._last_activity = time.monotonic()
        self.on_text(f"You: {heard}")
        if self.name.lower() == "kurama":
            command = wake_command(heard, self.name)
            if command == "":
                self._answer_call()
                return
            if command is not None:
                heard = command
        if is_stop_command(heard, self.name):
            self._say("Okay.")
            self.stop()
            return
        # A real request ends the teasing; stop alone preserves repeated-wake history.
        self._empty_calls = 0
        self._last_call_at = None
        words = set(_clean(heard).split())
        if words & {"sad", "upset", "worried", "lonely", "scared", "hurt"}:
            self.on_emotion("concerned")
        elif words & {"thanks", "thank", "happy", "great", "finished"}:
            self.on_emotion("happy")
        else:
            self.on_emotion("focused")
        skills = getattr(self.brain, "skills", None)
        confirmed = skills.handle_confirmation(heard) if skills is not None else None
        if confirmed is not None:  # the user answered yes/no to sending something
            self._say(confirmed)
            return
        prepare_greeting = getattr(skills, "prepare_slack_greeting", None)
        memory = getattr(skills, 'memory', None)
        identity = memory.answer_identity(heard) if memory is not None else None
        if identity is not None:
            self._say(identity)
            return
        greeting = prepare_greeting(heard) if prepare_greeting else None
        if greeting is not None:
            self._say(greeting)
            return
        self.on_state("thinking")
        try:
            answer = self.brain.reply(heard)
        except Exception as exc:
            print(f"[error: {exc}]")
            self.on_emotion("concerned")
            answer = "Sorry, something went wrong. Please try again."
        self._say(answer)

    def _say(self, text: str) -> None:
        if not self._awake.is_set():
            return
        self.on_state("speaking")
        self.on_text(f"{self.name}: {text}")
        spoken = self.speaker.say(i_am_groot(text) if self.groot_mode else text)
        if spoken is False and self.active:
            self.on_text(f"{self.name}: {text}\n(Voice unavailable; please try again.)")
        self._last_activity = time.monotonic()


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
                              groot_mode=config.i_am_groot, on_stop=robot.end_conversation,
                              on_emotion=robot.set_emotion)
            robot.set_session(session)
            ears.on_speech_start = session.speech_started
            ears.speaker = speaker
            if config.read_notifications and sys.platform == "darwin":
                robot.set_watcher(start_notification_watcher(session, speaker, robot))
            robot.set_state("idle")
            wake_phrase = "Fox" if config.name.lower() == "kurama" else f"Hey {config.name}"
            robot.set_text('Say "Fox", "Hey Kurama" or "Hi Foxy"!' if config.name.lower() == "kurama"
                           else f'Say "{wake_phrase}" or click me!', seconds=6)
            session.launch()
            print(f'{config.name} is ready. Say "{wake_phrase}" or click the fox; right-click it to quit.')
        except Exception as exc:
            print(f"[error starting {config.name}: {exc}]")
            robot.set_state("error")
            robot.set_text(f"Couldn't start: {exc}")

    threading.Thread(target=load, daemon=True).start()
    host.run()
