"""Settings, read from environment variables (or a .env file)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    name: str = field(default_factory=lambda: os.getenv("GROOT_NAME", "Groot"))
    # "auto" picks Claude if ANTHROPIC_API_KEY is set, else Groq if GROQ_API_KEY is set,
    # else free local Ollama
    brain: str = field(default_factory=lambda: os.getenv("GROOT_BRAIN", "auto").lower())
    model: str = field(default_factory=lambda: os.getenv("GROOT_MODEL", "claude-sonnet-5-5"))
    groq_model: str = field(
        default_factory=lambda: os.getenv("GROOT_GROQ_MODEL", "")
    )
    ollama_model: str = field(default_factory=lambda: os.getenv("GROOT_OLLAMA_MODEL", "llama3.2"))
    ollama_url: str = field(
        default_factory=lambda: os.getenv("GROOT_OLLAMA_URL", "http://localhost:11434")
    )
    wake_words: tuple = field(
        default_factory=lambda: tuple(
            w.strip().lower()
            for w in os.getenv("GROOT_WAKE_WORDS", "hey groot,groot").split(",")
            if w.strip()
        )
    )
    use_wake_word: bool = field(default_factory=lambda: _bool("GROOT_USE_WAKE_WORD", True))
    stt_engine: str = field(default_factory=lambda: os.getenv("GROOT_STT", "google"))
    whisper_model: str = field(default_factory=lambda: os.getenv("GROOT_WHISPER_MODEL", "base"))
    voice: str = field(default_factory=lambda: os.getenv("GROOT_VOICE", ""))
    voice_rate: int = field(default_factory=lambda: int(os.getenv("GROOT_VOICE_RATE", "180")))
    city: str = field(default_factory=lambda: os.getenv("GROOT_CITY", ""))
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("GROOT_DATA_DIR", Path.home() / ".groot"))
    )
