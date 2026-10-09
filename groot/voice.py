"""Ears (speech-to-text) and mouth (text-to-speech)."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

# Groot voice: a male Mac voice, recorded and then played back lower and slower
# so it sounds deep, warm and tree-like. Voices in order of preference.
GROOT_VOICES = ["Ralph", "Fred", "Bruce", "Daniel", "Alex", "Tom", "Aaron"]
GROOT_SAY_RATE = 165  # words per minute before slowing down
GROOT_PITCH = 0.80  # 0.80 = about 4 semitones deeper and 20% slower


def installed_mac_voices() -> set:
    try:
        output = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return set()
    return {line.split("  ")[0].strip() for line in output.splitlines() if line.strip()}


def deepen(src: str, dst: str, factor: float = GROOT_PITCH) -> None:
    """Make a WAV file deeper and slower by playing it back at a lower sample rate."""
    with wave.open(src, "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())
    with wave.open(dst, "wb") as writer:
        writer.setparams(params)
        writer.setframerate(max(8000, int(params.framerate * factor)))
        writer.writeframes(frames)


def i_am_groot(answer: str) -> str:
    """What Groot says out loud in "I am Groot" mode, matching the answer's mood."""
    text = answer.strip()
    if text.endswith("?"):
        return "I am Groot?"
    if "!" in text or "haha" in text.lower():
        return "I am Groot!"
    if len(text) > 200:
        return "I am Groot. I am Groot... I am Groot."
    if len(text) > 80:
        return "I am Groot. I am Groot."
    return "I am Groot."


class Speaker:
    def __init__(self, rate: int = 180, voice: str = "", tree_voice: bool = True):
        self.rate = rate
        self.voice = voice
        self.tree_voice = tree_voice  # deep, slow Groot voice (Mac)
        self._stopped = False
        self._tree_voice_name = None
        self._lock = threading.Lock()
        # On macOS, pyttsx3 often goes silent after a couple of sentences,
        # so use the built-in `say` command there instead.
        self.use_mac_say = sys.platform == "darwin" and shutil.which("say") is not None
        self._process = None
        if not self.use_mac_say:
            import pyttsx3

            self.pyttsx3 = pyttsx3

    def say(self, text: str) -> None:
        with self._lock:
            self._stopped = False
            if self.use_mac_say:
                if self.tree_voice:
                    try:
                        self._say_groot(text)
                        return
                    except Exception as exc:
                        print(f"[Groot voice failed, using normal voice: {exc}]")
                command = ["say", "-r", str(self.rate)]
                if self.voice:
                    command += ["-v", self.voice]
                self._run(command + [text])
                return
            # A fresh engine each time avoids pyttsx3 getting stuck after the first reply
            engine = self.pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.say(text)
            engine.runAndWait()
            engine.stop()

    def _say_groot(self, text: str) -> None:
        voice = self.voice or self._groot_voice()
        with tempfile.TemporaryDirectory() as folder:
            raw = os.path.join(folder, "raw.wav")
            deep = os.path.join(folder, "groot.wav")
            command = ["say", "-r", str(GROOT_SAY_RATE), "-o", raw, "--data-format=LEI16@22050"]
            if voice:
                command += ["-v", voice]
            self._run(command + [text])
            if self._stopped:
                return
            deepen(raw, deep)
            self._run(["afplay", deep])

    def _run(self, command: list) -> None:
        self._process = subprocess.Popen(command)
        self._process.wait()
        self._process = None

    def _groot_voice(self) -> str:
        if self._tree_voice_name is None:
            installed = installed_mac_voices()
            self._tree_voice_name = next((v for v in GROOT_VOICES if v in installed), "")
        return self._tree_voice_name

    def stop(self) -> None:
        """Cut off whatever is being said right now (Mac only)."""
        self._stopped = True
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()


class Listener:
    def __init__(self, engine: str = "google", whisper_model: str = "base"):
        import speech_recognition as sr

        self.sr = sr
        self.engine = engine
        self.whisper_model = whisper_model
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self._mic_lock = threading.Lock()  # only one listener at a time
        self.microphone = sr.Microphone()
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)

    def listen(self, timeout: float = None, phrase_limit: float = 15) -> str:
        """Record one phrase and return it as text ('' if nothing understood)."""
        with self._mic_lock, self.microphone as source:
            try:
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_limit
                )
            except self.sr.WaitTimeoutError:
                return ""
        try:
            if self.engine == "whisper":
                # Runs offline on your computer (pip install openai-whisper)
                return self.recognizer.recognize_whisper(
                    audio, model=self.whisper_model, language="english"
                ).strip()
            return self.recognizer.recognize_google(audio).strip()
        except self.sr.UnknownValueError:
            return ""
        except self.sr.RequestError as exc:
            print(f"[speech service error: {exc}]")
            return ""
