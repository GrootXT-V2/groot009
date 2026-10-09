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
    name: str = field(default_factory=lambda: os.getenv("GROOT_NAME", "Kurama"))
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
            for w in os.getenv("GROOT_WAKE_WORDS", "hay kurama,hey kurama,kurama").split(",")
            if w.strip()
        )
    )
    use_wake_word: bool = field(default_factory=lambda: _bool("GROOT_USE_WAKE_WORD", True))
    stt_engine: str = field(default_factory=lambda: os.getenv("GROOT_STT", "google"))
    whisper_model: str = field(default_factory=lambda: os.getenv("GROOT_WHISPER_MODEL", "base"))
    tts: str = field(default_factory=lambda: os.getenv("GROOT_TTS", "edge").lower())
    # natural (default), natural-female, baby, little, normal - or custom to use the GROOT_EDGE_* settings below
    voice_style: str = field(default_factory=lambda: os.getenv("GROOT_VOICE_STYLE", "natural").lower())
    edge_voice: str = field(default_factory=lambda: os.getenv("GROOT_EDGE_VOICE", "en-US-AndrewNeural"))
    edge_pitch: str = field(default_factory=lambda: os.getenv("GROOT_EDGE_PITCH", "+30Hz"))
    edge_rate: str = field(default_factory=lambda: os.getenv("GROOT_EDGE_RATE", "+5%"))

    def __post_init__(self):
        from .voice import VOICE_STYLES

        if self.voice_style in VOICE_STYLES:  # a preset wins over the individual settings
            self.edge_voice, self.edge_pitch, self.edge_rate = VOICE_STYLES[self.voice_style]
    voice: str = field(default_factory=lambda: os.getenv("GROOT_VOICE", ""))
    dramatic_voice: bool = field(default_factory=lambda: _bool("GROOT_DRAMATIC_VOICE", False))
    tree_voice: bool = field(default_factory=lambda: _bool("GROOT_TREE_VOICE", True))
    voice_pitch: float = field(default_factory=lambda: float(os.getenv("GROOT_VOICE_PITCH", "1.25")))
    i_am_groot: bool = field(default_factory=lambda: _bool("GROOT_I_AM_GROOT", False))
    voice_rate: int = field(default_factory=lambda: int(os.getenv("GROOT_VOICE_RATE", "180")))
    robot_style: str = field(default_factory=lambda: os.getenv("GROOT_ROBOT_STYLE", "fox").lower())
    robot_size: float = field(default_factory=lambda: float(os.getenv("GROOT_ROBOT_SIZE", "0.6")))
    read_notifications: bool = field(default_factory=lambda: _bool("GROOT_READ_NOTIFICATIONS", True))
    slack_token: str = field(default_factory=lambda: os.getenv("SLACK_TOKEN", ""))
    city: str = field(default_factory=lambda: os.getenv("GROOT_CITY", ""))
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("GROOT_DATA_DIR", Path.home() / ".groot"))
    )
