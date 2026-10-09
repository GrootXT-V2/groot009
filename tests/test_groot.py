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
    speaker = voice.Speaker(rate=200, voice="Samantha", tree_voice=False)
    for text in ["one", "two", "three"]:
        speaker.say(text)
    assert ran == [["say", "-r", "200", "-v", "Samantha", t] for t in ["one", "two", "three"]]


def test_stop_commands():
    from groot.gui import is_stop_command

    for text in ["stop", "Stop.", "Groot, stop!", "stop talking please", "That's all", "goodbye"]:
        assert is_stop_command(text), text
    for text in ["what's the weather", "don't stop the music", "tell me about bus stops"]:
        assert not is_stop_command(text), text


def _run_session(heard_items):
    import threading
    from groot.gui import Session

    heard = iter(heard_items)
    said, states, done = [], [], threading.Event()

    class FakeSpeaker:
        def say(self, text):
            said.append(text)

        def stop(self):
            pass

    def listen(timeout=None):
        try:
            return next(heard)
        except StopIteration:
            done.set()
            return ""

    brain = SimpleNamespace(reply=lambda text: f"echo: {text}")
    session = Session(brain, FakeSpeaker(), listen, states.append, lambda text: None)
    session.start()
    return session, said, states, done


def test_session_talks_until_user_says_stop():
    session, said, states, _ = _run_session(["", "hello", "stop", "never heard"])
    for _ in range(100):
        if not session.active:
            break
        import time; time.sleep(0.01)
    assert not session.active
    assert said == ["Hi! I'm listening.", "echo: hello", "Okay, talk to you later."]
    assert states[-1] == "idle"


def test_session_stops_when_clicked_again():
    session, said, states, done = _run_session([])
    assert done.wait(1)
    session.toggle()  # second click
    assert not session.active
    assert states[-1] == "idle"


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
    speaker = voice.Speaker(rate=180)  # little Groot voice is on by default
    speaker.say("I am Groot")
    assert ran[0][:3] == ["say", "-r", "140"] and ran[0][-3:] == ["-v", "Fred", "I am Groot"]
    assert deepened[0][2] == 1.25  # higher, little Groot
    assert ran[1][0] == "afplay" and ran[1][1] == deepened[0][1]

    speaker.tree_voice = False
    speaker.say("normal")
    assert ran[2] == ["say", "-r", "180", "normal"]


def test_session_groot_mode_speaks_groot_but_shows_answer():
    import time
    from groot.gui import Session

    spoken, shown = [], []
    heard = iter(["what time is it", "stop"])
    speaker = SimpleNamespace(say=spoken.append, stop=lambda: None)
    brain = SimpleNamespace(reply=lambda text: "It is 3 PM.")
    session = Session(brain, speaker, lambda timeout=None: next(heard, ""), lambda s: None, shown.append,
                      groot_mode=True)
    session.start()
    for _ in range(100):
        if not session.active:
            break
        time.sleep(0.01)
    assert spoken == ["I am Groot!", "I am Groot.", "I am Groot."]
    assert "Groot: It is 3 PM." in shown
