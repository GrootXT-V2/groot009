# 🌱 Groot — your personal voice assistant

Talk to Groot and it talks back. It uses Claude as its brain and can tell
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
cp .env.example .env      # then put your Anthropic API key in .env
```

Get an API key at <https://console.anthropic.com>.

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
| `ANTHROPIC_API_KEY` | — | **Required.** Your Claude API key |
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
  brain.py      talks to Claude, runs skills it asks for
  skills.py     what Groot can do (add your own here!)
  voice.py      microphone (speech-to-text) and speaker (text-to-speech)
  config.py     settings from .env
tests/          run with: pip install pytest && pytest
```

## Adding a new skill

1. Add a method to the `Skills` class in `groot/skills.py` that returns a string.
2. Add a matching entry to the `TOOLS` list (name, description, input schema).

Claude will automatically decide when to use it.
