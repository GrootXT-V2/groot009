"""Ears (speech-to-text) and mouth (text-to-speech)."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
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
EDGE_GROOT_PITCH = "+30Hz"
EDGE_RATE = "+5%"


def _hz(pitch: str) -> int:
    try:
        return int(pitch.lower().replace("hz", ""))
    except ValueError:
        return 0


def _percent(rate: str) -> int:
    try:
        return int(rate.replace("%", ""))
    except ValueError:
        return 0


def dramatic_prosody(sentence: str, base_pitch: str = EDGE_GROOT_PITCH, base_rate: str = EDGE_RATE) -> tuple:
    """(rate, pitch) for one sentence, so the voice acts out each line:
    excited lines go up and speed up, questions rise, '...' slows right down."""
    base = _hz(base_pitch)
    speed = _percent(base_rate)
    text = sentence.strip()
    lowered = text.lower()
    rate, pitch = 0, base  # rate is relative to the base speed
    if text.endswith("!") or lowered.startswith(("wow", "yay", "ooh", "whoa", "oh my")):
        rate, pitch = 9, base + 18
    elif text.endswith("?"):
        rate, pitch = -2, base + 12
    if "..." in text or "…" in text:
        rate, pitch = -17, base - 6
    if lowered.startswith(("oh no", "aww", "sniff", "uh oh", "uh-oh")):
        rate, pitch = -13, base + 6
    if lowered.startswith(("hehe", "haha", "teehee")):
        rate, pitch = 13, base + 22
    return f"{speed + rate:+d}%", f"{pitch:+d}Hz"


# Voice styles for the natural voice: (voice, pitch, speed)
VOICE_STYLES = {
    "baby": ("en-US-AnaNeural", "+15Hz", "+0%"),  # a real child's voice, a little higher
    "little": ("en-US-AndrewNeural", "+30Hz", "+5%"),  # a young man's voice pitched up
    "normal": ("en-US-AndrewNeural", "+0Hz", "+0%"),
}

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
                 edge_pitch: str = EDGE_GROOT_PITCH, dramatic: bool = True, edge_rate: str = EDGE_RATE):
        self.edge_rate = edge_rate
        self.dramatic = dramatic  # act out each sentence (excited, curious, sad...)
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

        All sentences are prepared at the same time (in parallel) and played
        in order as soon as each is ready, so there are no waits in between.
        """
        import edge_tts

        pitch = self.edge_pitch if self.tree_voice else "+0Hz"
        # dramatic mode speaks sentences separately so each gets its own emotion
        sentences = split_sentences(text, min_length=14 if self.dramatic else 25) or [text]

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            def prepare(i, sentence):
                if self._stopped:
                    return None
                path = os.path.join(folder, f"{i}.mp3")
                rate, line_pitch = (dramatic_prosody(sentence, pitch, self.edge_rate) if self.dramatic
                                    else (self.edge_rate, pitch))
                speech = edge_tts.Communicate(sentence, self.edge_voice, rate=rate, pitch=line_pitch)
                asyncio.run(speech.save(path))
                return path

            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = [pool.submit(prepare, i, sentence) for i, sentence in enumerate(sentences)]
                played = 0
                for job in jobs:
                    try:
                        path = job.result(timeout=30)
                    except Exception:
                        if played == 0:
                            raise  # nothing spoken yet: fall back to the Mac voice
                        break
                    if self._stopped or path is None:
                        break
                    self._run(["afplay", path])
                    played += 1

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
        # notice sooner that you've finished talking (default waits 0.8 s of silence)
        self.recognizer.pause_threshold = 0.5
        self.recognizer.non_speaking_duration = 0.3
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
