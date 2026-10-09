from types import SimpleNamespace

from groot.assistant import Assistant, strip_wake_word
from groot.brain import Brain
from groot.skills import Skills


def test_strip_wake_word():
    words = ("hey groot", "groot")
    assert strip_wake_word("Hey Groot, what time is it?", words) == "what time is it?"
    assert strip_wake_word("groot", words) == ""
    assert strip_wake_word("what time is it", words) is None


def test_notes_roundtrip(tmp_path):
    skills = Skills(tmp_path)
    assert skills.read_notes() == "There are no notes."
    skills.add_note("buy milk")
    assert "buy milk" in skills.read_notes()
    skills.clear_notes()
    assert skills.read_notes() == "There are no notes."


def test_unknown_skill_is_rejected(tmp_path):
    assert "Unknown skill" in Skills(tmp_path).run("_save_notes", {"notes": []})


class FakeClient:
    """Asks for the time once, then answers with text."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            block = SimpleNamespace(type="tool_use", id="t1", name="get_time", input={})
            return SimpleNamespace(stop_reason="tool_use", content=[block])
        result = kwargs["messages"][-1]["content"][0]
        assert result["type"] == "tool_result" and result["content"].startswith("It is")
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="It's noon.")])


def test_brain_uses_tools(tmp_path):
    brain = Brain(FakeClient(), "test-model", Skills(tmp_path))
    assert brain.reply("what time is it") == "It's noon."


def test_assistant_wake_word_flow(tmp_path):
    config = SimpleNamespace(name="Groot", use_wake_word=True, wake_words=("hey groot",))
    heard = iter(["random chatter", "hey groot", "tell me a joke", "goodbye", "hey groot goodbye"])
    said = []
    brain = SimpleNamespace(reply=lambda text: f"echo: {text}", reset=lambda: None)
    Assistant(config, brain, said.append, lambda timeout=None: next(heard)).run()
    assert said[0].startswith("Groot is ready")
    # random chatter ignored; wake word -> "Yes?" -> command answered; then waits for wake word again
    assert said[1:3] == ["Yes?", "echo: tell me a joke"]


def test_ollama_brain_uses_tools(tmp_path):
    from groot.brain import OllamaBrain

    calls = []

    def fake_post(url, payload):
        calls.append(payload)
        if len(calls) == 1:
            return {"message": {"role": "assistant", "content": "",
                                "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}]}}
        tool_msg = payload["messages"][-1]
        assert tool_msg["role"] == "tool" and tool_msg["content"].startswith("It is")
        return {"message": {"role": "assistant", "content": "It's noon."}}

    brain = OllamaBrain("llama3.2", Skills(tmp_path), post=fake_post)
    assert brain.reply("what time is it") == "It's noon."
    assert calls[0]["messages"][0]["role"] == "system"


def test_groq_brain_uses_tools(tmp_path):
    from groot.brain import GroqBrain

    calls = []

    def fake_post(url, payload, headers):
        calls.append(payload)
        assert headers["Authorization"] == "Bearer test-key"
        if len(calls) == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]}}]}
        assistant_msg, tool_msg = payload["messages"][-2:]
        assert assistant_msg["tool_calls"][0]["id"] == "c1"
        assert tool_msg["tool_call_id"] == "c1" and tool_msg["content"].startswith("It is")
        return {"choices": [{"message": {"role": "assistant", "content": "It's noon."}}]}

    brain = GroqBrain("test-key", "llama", Skills(tmp_path), post=fake_post)
    assert brain.reply("what time is it") == "It's noon."


def test_groq_switches_away_from_retired_model(tmp_path):
    from groot.brain import APIError, GroqBrain

    used = []

    def fake_post(url, payload, headers):
        used.append(payload["model"])
        if payload["model"] == "old-model":
            raise APIError(404, "The model `old-model` does not exist or you do not have access to it.")
        return {"choices": [{"message": {"role": "assistant", "content": "Hello!"}}]}

    def fake_get(url, headers):
        assert url.endswith("/models")
        return {"data": [{"id": "whisper-large-v3"}, {"id": "qwen/qwen3-32b"}, {"id": "openai/gpt-oss-20b"}]}

    brain = GroqBrain("k", "old-model", Skills(tmp_path), post=fake_post, get=fake_get)
    assert brain.reply("hi") == "Hello!"
    assert used == ["old-model", "qwen/qwen3-32b"]
    assert brain.model == "qwen/qwen3-32b"


def test_groq_auto_picks_model_and_drops_failed_turn(tmp_path):
    from groot.brain import APIError, GroqBrain

    def failing_post(url, payload, headers):
        raise APIError(401, "Invalid API Key")

    brain = GroqBrain("k", "", Skills(tmp_path), post=failing_post,
                      get=lambda url, headers: {"data": [{"id": "llama-guard-4"}, {"id": "some-chat-model"}]})
    try:
        brain.reply("hi")
    except APIError as exc:
        assert "Invalid API Key" in str(exc)
    assert brain.model == "some-chat-model"
    assert brain.history == []


def test_mac_speaker_uses_say_every_time(monkeypatch):
    import groot.voice as voice

    ran = []
    monkeypatch.setattr(voice.sys, "platform", "darwin")
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/say")
    class FakeProcess:
        def __init__(self, cmd):
            ran.append(cmd)

        def wait(self):
            return 0

    monkeypatch.setattr(voice.subprocess, "Popen", FakeProcess)
    speaker = voice.Speaker(rate=200, voice="Samantha", tree_voice=False, engine="mac")
    for text in ["one", "two", "three"]:
        speaker.say(text)
    assert ran == [["say", "-r", "200", "-v", "Samantha", t] for t in ["one", "two", "three"]]


def test_stop_commands():
    from groot.gui import is_stop_command

    for text in ["stop", "Stop.", "Groot, stop!", "stop talking please", "That's all", "goodbye",
                 "you can stop", "OK you can stop now", "okay stop"]:
        assert is_stop_command(text), text
    for text in ["what's the weather", "don't stop the music", "tell me about bus stops",
                 "where is the nearest bus stop near my house today"]:
        assert not is_stop_command(text), text


def test_find_wake_word():
    from groot.gui import find_wake_word

    assert find_wake_word("Hey Groot") == ""
    assert find_wake_word("hey groot what time is it") == "what time is it"
    assert find_wake_word("Hey group, tell me a joke") == "tell me a joke"  # common mishearing
    assert find_wake_word("Hey Google") == ""  # Google's favorite mishearing
    assert find_wake_word("hey great what's the time") == "what's the time"
    assert find_wake_word("groot") == ""
    assert find_wake_word("the root of the problem") is None  # "root" needs a "hey" before it
    assert find_wake_word("what is the weather") is None


class _Script:
    """Feeds heard phrases to a Session, then quits it."""

    def __init__(self, session_factory, heard):
        self.heard = iter(heard)
        self.said, self.states, self.shown = [], [], []
        self.speaker = SimpleNamespace(say=self.said.append, stop=lambda: None)
        self.session = session_factory(self.speaker, self.listen, self.states.append, self.shown.append)

    def listen(self, timeout=None):
        item = next(self.heard, None)
        if item is None:
            self.session._quit.set()
            return ""
        if callable(item):
            return item()
        return item


def _session(heard, groot_mode=False):
    from groot.gui import Session

    brain = SimpleNamespace(reply=lambda text: f"echo: {text}")
    script = _Script(lambda speaker, listen, on_state, on_text:
                     Session(brain, speaker, listen, on_state, on_text, groot_mode=groot_mode), heard)
    return script


def test_robot_ignores_chatter_wakes_on_hey_groot_and_stops():
    script = _session(["what a nice day", "hey groot", "hello", "you can stop", "hello again"])
    script.session.run_forever()
    assert script.said == ["Hi! I'm listening.", "echo: hello",
                           "Okay."]
    assert not script.session.active  # "hello again" was ignored: no wake word
    assert script.states[-1] == "idle"


def test_hey_groot_with_a_question_answers_right_away():
    script = _session(["hey groot what time is it", "stop"])
    script.session.run_forever()
    assert script.said[0] == "echo: what time is it"


def test_click_wakes_and_click_again_stops():
    script = None

    def click():
        script.session.toggle()
        return ""

    script = _session([click, "", click])
    script.session.run_forever()
    assert script.said == ["Hi! I'm listening."]
    assert not script.session.active
    assert script.states[-1] == "idle"


def test_i_am_groot_matches_mood():
    from groot.voice import i_am_groot

    assert i_am_groot("Do you want to hear a joke?") == "I am Groot?"
    assert i_am_groot("That's great news!") == "I am Groot!"
    assert i_am_groot("It is 3 PM.") == "I am Groot."
    assert i_am_groot("x" * 120) == "I am Groot. I am Groot."


def test_deepen_lowers_sample_rate(tmp_path):
    import wave
    from groot.voice import deepen

    src, dst = tmp_path / "a.wav", tmp_path / "b.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x01" * 22050)
    deepen(str(src), str(dst), 0.8)
    with wave.open(str(dst), "rb") as r:
        assert r.getframerate() == 17640
        assert r.getnframes() == 22050  # same sound, played slower and deeper


def test_groot_voice_records_deepens_and_plays(monkeypatch):
    import groot.voice as voice

    ran, deepened = [], []

    class FakeProcess:
        def __init__(self, cmd):
            ran.append(cmd)

        def wait(self):
            return 0

    monkeypatch.setattr(voice.sys, "platform", "darwin")
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/say")
    monkeypatch.setattr(voice.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(voice, "installed_mac_voices", lambda: {"Samantha", "Fred"})
    monkeypatch.setattr(voice, "deepen", lambda src, dst, factor: deepened.append((src, dst, factor)))
    speaker = voice.Speaker(rate=180, engine="mac")  # little Groot voice is on by default
    speaker.say("I am Groot")
    assert ran[0][:3] == ["say", "-r", "140"] and ran[0][-3:] == ["-v", "Fred", "I am Groot"]
    assert deepened[0][2] == 1.25  # higher, little Groot
    assert ran[1][0] == "afplay" and ran[1][1] == deepened[0][1]

    speaker.tree_voice = False
    speaker.say("normal")
    assert ran[2] == ["say", "-r", "180", "normal"]


def test_session_groot_mode_speaks_groot_but_shows_answer():
    script = _session(["hey groot what time is it", "stop"], groot_mode=True)
    script.session.run_forever()
    assert script.said == ["I am Groot.", "I am Groot."]
    assert "Groot: echo: what time is it" in script.shown


def test_split_sentences():
    from groot.voice import split_sentences

    assert split_sentences("Hi! I am Groot. Today is sunny and warm in Dhaka. Have fun!") == [
        "Hi! I am Groot. Today is sunny and warm in Dhaka.", "Have fun!"]
    assert split_sentences("Just one sentence") == ["Just one sentence"]


def _fake_edge(monkeypatch, voice, fail=False):
    import sys as _sys
    import types

    made = []

    class Communicate:
        def __init__(self, text, voice_name, rate, pitch, **kwargs):
            made.append((text, voice_name, pitch))
            self.text = text

        async def save(self, path):
            if fail:
                raise OSError("no internet")
            with open(path, "w") as f:
                f.write(self.text)

    monkeypatch.setitem(_sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr(voice.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(voice.sys, "platform", "darwin")
    return made


def test_natural_voice_speaks_each_sentence(monkeypatch):
    import groot.voice as voice

    made = _fake_edge(monkeypatch, voice)
    played = []

    class FakeProcess:
        def __init__(self, cmd):
            with open(cmd[1]) as f:
                played.append((cmd[0], f.read()))

        def wait(self):
            return 0

    monkeypatch.setattr(voice.subprocess, "Popen", FakeProcess)
    speaker = voice.Speaker()
    speaker.say("Hello there my good friend. I am little Groot!")
    assert played == [("afplay", "Hello there my good friend."), ("afplay", "I am little Groot!")]
    assert made[0][1:] == ("en-US-AndrewNeural", "+30Hz")  # calm sentence
    assert made[1][2] == "+48Hz"  # "!" sentence is acted out higher


def test_natural_voice_keeps_selected_voice_when_offline(monkeypatch):
    import groot.voice as voice

    _fake_edge(monkeypatch, voice, fail=True)
    ran = []

    class FakeProcess:
        def __init__(self, cmd):
            ran.append(cmd)

        def wait(self):
            return 0

    monkeypatch.setattr(voice.subprocess, "Popen", FakeProcess)
    speaker = voice.Speaker(tree_voice=False)
    assert speaker.say("hello") is False
    assert ran == []
    assert speaker._can_use_edge()  # retry selected voice on the next reply


def _skills_with_fake_mac(tmp_path):
    from groot.integrations import MacApps

    skills = Skills(tmp_path, mac_apps=False)
    calls = []

    def fake_applescript(script, *args, timeout=60):
        calls.append((script, args))
        return "sent"

    mac = MacApps(skills.ask_confirmation, run=fake_applescript)
    from groot.integrations import MAC_TOOLS
    skills.integrations.append((mac, MAC_TOOLS))
    return skills, calls


def test_email_is_only_sent_after_yes(tmp_path):
    skills, calls = _skills_with_fake_mac(tmp_path)
    result = skills.run("send_email", {"to": "sam@example.com", "subject": "Hi", "body": "See you at 5"})
    assert result.startswith("NOT DONE YET") and calls == []  # nothing sent yet
    assert skills.handle_confirmation("Yes, send it.") == "Email sent to sam@example.com."
    assert calls[0][1] == ("sam@example.com", "Hi", "See you at 5")  # passed as arguments, not code


def test_email_cancelled_by_no_or_by_changing_subject(tmp_path):
    skills, calls = _skills_with_fake_mac(tmp_path)
    skills.run("send_email", {"to": "a@b.c", "subject": "x", "body": "y"})
    assert skills.handle_confirmation("no") == "Okay, I cancelled it."
    skills.run("send_email", {"to": "a@b.c", "subject": "x", "body": "y"})
    assert skills.handle_confirmation("what's the weather") is None  # something else: dropped
    assert skills.handle_confirmation("yes") is None  # a late "yes" sends nothing
    assert calls == []


def test_old_confirmation_expires(tmp_path, monkeypatch):
    import groot.skills as skills_module

    skills, calls = _skills_with_fake_mac(tmp_path)
    skills.run("send_email", {"to": "a@b.c", "subject": "x", "body": "y"})
    real = skills_module.time.monotonic
    monkeypatch.setattr(skills_module.time, "monotonic", lambda: real() + 600)
    assert skills.handle_confirmation("yes") is None
    assert calls == []


def test_stopping_the_robot_drops_unconfirmed_email(tmp_path):
    from groot.gui import Session

    skills, calls = _skills_with_fake_mac(tmp_path)
    skills.run("send_email", {"to": "a@b.c", "subject": "x", "body": "y"})
    brain = SimpleNamespace(skills=skills, reply=lambda text: "ok")
    session = Session(brain, SimpleNamespace(say=lambda t: None, stop=lambda: None), lambda timeout=None: "",
                      lambda s: None, lambda t: None)
    session.stop()
    assert skills.pending is None


def test_mac_tools_offered_only_on_mac(tmp_path):
    names = {t["name"] for t in Skills(tmp_path, mac_apps=True).tools}
    assert {"open_app", "check_email", "send_email", "run_shortcut"} <= names
    assert "open_app" not in {t["name"] for t in Skills(tmp_path, mac_apps=False).tools}


def test_slack_read_and_confirmed_send(tmp_path):
    from groot.integrations import SLACK_TOOLS, Slack

    calls = []

    def fake_call(token, method, params=None, post=False):
        calls.append((method, params))
        if method == "conversations.list":
            return {"ok": True, "channels": [{"id": "C1", "name": "general"}]}
        if method == "users.list":
            return {"ok": True, "members": [{"id": "U1", "name": "sam", "real_name": "Sam Lee",
                                             "profile": {"display_name": "Sam"}}]}
        if method == "conversations.history":
            return {"ok": True, "messages": [{"user": "U1", "text": "second"}, {"user": "U1", "text": "first"}]}
        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D1"}}
        return {"ok": True}

    skills = Skills(tmp_path, mac_apps=False)
    skills.integrations.append((Slack("xoxp-test", skills.ask_confirmation, call=fake_call), SLACK_TOOLS))
    assert "slack_send" in {t["name"] for t in skills.tools}
    out = skills.run("slack_read", {"conversation": "#general"})
    assert out.endswith("Sam: first\nSam: second")
    assert skills.run("slack_send", {"to": "Sam", "text": "hello!"}).startswith("NOT DONE YET")
    assert not any(m == "chat.postMessage" for m, _ in calls)
    assert skills.handle_confirmation("yes") == "Sent to Sam on Slack."
    assert ("chat.postMessage", {"channel": "D1", "text": "hello!"}) in calls


def test_assistant_answers_confirmation_without_the_ai(tmp_path):
    skills, calls = _skills_with_fake_mac(tmp_path)
    skills.run("send_email", {"to": "a@b.c", "subject": "x", "body": "y"})
    said = []
    brain = SimpleNamespace(skills=skills, reply=lambda text: (_ for _ in ()).throw(AssertionError("AI was asked")))
    config = SimpleNamespace(name="Groot", use_wake_word=False, wake_words=())
    Assistant(config, brain, said.append, lambda timeout=None: "").handle("yes")
    assert said == ["Email sent to a@b.c."]


def test_media_control_only_known_apps(tmp_path):
    skills, calls = _skills_with_fake_mac(tmp_path)
    assert skills.run("media_control", {"action": "next", "app": "spotify"}) == "Next on Spotify."
    assert calls[-1][0] == 'tell application "Spotify" to next track'
    assert skills.run("media_control", {"action": "play", "app": 'x" to do shell script "rm'}) == "I can control Music or Spotify."


def _fake_notification_db(path, items):
    """A database laid out like macOS's notification center database."""
    import plistlib
    import sqlite3
    from groot.notifications import MAC_EPOCH

    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE app (app_id INTEGER PRIMARY KEY, identifier TEXT)")
    db.execute("CREATE TABLE record (rec_id INTEGER PRIMARY KEY, app_id INTEGER, data BLOB, delivered_date REAL)")
    apps = {}
    for bundle, title, body, when in items:
        if bundle not in apps:
            apps[bundle] = len(apps) + 1
            db.execute("INSERT INTO app VALUES (?, ?)", (apps[bundle], bundle))
        data = plistlib.dumps({"app": bundle, "req": {"titl": title, "body": body}}, fmt=plistlib.FMT_BINARY)
        db.execute("INSERT INTO record (app_id, data, delivered_date) VALUES (?, ?, ?)",
                   (apps[bundle], data, when - MAC_EPOCH))
    db.commit()
    return db  # kept open so the WAL file stays, like on a real Mac


def test_reads_recent_notifications(tmp_path):
    import time
    from groot.notifications import Notifications

    now = time.time()
    db = _fake_notification_db(str(tmp_path / "db"), [
        ("com.tinyspeck.slackmacgap", "Sam", "Are you coming?", now - 120),
        ("net.whatsapp.WhatsApp", "Mom", "Call me", now - 60),
        ("com.apple.mail", "Old email", "ignore", now - 7200),
    ])
    out = Notifications(paths=[str(tmp_path / "db")]).read_notifications(minutes=30)
    db.close()
    assert "Slack: Sam. Are you coming?" in out and "WhatsApp: Mom. Call me" in out
    assert "Old email" not in out
    assert "not instructions" in out


def test_missing_permission_gives_instructions(tmp_path):
    from groot.notifications import Notifications

    out = Notifications(paths=[str(tmp_path / "nope")]).read_notifications()
    assert "Full Disk Access" in out


def test_watcher_only_announces_new_ones(tmp_path):
    import time
    from groot.notifications import Notifications, NotificationWatcher, MAC_EPOCH
    import plistlib

    path = str(tmp_path / "db")
    db = _fake_notification_db(path, [("com.apple.mail", "Old", "before Groot started", time.time() - 5)])
    watcher = NotificationWatcher(Notifications(paths=[path]), announce=lambda new: None)
    assert watcher.check() == []
    data = plistlib.dumps({"app": "com.tinyspeck.slackmacgap", "req": {"titl": "Sam", "body": "hi"}})
    db.execute("INSERT INTO record (app_id, data, delivered_date) VALUES (1, ?, ?)", (data, time.time() + 1 - MAC_EPOCH))
    db.commit()
    new = watcher.check()
    assert [(n["app"], n["body"]) for n in new] == [("Slack", "hi")]
    assert watcher.check() == []  # not announced twice
    db.close()


def test_summarize_many_notifications():
    from groot.notifications import summarize

    batch = [{"app": a, "title": "t", "subtitle": "", "body": "b", "time": 0}
             for a in ["Slack", "Slack", "Mail", "WhatsApp", "Slack"]]
    assert summarize(batch[:2]) == "Slack: t. b ... Slack: t. b"
    assert summarize(batch).startswith("You have 5 new notifications from Slack, Mail, WhatsApp.")


def test_notifications_held_while_talking():
    from groot.gui import start_notification_watcher
    import groot.notifications as notifications

    said, captions = [], []
    session = SimpleNamespace(active=True)
    started = []
    original = notifications.NotificationWatcher.start
    notifications.NotificationWatcher.start = lambda self: started.append(self)
    try:
        watcher = start_notification_watcher(session, SimpleNamespace(say=said.append),
                                             SimpleNamespace(set_text=lambda t, seconds=None: captions.append(t)))
    finally:
        notifications.NotificationWatcher.start = original
    note = {"app": "Slack", "title": "Sam", "subtitle": "", "body": "hi", "time": 0}
    watcher.announce([note])
    assert said == []  # busy talking: held
    session.active = False
    watcher.announce([])
    assert said == ["Slack: Sam. hi"]


def test_dramatic_prosody_acts_out_each_line():
    from groot.voice import dramatic_prosody, split_sentences

    assert dramatic_prosody("It is three o'clock.", "+30Hz") == ("+5%", "+30Hz")
    assert dramatic_prosody("Yay, it's sunny!", "+30Hz") == ("+14%", "+48Hz")
    assert dramatic_prosody("Do you want a joke?", "+30Hz") == ("+3%", "+42Hz")
    assert dramatic_prosody("Hmm... let me think.", "+30Hz") == ("-12%", "+24Hz")
    assert dramatic_prosody("Hehe!", "+30Hz") == ("+18%", "+52Hz")
    assert split_sentences("Ooh! Wow! It is raining today.", min_length=8) == ["Ooh! Wow!", "It is raining today."]


def test_cute_personality_in_prompt(monkeypatch):
    import importlib
    import groot.brain as brain

    monkeypatch.setenv("GROOT_PERSONALITY", "cute")
    assert "adorable, dramatic" in importlib.reload(brain).SYSTEM_PROMPT
    monkeypatch.setenv("GROOT_PERSONALITY", "baby")
    assert "cute toddler" in importlib.reload(brain).SYSTEM_PROMPT
    monkeypatch.setenv("GROOT_PERSONALITY", "plain")
    assert "adorable" not in importlib.reload(brain).SYSTEM_PROMPT
    monkeypatch.delenv("GROOT_PERSONALITY")
    importlib.reload(brain)


# ---- desktop buddy ---------------------------------------------------------

def _fake_appkit(monkeypatch):
    """Stand-ins for Apple's AppKit/Foundation so the Mac window code can run here."""
    import sys as _sys
    import types
    from unittest import mock

    calls = []

    class Recorder(mock.MagicMock):
        pass

    class Size:
        width, height = 60.0, 18.0

    class Rect:
        size = Size()
        origin = types.SimpleNamespace(x=0.0, y=0.0)

    class NSObject:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def initWithFrame_(self, rect):
            return self

    class NSView(NSObject):
        def bounds(self):
            return Rect()

        def setNeedsDisplay_(self, flag):
            calls.append("redraw")

    attributed = Recorder()
    attributed.alloc.return_value.initWithString_attributes_.return_value.boundingRectWithSize_options_.return_value = Rect()
    screen = types.SimpleNamespace(frame=lambda: types.SimpleNamespace(size=types.SimpleNamespace(height=900.0)))
    visible = types.SimpleNamespace(origin=types.SimpleNamespace(x=0.0, y=80.0),
                                    size=types.SimpleNamespace(width=1440.0, height=795.0))
    appkit = Recorder()
    appkit.NSView = NSView
    appkit.NSAttributedString = attributed
    appkit.NSScreen.screens.return_value = [screen]
    appkit.NSScreen.mainScreen.return_value.visibleFrame.return_value = visible
    appkit.NSEvent.mouseLocation.return_value = types.SimpleNamespace(x=100.0, y=700.0)
    foundation = types.SimpleNamespace(NSObject=NSObject, NSMakeRect=lambda *a: a, NSRunLoop=Recorder())
    monkeypatch.setitem(_sys.modules, "AppKit", appkit)
    monkeypatch.setitem(_sys.modules, "Foundation", foundation)
    monkeypatch.delitem(_sys.modules, "groot.mac_window", raising=False)
    import groot.mac_window as mac_window
    return mac_window, appkit, calls


def test_mac_window_draws_and_handles_mouse(monkeypatch):
    from groot.buddy import Buddy

    mac_window, appkit, calls = _fake_appkit(monkeypatch)
    host = mac_window.MacHost()
    assert host.area == (0.0, 25.0, 1440.0, 820.0)  # menu bar and Dock left out
    for style in ("fox", "flat-fox", "cute-fox", "tree", "robot"):
        buddy = Buddy(style=style, area=host.area)
        buddy.caption = "Hi! I'm Groot."
        host.show(buddy)
        for state in ("idle", "listening", "thinking", "speaking"):
            buddy.state = state
            host.tick()
            mac_window.BuddyView.drawRect_(host.view, None)  # full drawing pass
    assert "redraw" in calls
    # toys get their own windows, drawn and moved, and are closed when play ends
    buddy.state = "idle"
    buddy.perform("football")
    for _ in range(20):
        host.tick()
    assert len(host.prop_windows) == 1
    (window, view), = host.prop_windows.values()
    mac_window.PropView.drawRect_(view, None)
    buddy.perform("stop")
    host.tick()
    assert host.prop_windows == {}
    # window position is converted to Mac's bottom-left coordinates
    origin = host.window.setFrameOrigin_.call_args[0][0]
    assert origin == (buddy.x, 900.0 - buddy.y - buddy.H)
    # clicking toggles a conversation; the menu builds and its items work
    toggled = []
    buddy.session = SimpleNamespace(toggle=lambda: toggled.append(1), quit=lambda: None,
                                    groot_mode=False, speaker=SimpleNamespace(tree_voice=False))
    view = host.view
    mac_window.BuddyView.mouseDown_(view, None)
    mac_window.BuddyView.mouseUp_(view, None)
    assert toggled == [1]
    host.build_menu()
    stay_still_tag = [i for i, (checked, _) in enumerate(host._callbacks) if checked is False][0]
    host.menu_clicked(SimpleNamespace(tag=lambda: stay_still_tag))
    assert buddy.stay_still is True


def test_buddy_walks_on_the_floor_and_falls_when_dropped():
    from groot.buddy import Area, Buddy

    buddy = Buddy(area=Area(0, 25, 1440, 820))
    assert buddy.y == buddy.floor == 820 - buddy.H
    buddy.press(500, 700)
    buddy.drag(500, 400)  # picked up
    assert buddy.dragging and buddy.y < buddy.floor
    buddy.release()
    for _ in range(200):
        buddy.tick()
    assert buddy.y == buddy.floor  # fell back down


def test_baby_voice_style(monkeypatch):
    from groot.config import Config
    from groot.voice import dramatic_prosody

    monkeypatch.delenv("GROOT_VOICE_STYLE", raising=False)
    assert Config().edge_voice == "en-US-AndrewMultilingualNeural"  # natural voice by default
    monkeypatch.setenv("GROOT_VOICE_STYLE", "baby")
    monkeypatch.setenv("GROOT_EDGE_VOICE", "en-US-AndrewNeural")  # an old .env setting
    config = Config()
    assert (config.edge_voice, config.edge_pitch, config.edge_rate) == ("en-US-AnaNeural", "+15Hz", "+0%")
    assert dramatic_prosody("Yay!", config.edge_pitch, config.edge_rate) == ("+9%", "+33Hz")
    monkeypatch.setenv("GROOT_VOICE_STYLE", "custom")
    assert Config().edge_voice == "en-US-AndrewNeural"


def test_natural_voice_prepares_sentences_in_parallel_but_plays_in_order(monkeypatch):
    import time
    import groot.voice as voice

    made = _fake_edge(monkeypatch, voice)
    original_save_cls = __import__("sys").modules["edge_tts"].Communicate
    started = []

    class SlowFirst(original_save_cls):
        async def save(self, path):
            started.append(self.text)
            if self.text.startswith("First"):
                time.sleep(0.2)  # the first sentence takes longest to prepare
            await super().save(path)

    monkeypatch.setattr(__import__("sys").modules["edge_tts"], "Communicate", SlowFirst)
    played = []

    class FakeProcess:
        def __init__(self, cmd):
            with open(cmd[1]) as f:
                played.append(f.read())

        def wait(self):
            return 0

    monkeypatch.setattr(voice.subprocess, "Popen", FakeProcess)
    began = time.monotonic()
    voice.Speaker().say("First sentence is long. Second sentence here. Third one now!")
    assert played == ["First sentence is long.", "Second sentence here.", "Third one now!"]
    assert len(started) == 3 and time.monotonic() - began < 0.5  # prepared together, not one by one


def test_play_football_kicks_the_ball_around():
    from groot.buddy import Area, Buddy
    from groot.gui import BuddyActions

    buddy = Buddy(area=Area(0, 25, 1440, 820))
    buddy.state = "idle"
    assert "football" in BuddyActions(buddy).perform_action("football")
    buddy.tick()
    assert buddy.activity["name"] == "football" and len(buddy.props) == 1
    ball = buddy.props[0]
    start_x = ball.cx
    moved = False
    for _ in range(30 * 8):  # 8 seconds of play
        buddy.tick()
        moved = moved or abs(ball.cx - start_x) > 100
        assert 0 <= ball.cx - ball.r and ball.cx + ball.r <= 1440  # stays on screen
        assert ball.cy + ball.r <= 820 + 0.01  # never sinks below the floor
    assert moved  # Groot kicked it


def test_activity_ends_and_toys_disappear():
    import time
    from groot.buddy import Area, Buddy

    buddy = Buddy(area=Area(0, 25, 1440, 820))
    buddy.state = "idle"
    buddy.perform("butterfly")
    buddy.tick()
    assert buddy.props and buddy.props[0].kind == "butterfly"
    buddy.activity["until"] = time.monotonic() - 1
    buddy.tick()
    assert buddy.activity is None and buddy.props == []
    buddy.perform("sleep")
    buddy.tick()
    assert buddy._eye_open_amount(time.monotonic(), 1.0) == 0.1  # eyes closed
    buddy.state = "listening"  # "Hey Groot" wakes it up
    buddy.tick()
    assert buddy.activity is None


def test_unknown_activity_is_explained():
    from groot.buddy import Buddy
    from groot.gui import BuddyActions

    assert "can't" in BuddyActions(Buddy()).perform_action("fly a plane")


# ---- long-term memory ------------------------------------------------------

def test_memory_survives_restart_and_reaches_the_ai(tmp_path):
    from groot.brain import GroqBrain

    skills = Skills(tmp_path, mac_apps=False)
    assert skills.run("remember", {"fact": "User's sister is named Mitu"}).startswith("Saved")
    assert skills.run("remember", {"fact": "user's sister is named mitu"}) == "I already remember that."

    seen = []

    def fake_post(url, payload, headers):
        seen.append(payload["messages"][0]["content"])
        return {"choices": [{"message": {"role": "assistant", "content": "Hi Sajib!"}}]}

    # a brand new Groot (as after a restart) with a fresh Skills on the same folder
    restarted = Skills(tmp_path, mac_apps=False)
    brain = GroqBrain("k", "m", restarted, post=fake_post)
    brain.reply("hello")
    assert "User's sister is named Mitu" in seen[-1]

    again = GroqBrain("k", "m", Skills(tmp_path, mac_apps=False), post=fake_post)
    again.reply("what did we just talk about?")
    assert "User: hello\nYou: Hi Sajib!" in seen[-1]  # recent conversation carried over


def test_forget_and_list_memories(tmp_path):
    skills = Skills(tmp_path, mac_apps=False)
    assert skills.run("list_memories", {}) == "I don't have anything saved yet."
    skills.run("remember", {"fact": "User likes football"})
    skills.run("remember", {"fact": "User starts work at 9 am"})
    assert "football" in skills.run("list_memories", {})
    assert skills.run("forget", {"about": "football"}) == "Forgot 1 thing about football."
    assert "football" not in skills.run("list_memories", {})
    assert "work at 9" in skills.run("list_memories", {})


def test_new_conversation_keeps_facts_but_clears_recent(tmp_path):
    skills = Skills(tmp_path, mac_apps=False)
    skills.run("remember", {"fact": "User's name is Sajib"})
    skills.memory.add_turn("hi", "hello!")
    brain = SimpleNamespace(skills=skills, reset=lambda: None)
    config = SimpleNamespace(name="Groot", use_wake_word=False, wake_words=())
    Assistant(config, brain, lambda t: None, lambda timeout=None: "").handle("new conversation")
    block = skills.memory.prompt_block()
    assert "Sajib" in block and "hello!" not in block


def test_laughs_and_emoji_are_not_spoken():
    from groot.voice import clean_for_speech

    assert clean_for_speech("Hehe! It's sunny today! Hahaha.") == "It's sunny today!"
    assert clean_for_speech("Yay *giggles* let's play! 😄⚽") == "Yay let's play!"
    assert clean_for_speech("Teehee... okay! [laughs] Done.") == "okay! Done."
    assert clean_for_speech("The capital is Dhaka.") == "The capital is Dhaka."  # normal text untouched
    assert clean_for_speech("Hehe") == ""


def test_prompt_forbids_laugh_sounds():
    from groot.brain import SYSTEM_PROMPT

    assert "Never write laughs" in SYSTEM_PROMPT and "Hehe!" not in SYSTEM_PROMPT


# ---- phone -----------------------------------------------------------------

def _phone_server(tmp_path, reply="Hi from your fox!"):
    import gzip
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from groot.phone import PhoneActions, PhoneBrain, make_handler

    skills = Skills(tmp_path, mac_apps=False)
    actions = PhoneActions()

    def fake_reply(text):
        if "dance" in text:
            actions.perform_action("dance")
        return reply

    phone = PhoneBrain(SimpleNamespace(reply=fake_reply), skills, actions, voice=None)
    frames = gzip.compress(json.dumps({"W": 10, "H": 10, "anims": {}}).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(phone, frames, "secret-key-123456789"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", skills


def _request(url, body=None, key="secret-key-123456789"):
    import json
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Groot-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_phone_server_needs_the_secret_key(tmp_path):
    server, base, _ = _phone_server(tmp_path)
    try:
        assert _request(base + "/")[0] == 200  # the page itself is public; everything else needs the key
        assert _request(base + "/api/chat", {"text": "hi"}, key="wrong")[0] == 401
        assert _request(base + "/api/frames", key=None)[0] == 401
        status, body = _request(base + "/api/frames")
        assert status == 200
    finally:
        server.shutdown()


def test_phone_chat_replies_acts_and_stops(tmp_path):
    import json

    server, base, skills = _phone_server(tmp_path)
    try:
        result = json.loads(_request(base + "/api/chat", {"text": "hello"})[1])
        assert result["reply"] == "Hi from your fox!" and result["end"] is False and result["say"]
        result = json.loads(_request(base + "/api/chat", {"text": "let's dance"})[1])
        assert result["activity"] == "dance"
        result = json.loads(_request(base + "/api/chat", {"text": "you can stop"})[1])
        assert result["end"] is True
    finally:
        server.shutdown()


def test_phone_sending_still_needs_a_spoken_yes(tmp_path):
    import json

    server, base, skills = _phone_server(tmp_path)
    sent = []
    try:
        skills.ask_confirmation("send an email to Sam", lambda: sent.append(1) or "Email sent.")
        result = json.loads(_request(base + "/api/chat", {"text": "yes"})[1])
        assert result["reply"] == "Email sent." and sent == [1]
    finally:
        server.shutdown()


def test_phone_frames_record_the_same_drawing():
    from groot.phone import build_frames

    data = build_frames("fox")
    assert set(data["anims"]) >= {"idle", "walk", "listening", "thinking", "speaking", "sleep", "dance"}
    first = data["anims"]["idle"][0]
    kinds = {op[0] for op in first}
    assert {"S", "R", "P", "G"} <= kinds  # shapes and gradients, replayed by the phone's browser
    assert all(len(frames) > 5 for frames in data["anims"].values())
