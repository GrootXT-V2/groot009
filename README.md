# 🌱 Groot — your personal voice assistant

Talk to Groot and it talks back. It can run **100% free** on your own computer
(using [Ollama](https://ollama.com)), or use Claude as its brain. It can tell
the time, check the weather, open websites, search the web, set timers, and
keep notes for you.

```
🎤 you speak → speech-to-text → Claude (+ skills) → text-to-speech → 🔊 Groot answers
```

## Setup

Needs **Python 3.10+** and a microphone.

```bash
git clone <this repo> && cd groot009
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Choose a brain

**Free and fast (recommended): Groq.** Runs online, answers in about a second.
1. Sign up free at <https://console.groq.com> (no credit card) and create a key
   under **API Keys**.
2. Put it in `.env`: `GROQ_API_KEY=gsk_...`

**Free and offline: Ollama.** Runs on your computer, no account needed, but
can be slow on older or low-memory computers.
1. Download and install Ollama from <https://ollama.com>, then open the Ollama app.
2. Download a model (about 2 GB, one time):
   ```bash
   ollama pull llama3.2
   ```
That's it — with no API keys in `.env`, Groot uses Ollama automatically.
On older or low-memory computers, try the smaller `llama3.2:1b`
(set `GROOT_OLLAMA_MODEL=llama3.2:1b` in `.env`). For smarter answers on a
powerful machine, try `qwen2.5:7b`.

**Claude (paid, smartest):** put your API key from
<https://console.anthropic.com> in `.env` as `ANTHROPIC_API_KEY=...`.

**If `pyaudio` fails to install:**
- **Windows:** `pip install pipwin && pipwin install pyaudio`
- **Mac:** `brew install portaudio && pip install pyaudio`
- **Linux:** `sudo apt install portaudio19-dev python3-pyaudio espeak-ng && pip install pyaudio`
  (`espeak-ng` is the voice used on Linux)

## Run it

```bash
python -m groot             # voice mode — say "Hey Groot, what's the weather?"
python -m groot --no-wake   # answers everything you say, no wake word needed
python -m groot --text      # type instead of talking (good for testing)
python -m groot --text --mute   # fully text-only
```

Things to try:
- "Hey Groot, what time is it?"
- "Hey Groot, what's the weather in London?"
- "Hey Groot, open YouTube"
- "Hey Groot, set a timer for 5 minutes for tea"
- "Hey Groot, remember that I need to call mom tomorrow" / "read my notes"
- "Hey Groot, explain black holes simply"
- "Hey Groot, new conversation" — forgets the chat so far
- "Hey Groot, goodbye" — quits (or press Ctrl+C)

## Settings (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `GROOT_BRAIN` | `auto` | `auto`, `groq` (free, fast), `ollama` (free, local) or `claude` (paid) |
| `GROQ_API_KEY` | — | Free Groq key (for the Groq brain) |
| `GROOT_GROQ_MODEL` | auto | Which Groq model to use (empty = pick automatically) |
| `GROOT_OLLAMA_MODEL` | `llama3.2` | Which Ollama model to use |
| `ANTHROPIC_API_KEY` | — | Claude API key (only for the Claude brain) |
| `GROOT_NAME` | `Groot` | Assistant's name |
| `GROOT_MODEL` | `claude-sonnet-5-5` | Claude model to use |
| `GROOT_WAKE_WORDS` | `hey groot,groot` | Comma-separated wake phrases |
| `GROOT_USE_WAKE_WORD` | `true` | Require the wake word |
| `GROOT_STT` | `google` | `google` (free, online) or `whisper` (offline; `pip install openai-whisper`) |
| `GROOT_WHISPER_MODEL` | `base` | Whisper size: `tiny`, `base`, `small`, `medium` |
| `GROOT_VOICE_RATE` | `180` | Speaking speed |
| `GROOT_CITY` | — | Home city for weather |

Notes are saved in `~/.groot/notes.json`.

## Project layout

```
groot/
  __main__.py   start-up and command-line options
  assistant.py  main loop: wake word → listen → think → speak
  brain.py      talks to Claude, Groq or Ollama, runs skills it asks for
  skills.py     what Groot can do (add your own here!)
  voice.py      microphone (speech-to-text) and speaker (text-to-speech)
  config.py     settings from .env
tests/          run with: pip install pytest && pytest
```

## Adding a new skill

1. Add a method to the `Skills` class in `groot/skills.py` that returns a string.
2. Add a matching entry to the `TOOLS` list (name, description, input schema).

The brain (Claude, Groq or Ollama) will automatically decide when to use it.
