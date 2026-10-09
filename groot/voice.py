"""Ears (speech-to-text) and mouth (text-to-speech)."""

import shutil
import subprocess
import sys
import threading

# Deep classic Mac voices used for the "tree voice", in order of preference
TREE_VOICES = ["Ralph", "Fred", "Bruce"]
TREE_RATE = 135


def installed_mac_voices() -> set:
    try:
        output = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return set()
    return {line.split("  ")[0].strip() for line in output.splitlines() if line.strip()}


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
    def __init__(self, rate: int = 180, voice: str = "", tree_voice: bool = False):
        self.rate = rate
        self.voice = voice
        self.tree_voice = tree_voice  # deep, slow Groot-like voice (Mac)
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
            if self.use_mac_say:
                voice, rate = self.voice, self.rate
                if self.tree_voice:
                    voice, rate = self._tree_voice() or voice, min(rate, TREE_RATE)
                command = ["say", "-r", str(rate)]
                if voice:
                    command += ["-v", voice]
                self._process = subprocess.Popen(command + [text])
                self._process.wait()
                self._process = None
                return
            # A fresh engine each time avoids pyttsx3 getting stuck after the first reply
            engine = self.pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.say(text)
            engine.runAndWait()
            engine.stop()

    def _tree_voice(self) -> str:
        if self._tree_voice_name is None:
            installed = installed_mac_voices()
            self._tree_voice_name = next((v for v in TREE_VOICES if v in installed), "")
        return self._tree_voice_name

    def stop(self) -> None:
        """Cut off whatever is being said right now (Mac only)."""
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
