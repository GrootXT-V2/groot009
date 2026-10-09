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
    monkeypatch.setattr(voice.subprocess, "run", lambda cmd, check: ran.append(cmd))
    speaker = voice.Speaker(rate=200, voice="Samantha")
    for text in ["one", "two", "three"]:
        speaker.say(text)
    assert ran == [["say", "-r", "200", "-v", "Samantha", t] for t in ["one", "two", "three"]]
