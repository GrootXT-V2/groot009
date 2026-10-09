"""Ears (speech-to-text) and mouth (text-to-speech)."""

import asyncio
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave

# Natural voice: Microsoft's free neural voices via the edge-tts package (needs internet).
# Little Groot = a warm young male voice, pitched up a little.
EDGE_VOICE = "en-US-AndrewNeural"
EDGE_GROOT_PITCH = "+20Hz"
EDGE_RATE = "+5%"

# Little Groot voice: a male Mac voice, recorded slowly and then played back
# higher and faster, so it sounds small and cute. Voices in order of preference.
GROOT_VOICES = ["Daniel", "Fred", "Alex", "Tom", "Aaron", "Ralph", "Bruce"]
GROOT_SAY_RATE = 140  # recorded slowly, so after speeding up it's a normal pace
GROOT_PITCH = 1.25  # >1 = higher (1.25 is about 4 semitones), <1 = deeper


def installed_mac_voices() -> set:
    try:
        output = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return set()
    return {line.split("  ")[0].strip() for line in output.splitlines() if line.strip()}


def deepen(src: str, dst: str, factor: float = GROOT_PITCH) -> None:
    """Change a WAV file's pitch by changing its playback sample rate.

    factor > 1 makes it higher and faster; factor < 1 makes it deeper and slower.
    """
    with wave.open(src, "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())
    with wave.open(dst, "wb") as writer:
        writer.setparams(params)
        writer.setframerate(max(8000, int(params.framerate * factor)))
        writer.writeframes(frames)


def split_sentences(text: str, min_length: int = 25) -> list:
    """Split text into sentences, joining very short ones, so speech can start sooner."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    merged = []
    for part in parts:
        if merged and len(merged[-1]) < min_length:
            merged[-1] += " " + part
        else:
            merged.append(part)
    return merged


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
    def __init__(self, rate: int = 180, voice: str = "", tree_voice: bool = True,
                 pitch: float = GROOT_PITCH, engine: str = "edge", edge_voice: str = EDGE_VOICE,
                 edge_pitch: str = EDGE_GROOT_PITCH):
        self.engine = engine  # "edge" (natural, online) or "mac" (built-in voices)
        self.edge_voice = edge_voice
        self.edge_pitch = edge_pitch
        self._edge_down_until = 0.0  # skip edge for a while after a failure (e.g. offline)
        self.rate = rate
        self.pitch = pitch
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
            if self._can_use_edge():
                try:
                    self._say_edge(text)
                    return
                except Exception as exc:
                    self._edge_down_until = time.time() + 120
                    print(f"[natural voice unavailable ({exc}), using Mac voice]")
                    if self._stopped:
                        return
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

    def _can_use_edge(self) -> bool:
        if self.engine != "edge" or time.time() < self._edge_down_until:
            return False
        if shutil.which("afplay") is None:  # audio player built into macOS
            return False
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True

    def _say_edge(self, text: str) -> None:
        """Speak with a natural neural voice, one sentence at a time.

        The next sentence is prepared while the current one plays, so the
        first words start quickly even for long answers.
        """
        import edge_tts

        pitch = self.edge_pitch if self.tree_voice else "+0Hz"
        sentences = split_sentences(text) or [text]
        ready = queue.Queue()

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            def prepare():
                try:
                    for i, sentence in enumerate(sentences):
                        if self._stopped:
                            break
                        path = os.path.join(folder, f"{i}.mp3")
                        speech = edge_tts.Communicate(sentence, self.edge_voice, rate=EDGE_RATE, pitch=pitch)
                        asyncio.run(speech.save(path))
                        ready.put(path)
                except Exception as exc:
                    ready.put(exc)
                ready.put(None)

            worker = threading.Thread(target=prepare, daemon=True)
            worker.start()
            played = 0
            while True:
                item = ready.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    if played == 0:
                        raise item  # nothing spoken yet: fall back to the Mac voice
                    break
                if not self._stopped:
                    self._run(["afplay", item])
                    played += 1
            worker.join(timeout=10)

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
            deepen(raw, deep, self.pitch)
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
