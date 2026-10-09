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

## Desktop robot (Mac) 🤖

```bash
python -m groot --gui
```

Or just **double-click `Groot.command`** in Finder. The first time, macOS may
block it: right-click it → **Open** → **Open**.

A little robot appears at the bottom of your screen and plays — walking back and
forth, looking around, waving, jumping and dancing. Pick it up and drop it, and
it falls back down.

- **Say "Hey Groot"** → it stops, looks at you and listens. You can also ask
  straight away: "Hey Groot, what time is it?"
- **Say "stop"** (or "you can stop", "that's all", "goodbye") → it goes back to playing.
- **Click it** to start or stop talking. **Drag it** to pick it up and move it.
- **Right-click** (or Ctrl+click) for the menu: Stay still, Little Groot voice,
  "I am Groot" mode, Quit.
- Eye colors: 🔵 playing · 🟢 listening · 🟡 thinking · 🩵 talking

While it's playing, Groot listens for "Hey Groot" using the same speech
recognition as the rest of the app (Google's free service by default, or
offline Whisper with `GROOT_STT=whisper`). Everything it hears is printed in
Terminal as `[heard] ...`, so you can check it's picking you up.

The robot window uses Qt (PySide6), installed by `pip install -r requirements.txt`.

## Your apps, email and Slack (Mac)

Groot can use your Mac apps. Just ask:

| Say | What happens |
|---|---|
| "Open Spotify" / "Quit Safari" | Opens or quits any app |
| "Set the volume to 30" | Changes the volume |
| "Play music" / "Next song on Spotify" | Controls Music or Spotify |
| "Open my Downloads folder" | Opens a folder in Finder |
| "Do I have any new emails?" | Lists unread email in the **Mail** app |
| "Read the email from Sam" | Reads one out |
| "Email sam@example.com that I'll be late" | Sends an email — **after you say "yes"** |
| "What's on my calendar today?" | Reads today's events from **Calendar** |
| "Remind me to buy milk" | Adds it to **Reminders** |
| "Run my Morning shortcut" | Runs any shortcut from the **Shortcuts** app |

**Email** works with any account in the Mail app (Gmail, Outlook, iCloud, work
email): add yours in System Settings → Internet Accounts. The first time Groot
uses Mail, Calendar, Reminders or Music, macOS asks whether Terminal may control
it — click **OK**.

**Any other app:** make a shortcut for it in the Shortcuts app (WhatsApp,
Notes, HomeKit lights, Messages, …) and say "run my <name> shortcut".

**Slack** (optional) needs a token:
1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**,
   name it Groot and pick your workspace.
2. **OAuth & Permissions** → **User Token Scopes** → add: `channels:history`,
   `channels:read`, `groups:history`, `groups:read`, `im:history`, `im:read`,
   `im:write`, `users:read`, `chat:write`, `search:read`.
3. Click **Install to Workspace** → **Allow** (a work Slack may need your
   admin to approve it), then copy the **User OAuth Token** (`xoxp-...`).
4. Put it in `.env`: `SLACK_TOKEN=xoxp-...`

Then: "What's new in #general?", "Read my messages from Sam", "Search Slack
for the deadline", "Tell Sam on Slack I'm on my way" (asks for "yes" first).

**Safety:** Groot never sends an email or Slack message until you say "yes"
to what it reads back. That check is in the code, not just the AI's
instructions, so nothing in an email or message can trick it into sending.
Saying anything else, saying "stop", or waiting 2 minutes cancels it. Keep
your `.env` private: the Slack token can read and send your messages.

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
| `GROOT_TTS` | `edge` | `edge` = natural neural voice (free, needs internet), `mac` = built-in Mac voices |
| `GROOT_EDGE_VOICE` | `en-US-AndrewNeural` | Natural voice (list: `edge-tts --list-voices`) |
| `GROOT_EDGE_PITCH` | `+20Hz` | Little Groot pitch for the natural voice (`+0Hz` normal) |
| `GROOT_TREE_VOICE` | `true` | Little Groot voice (Mac). `false` = normal voice |
| `GROOT_VOICE_PITCH` | `1.25` | Higher = smaller, cuter voice. `1.0` normal, `0.8` big deep Groot |
| `GROOT_I_AM_GROOT` | `false` | Only say "I am Groot" out loud; show the real answer as text |
| `GROOT_VOICE` | — | Mac voice, e.g. `Samantha` or `Daniel` (list: `say -v '?'`) |
| `GROOT_ROBOT_SIZE` | `0.6` | Desktop robot size (`1.0` = big) |
| `SLACK_TOKEN` | — | Slack user token (`xoxp-...`) to let Groot read and send Slack messages |
| `GROOT_CITY` | — | Home city for weather |

Notes are saved in `~/.groot/notes.json`.

## Project layout

```
groot/
  __main__.py   start-up and command-line options
  assistant.py  main loop: wake word → listen → think → speak
  brain.py      talks to Claude, Groq or Ollama, runs skills it asks for
  skills.py     what Groot can do (add your own here!)
  integrations.py  Mac apps (Mail, Calendar, Music, Shortcuts...) and Slack
  voice.py      microphone (speech-to-text) and speaker (text-to-speech)
  config.py     settings from .env
tests/          run with: pip install pytest && pytest
```

## Adding a new skill

1. Add a method to the `Skills` class in `groot/skills.py` that returns a string.
2. Add a matching entry to the `TOOLS` list (name, description, input schema).

The brain (Claude, Groq or Ollama) will automatically decide when to use it.
