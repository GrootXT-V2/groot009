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
                           "Okay! I'll go play. Say hey Groot if you need me."]
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
    assert script.said == ["I am Groot.", "I am Groot!"]
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
        def __init__(self, text, voice_name, rate, pitch):
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
    assert made[0][1:] == ("en-US-AndrewNeural", "+20Hz")


def test_natural_voice_falls_back_to_mac_when_offline(monkeypatch):
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
    speaker.say("hello")
    assert ran == [["say", "-r", "180", "hello"]]
    assert not speaker._can_use_edge()  # don't retry right away


def test_prepare_qt_points_mac_at_pyside_plugins(tmp_path, monkeypatch):
    import os
    import sys as _sys
    import types
    import groot.gui as gui

    plugins = tmp_path / "PySide6" / "Qt" / "plugins" / "platforms"
    plugins.mkdir(parents=True)
    (plugins / "libqcocoa.dylib").write_text("")
    monkeypatch.setitem(_sys.modules, "PySide6", types.SimpleNamespace(__file__=str(tmp_path / "PySide6" / "__init__.py")))
    monkeypatch.setattr(gui.sys, "platform", "darwin")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/opt/homebrew/share/qt/plugins")
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "")  # restored after the test
    gui.prepare_qt()
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == str(plugins)
    assert os.environ["QT_PLUGIN_PATH"] == str(plugins.parent)


# ---- apps, email and Slack -------------------------------------------------

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


def test_qt_check_explains_instead_of_crashing(monkeypatch):
    import pytest
    import groot.gui as gui

    failed = SimpleNamespace(returncode=134, stdout="", stderr=(
        "qt.core.plugin.factoryloader: checking directory path ...\n"
        'Cannot load library libqcocoa.dylib: (Library not loaded: @rpath/QtGui.framework)\n'))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: failed)
    with pytest.raises(SystemExit) as stop:
        gui.check_qt_starts()
    message = str(stop.value)
    assert "Library not loaded" in message and "python3.12 -m venv .venv" in message

    monkeypatch.setattr("subprocess.run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="qt-ok\n", stderr=""))
    gui.check_qt_starts()  # works: no exit


# ---- notifications ---------------------------------------------------------

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
