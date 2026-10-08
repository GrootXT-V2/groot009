"""Ears (speech-to-text) and mouth (text-to-speech)."""

import threading


class Speaker:
    def __init__(self, rate: int = 180):
        import pyttsx3

        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", rate)
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        with self._lock:
            self.engine.say(text)
            self.engine.runAndWait()


class Listener:
    def __init__(self, engine: str = "google", whisper_model: str = "base"):
        import speech_recognition as sr

        self.sr = sr
        self.engine = engine
        self.whisper_model = whisper_model
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.microphone = sr.Microphone()
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)

    def listen(self, timeout: float = None, phrase_limit: float = 15) -> str:
        """Record one phrase and return it as text ('' if nothing understood)."""
        with self.microphone as source:
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
