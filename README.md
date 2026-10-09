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

## Desktop buddy (Mac) 🌱

```bash
python -m groot --gui
```

Or just **double-click `Groot.command`** in Finder. The first time, macOS may
block it: right-click it → **Open** → **Open**.

A little fox (or a tree creature or robot, with `GROOT_ROBOT_STYLE=tree` / `robot`) appears at
the bottom of your screen and plays — walking back and
forth, looking around, waving, jumping and dancing. Pick it up and drop it, and
it falls back down.

- **Say "Hey Groot"** → it stops, looks at you and listens. You can also ask
  straight away: "Hey Groot, what time is it?"
- **Say "stop"** (or "you can stop", "that's all", "goodbye") → it goes back to playing.
- **Ask it to play!** It acts things out on your screen:
  - "Let's play football" ⚽ — a ball appears; Groot chases it and kicks it around the screen
  - "Chase a butterfly" 🦋 — Groot follows a butterfly and jumps to catch it
  - "Dance", "Jump", "Wave", "Run around", "Go to sleep" (zzz until you talk to it), "Stop playing"
- **Click it** to start or stop talking. **Drag it** to pick it up and move it.
- **Right-click** (or Ctrl+click) for the menu: Stay still, Little Groot voice,
  "I am Groot" mode, Quit.
- It shows its mood: ears perk up and eyes glow green when listening, head tilts when thinking

While it's playing, Groot listens for "Hey Groot" using the same speech
recognition as the rest of the app (Google's free service by default, or
offline Whisper with `GROOT_STT=whisper`). Everything it hears is printed in
Terminal as `[heard] ...`, so you can check it's picking you up.

On Mac the buddy's window uses Apple's own AppKit (via PyObjC); on Windows and Linux it
uses Qt (PySide6). Both are installed by `pip install -r requirements.txt`.

## On your phone 📱

Run this on your computer and keep it running:

```bash
python -m groot --phone
```

It prints a link and a QR code. Scan it with your phone's camera and Groot opens:
the same fox, brain, voice and memory. Tap **Share → Add to Home Screen** to use it
like an app.

- **Tap the fox (or 🎤) and talk.** Groot answers out loud and keeps listening until
  you say "stop" or tap again. You can also type.
- Ask it to "dance", "jump" or "wave" and the fox does it on your phone. It can still
  use your computer's apps ("play music on my Mac").
- Phones only allow the microphone on secure **https** links. The plain Wi-Fi link
  works for typing and your keyboard's 🎤 dictation. For tap-to-talk, and to use
  Groot away from home, install Cloudflare's free tunnel once (`brew install cloudflared`
  on Mac) — Groot then prints a secure https link and QR code automatically.
- The link contains a secret key (saved in `~/.groot/phone_key`), so only you can
  use it. Keep it private; delete that file to make a new key.

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

**Notifications:** Groot reads new Mac notifications out loud as they arrive
(Slack, WhatsApp, Mail, Messages, Calendar, …) and shows them above the robot.
While you're talking to it, it waits and reads them afterwards. You can also
ask "What notifications did I get in the last hour?" To allow this, open
**System Settings → Privacy & Security → Full Disk Access** and turn on
**Terminal**, then restart Groot. Turn reading aloud off from the robot's
right-click menu, or with `GROOT_READ_NOTIFICATIONS=false`. Groot only reads
notifications — it never changes or deletes them.

**Safety:** Groot never sends an email or Slack message until you say "yes"
to what it reads back. That check is in the code, not just the AI's
instructions, so nothing in an email or message can trick it into sending.
Saying anything else, saying "stop", or waiting 2 minutes cancels it. Keep
your `.env` private: the Slack token can read and send your messages.

## Memory 🧠

Groot remembers you between restarts, so you don't have to repeat yourself:

- When you tell it something lasting — "My name is Sajib", "My sister is Mitu",
  "I love football", "I start work at 9" — it saves it and knows it from then on.
- "Remember that my car is parked on level 2" / "What do you remember about me?" /
  "Forget my car".
- It also remembers the last few things you talked about, so after a restart it can
  pick up where you left off. "New conversation" clears that (saved facts stay).

Memories are stored on your computer in `~/.groot/memory.json` (facts) and
`~/.groot/recent.json` (recent chat). They're sent to the AI along with your
questions so it can use them — Groot is told never to save passwords or other secrets.

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
| `GROOT_VOICE_STYLE` | `natural` | `natural` (real-sounding male voice), `natural-female`, `baby` (child voice), `little`, `normal`, or `custom` to use the `GROOT_EDGE_*` settings |
| `GROOT_EDGE_VOICE` | `en-US-AndrewNeural` | Natural voice (list: `edge-tts --list-voices`) |
| `GROOT_EDGE_PITCH` | `+30Hz` | Little Groot pitch for the natural voice (`+0Hz` normal) |
| `GROOT_DRAMATIC_VOICE` | `false` | Act out each sentence (excited lines go up, questions rise, "..." slows down) |
| `GROOT_PERSONALITY` | `friendly` | `friendly` = warm and cheerful; `baby` = toddler talk; `cute` = very dramatic; `plain` = normal assistant |
| `GROOT_TREE_VOICE` | `true` | Little Groot voice (Mac). `false` = normal voice |
| `GROOT_VOICE_PITCH` | `1.25` | Higher = smaller, cuter voice. `1.0` normal, `0.8` big deep Groot |
| `GROOT_I_AM_GROOT` | `false` | Only say "I am Groot" out loud; show the real answer as text |
| `GROOT_VOICE` | — | Mac voice, e.g. `Samantha` or `Daniel` (list: `say -v '?'`) |
| `GROOT_ROBOT_STYLE` | `fox` | `fox` (realistic red fox), `flat-fox` (flat illustration), `cute-fox` (round cartoon), `tree` or `robot` |
| `GROOT_ROBOT_SIZE` | `0.6` | Desktop robot size (`1.0` = big) |
| `GROOT_READ_NOTIFICATIONS` | `true` | Read new Mac notifications aloud (needs Full Disk Access) |
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
  notifications.py reads new Mac notifications
  memory.py     long-term memory (facts about you and recent chat)
  phone.py / phone_app.html  Groot on your phone (web app served from your computer)
  buddy.py      the desktop buddy: behaviour and drawing
  mac_window.py / qt_window.py  its window on Mac (AppKit) / Windows and Linux (Qt)
  voice.py      microphone (speech-to-text) and speaker (text-to-speech)
  config.py     settings from .env
tests/          run with: pip install pytest && pytest
```

## Adding a new skill

1. Add a method to the `Skills` class in `groot/skills.py` that returns a string.
2. Add a matching entry to the `TOOLS` list (name, description, input schema).

The brain (Claude, Groq or Ollama) will automatically decide when to use it.
