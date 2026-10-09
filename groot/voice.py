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
import hashlib
from pathlib import Path
from array import array
from .speech import UncertainTranscription, correct_app_command, transcribe_groq

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


LAUGHS = re.compile(r"\b(?:he){2,}h?\b|\b(?:ha){2,}h?\b|\b(?:hi){2,}\b|\btee+hee+\b|\blo+l\b|\blmao\b"
                    r"|\bgiggles?\b|\bteehee\b", re.IGNORECASE)
ACTIONS = re.compile(r"\*[^*]{1,60}\*|\[[^\]]{1,60}\]")  # *giggles*, [laughs]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")


def clean_for_speech(text: str) -> str:
    """Remove things a voice can't say naturally: laughs like 'hehe', *actions*, emoji."""
    text = EMOJI.sub("", LAUGHS.sub("", ACTIONS.sub("", text)))
    text = re.sub(r"\s+([!?.,])", r"\1", text)  # no space before punctuation left behind
    text = re.sub(r"(^|[.!?]\s*)[!?.,]+\s*", r"\1", text)  # drop orphaned "!" from removed words
    return " ".join(text.split()).strip()


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
    "kurama": ("en-US-AndrewNeural", "-28Hz", "-8%"),  # deep voice, measured delivery
    # Microsoft's newest, most human-sounding voices, with no pitch tricks
    "natural": ("en-US-AndrewMultilingualNeural", "+0Hz", "+0%"),
    "natural-female": ("en-US-AvaMultilingualNeural", "+0Hz", "+0%"),
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
    def _voice_for_text(self, text):
        if re.search(r'[\u0980-\u09ff]', text):
            return os.getenv('GROOT_BANGLA_VOICE', 'bn-BD-PradeepNeural')
        return self.edge_voice

    def __init__(self, rate: int = 180, voice: str = "", tree_voice: bool = True,
                 pitch: float = GROOT_PITCH, engine: str = "edge", edge_voice: str = EDGE_VOICE,
                 edge_pitch: str = EDGE_GROOT_PITCH, dramatic: bool = True, edge_rate: str = EDGE_RATE):
        self.edge_rate = edge_rate
        self.dramatic = dramatic  # act out each sentence (excited, curious, sad...)
        self.engine = engine  # "edge" (natural, online) or "mac" (built-in voices)
        self.edge_voice = edge_voice
        self.edge_pitch = edge_pitch
        self.rate = rate
        self.pitch = pitch
        self.voice = voice
        self.tree_voice = tree_voice  # deep, slow Groot voice (Mac)
        self._stopped = False
        self._tree_voice_name = None
        self._lock = threading.Lock()
        self._audio_cache = {}
        self._speech_guard = threading.Lock()
        self.audio_epoch = 0
        self.speaking = threading.Event()
        self.last_speech_end = 0.0
        # On macOS, pyttsx3 often goes silent after a couple of sentences,
        # so use the built-in `say` command there instead.
        self.use_mac_say = sys.platform == "darwin" and shutil.which("say") is not None
        self._process = None
        if not self.use_mac_say:
            import pyttsx3

            self.pyttsx3 = pyttsx3

    def say(self, text: str):
        with self._speech_guard:
            return self._tracked_say(text)

    def _tracked_say(self, text: str):
        self.audio_epoch += 1
        self.speaking.set()
        try:
            return self._say_impl(text)
        finally:
            self.last_speech_end = time.monotonic()
            self.audio_epoch += 1
            self.speaking.clear()

    def _say_impl(self, text: str):
        text = clean_for_speech(text)
        if not text:
            return
        with self._lock:
            self._stopped = False
            if self.engine == "edge":
                # Keep the selected voice even during service failures.
                # A different synthesizer changes the character's voice entirely.
                if self._can_use_edge():
                    for attempt in range(2):
                        if self._stopped:
                            return
                        try:
                            return self._say_edge(text)
                        except Exception as exc:
                            print(f"[selected voice attempt {attempt + 1} failed: {type(exc).__name__}]", flush=True)
                print("[selected voice unavailable; reply remains on screen]", flush=True)
                return False
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
        if self.engine != "edge":
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

        if not self.dramatic and shutil.which("ffplay"):
            return self._stream_edge(text)

        pitch = self.edge_pitch if self.tree_voice else "+0Hz"
        # dramatic mode speaks sentences separately so each gets its own emotion
        # Ordinary dialogue needs full context for smooth phrasing and intonation.
        sentences = (split_sentences(text, min_length=14) or [text]) if self.dramatic else [text]

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            def prepare(i, sentence):
                if self._stopped:
                    return None
                path = os.path.join(folder, f"{i}.mp3")
                rate, line_pitch = (dramatic_prosody(sentence, pitch, self.edge_rate) if self.dramatic
                                    else (self.edge_rate, pitch))
                voice = self._voice_for_text(sentence)
                key = (sentence, voice, rate, line_pitch)
                cached = self._audio_cache.get(key)
                if cached is not None:
                    with open(path, "wb") as output:
                        output.write(cached)
                    return path
                speech = edge_tts.Communicate(sentence, voice, rate=rate, pitch=line_pitch,
                                              connect_timeout=3, receive_timeout=5)
                async def save_bounded():
                    await asyncio.wait_for(speech.save(path), timeout=8)
                asyncio.run(save_bounded())
                with open(path, "rb") as source:
                    audio = source.read()
                if not audio:
                    raise RuntimeError("Empty speech audio")
                if len(self._audio_cache) >= 32:
                    self._audio_cache.pop(next(iter(self._audio_cache)))
                self._audio_cache[key] = audio
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

    def _stream_edge(self, text):
        """Play the selected voice as it arrives; cache complete audio privately."""
        import edge_tts
        pitch = self.edge_pitch if self.tree_voice else "+0Hz"
        voice = self._voice_for_text(text)
        key = hashlib.sha256(repr((text, voice, pitch, self.edge_rate)).encode()).hexdigest()
        folder = Path(tempfile.gettempdir()) / f"kurama-voice-{os.getuid()}"
        folder.mkdir(mode=0o700, exist_ok=True)
        path = folder / (key + '.mp3')
        if path.is_file() and path.stat().st_size:
            self._run(['afplay', str(path)])
            return
        received = bytearray()
        player = None
        started = time.monotonic()
        async def stream():
            nonlocal player
            speech = edge_tts.Communicate(text, voice, rate=self.edge_rate,
                                         pitch=pitch, connect_timeout=5, receive_timeout=12)
            async for chunk in speech.stream():
                if self._stopped:
                    return
                if chunk['type'] != 'audio':
                    continue
                if player is None:
                    print(f'[voice audio ready in {time.monotonic() - started:.1f}s]', flush=True)
                    player = subprocess.Popen(
                        ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'error',
                         '-probesize', '32', '-analyzeduration', '0', '-f', 'mp3', '-i', 'pipe:0'],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self._process = player
                player.stdin.write(chunk['data'])
                player.stdin.flush()
                received.extend(chunk['data'])
        try:
            asyncio.run(stream())
            if player is not None:
                player.stdin.close()
                result = player.wait()
                if result != 0 and not self._stopped:
                    raise RuntimeError('Audio player failed')
            if received and not self._stopped:
                temporary = path.with_suffix('.tmp')
                temporary.write_bytes(received)
                temporary.replace(path)
                # Bound disk usage to the most recent 64 complete replies.
                files = sorted(folder.glob('*.mp3'), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in files[64:]:
                    old.unlink(missing_ok=True)
            elif not self._stopped:
                raise RuntimeError('No audio received')
        except Exception:
            if player is not None and received:
                # Do not repeat a reply whose beginning has already played.
                print('[voice stream interrupted; full reply remains on screen]', flush=True)
                return False
            raise
        finally:
            if player is not None and player.poll() is None:
                player.terminate()
                player.wait()
            self._process = None

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


def has_voice_activity(audio, threshold):
    """Reject silence, low-level room noise and brief clicks before transcription."""
    samples = array('h', audio.get_raw_data(convert_rate=16000, convert_width=2))
    if sys.byteorder != 'little':
        samples.byteswap()
    active_frames = 0
    for offset in range(0, len(samples) - 319, 320):
        frame = samples[offset:offset + 320]
        rms_squared = sum(value * value for value in frame) / 320
        if rms_squared > max(80, threshold) ** 2:
            active_frames += 1
    return active_frames >= 8  # at least 160 ms, not an isolated click


class Listener:
    def __init__(self, engine: str = "google", whisper_model: str = "base"):
        import speech_recognition as sr

        self.sr = sr
        self.engine = engine
        self.whisper_model = whisper_model
        self._groq_retry_after = 0.0
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = False
        # Keep quiet syllables after a loud greeting: do not adapt the noise
        # threshold to speech or trim away the end of the wake phrase.
        self.recognizer.pause_threshold = 1.2
        self.recognizer.non_speaking_duration = 1.2
        self.recognizer.phrase_threshold = 0.15
        self.recognizer.operation_timeout = 10
        self._mic_lock = threading.Lock()  # only one listener at a time
        self.on_speech_start = None
        self.speaker = None
        self.microphone = sr.Microphone()
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        print(f"[microphone] ready; energy threshold={self.recognizer.energy_threshold:.0f}", flush=True)

    def listen(self, timeout: float = None, phrase_limit: float = 15) -> str:
        """Record one phrase and return it as text ('' if nothing understood)."""
        speaker = self.speaker
        epoch = speaker.audio_epoch if speaker else 0
        if speaker and (speaker.speaking.is_set() or time.monotonic() - speaker.last_speech_end < 0.6):
            time.sleep(0.1)
            return ""
        with self._mic_lock, self.microphone as source:
            try:
                if self.on_speech_start is None:
                    audio = self.recognizer.listen(
                        source, timeout=timeout, phrase_time_limit=phrase_limit
                    )
                else:
                    chunks = self.recognizer.listen(
                        source, timeout=timeout, phrase_time_limit=phrase_limit, stream=True
                    )
                    first = next(chunks)
                    self.on_speech_start()
                    frames = first.frame_data + b"".join(chunk.frame_data for chunk in chunks)
                    audio = self.sr.AudioData(frames, first.sample_rate, first.sample_width)
            except self.sr.WaitTimeoutError:
                return ""
        if speaker and (speaker.speaking.is_set() or speaker.audio_epoch != epoch):
            return ""
        if not has_voice_activity(audio, self.recognizer.energy_threshold):
            return ""
        try:
            if self.engine == "groq" and time.monotonic() >= self._groq_retry_after:
                try:
                    return correct_app_command(transcribe_groq(audio))
                except UncertainTranscription:
                    # Retry this utterance, without disabling Whisper for the
                    # next minute as we do for a service outage.
                    print('[speech unclear; retrying the complete recording]', flush=True)
                except Exception as exc:
                    # Reuse this recording; do not ask the user to repeat it.
                    self._groq_retry_after = time.monotonic() + 60
                    print(f"[Whisper unavailable: {type(exc).__name__}; using Google temporarily]", flush=True)
            if self.engine == "whisper":
                # Runs offline on your computer (pip install openai-whisper)
                language = os.getenv('GROOT_STT_LANGUAGE', 'auto')
                options = {} if language == 'auto' else {'language': language}
                return correct_app_command(self.recognizer.recognize_whisper(
                    audio, model=self.whisper_model, **options
                ).strip())
            return correct_app_command(self.recognizer.recognize_google(
                audio, language=os.getenv('GROOT_GOOGLE_LANGUAGE', 'en-US')).strip())
        except self.sr.UnknownValueError:
            return ""
        except self.sr.RequestError as exc:
            print(f"[speech service error: {exc}]")
            return ""
