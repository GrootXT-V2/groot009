"""Things Groot can do. Each skill is a plain function plus a tool schema for Claude."""

import json
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable


CONFIRM_SECONDS = 120  # a waiting email/message is dropped after this long

YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "send it", "do it", "go ahead", "confirm",
             "ok", "okay", "yes please", "yes send it", "please do", "correct", "send"}
NO_WORDS = {"no", "nope", "cancel", "don't", "dont", "don't send it", "do not send", "stop",
            "never mind", "nevermind", "no thanks", "wait"}


class Skills:
    def __init__(self, data_dir: Path, default_city: str = "", announce: Callable[[str], None] = print,
                 slack_token: str = "", mac_apps: bool = None):
        from .integrations import MAC_TOOLS, SLACK_TOOLS, MacApps, Slack, mac_available
        from .notifications import NOTIFICATION_TOOLS, Notifications
        from .memory import MEMORY_TOOLS, Memory

        self.data_dir = Path(data_dir)
        self.default_city = default_city
        self.announce = announce
        self.notes_file = self.data_dir / "notes.json"
        self.pending = None  # (description, action) waiting for the user to say yes

        # long-term memory that survives restarts
        self.memory = Memory(self.data_dir)

        # extra abilities: (object with the methods, its tool schemas)
        self.integrations = [(self.memory, MEMORY_TOOLS)]
        if mac_available() if mac_apps is None else mac_apps:
            self.integrations.append((MacApps(self.ask_confirmation), MAC_TOOLS))
            self.integrations.append((Notifications(), NOTIFICATION_TOOLS))
        if slack_token:
            self.integrations.append((Slack(slack_token, self.ask_confirmation), SLACK_TOOLS))

    @property
    def tools(self) -> list:
        return TOOLS + [tool for _, tools in self.integrations for tool in tools]

    # ---- confirming actions that send things on the user's behalf -----------

    def ask_confirmation(self, description: str, action: Callable[[], str]) -> str:
        self.pending = (description, action, time.monotonic())
        return ("NOT DONE YET. Read this back to the user in one short sentence and ask them to say "
                f"yes to confirm or no to cancel: I'm about to {description}")

    def handle_confirmation(self, text: str):
        """If something is waiting for a yes/no, handle the answer and return what to say.

        Returns None when nothing is waiting (or the user said something else,
        which cancels the waiting action to be safe)."""
        if self.pending is None:
            return None
        description, action, asked_at = self.pending
        self.pending = None
        if time.monotonic() - asked_at > CONFIRM_SECONDS:
            return None  # too old: never send something the user may have forgotten about
        answer = " ".join(text.lower().replace(",", " ").replace(".", " ").replace("!", " ").split())
        answer = answer.removeprefix("groot ").removeprefix("hey groot ")
        if answer in YES_WORDS or answer.startswith(("yes ", "yeah ", "sure ")):
            try:
                return action()
            except Exception as exc:
                return f"Sorry, that didn't work: {exc}"
        if answer in NO_WORDS or answer.startswith(("no ", "don't ", "cancel ")):
            return "Okay, I cancelled it."
        return None  # something else: the action is dropped and we carry on normally

    # ---- skills -------------------------------------------------------------

    def get_time(self) -> str:
        now = datetime.now()
        return now.strftime("It is %I:%M %p on %A, %B %d, %Y.")

    def get_weather(self, city: str = "") -> str:
        city = city or self.default_city
        if not city:
            return "No city given. Ask the user which city they want the weather for."
        geo = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": city, "count": 1})
        )
        if not geo.get("results"):
            return f"Could not find a place called {city}."
        place = geo["results"][0]
        weather = _get_json(
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                    "forecast_days": 1,
                }
            )
        )
        current = weather["current"]
        daily = weather["daily"]
        return json.dumps(
            {
                "place": f"{place['name']}, {place.get('country', '')}",
                "temperature_c": current["temperature_2m"],
                "feels_like_c": current["apparent_temperature"],
                "humidity_percent": current["relative_humidity_2m"],
                "wind_kmh": current["wind_speed_10m"],
                "condition": WEATHER_CODES.get(current["weather_code"], "unknown"),
                "today_high_c": daily["temperature_2m_max"][0],
                "today_low_c": daily["temperature_2m_min"][0],
                "rain_chance_percent": daily["precipitation_probability_max"][0],
            }
        )

    def open_website(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened {url}."

    def search_web(self, query: str) -> str:
        webbrowser.open("https://www.google.com/search?" + urllib.parse.urlencode({"q": query}))
        return f"Opened a web search for '{query}'."

    def set_timer(self, seconds: int, label: str = "Timer") -> str:
        seconds = max(1, int(seconds))
        timer = threading.Timer(seconds, self.announce, args=[f"{label} is done!"])
        timer.daemon = True
        timer.start()
        return f"Timer '{label}' set for {seconds} seconds."

    def add_note(self, text: str) -> str:
        notes = self._load_notes()
        notes.append({"text": text, "created": datetime.now().isoformat(timespec="minutes")})
        self._save_notes(notes)
        return f"Saved note. You now have {len(notes)} notes."

    def read_notes(self) -> str:
        notes = self._load_notes()
        if not notes:
            return "There are no notes."
        return json.dumps(notes)

    def clear_notes(self) -> str:
        self._save_notes([])
        return "All notes deleted."

    # ---- plumbing -----------------------------------------------------------

    def _load_notes(self) -> list:
        if not self.notes_file.exists():
            return []
        return json.loads(self.notes_file.read_text(encoding="utf-8"))

    def _save_notes(self, notes: list) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notes_file.write_text(json.dumps(notes, indent=2), encoding="utf-8")

    def run(self, name: str, args: dict) -> str:
        func = getattr(self, name, None) if name in TOOL_NAMES else None
        for owner, tools in self.integrations:
            if any(tool["name"] == name for tool in tools):
                func = getattr(owner, name, None)
        if func is None:
            return f"Unknown skill: {name}"
        try:
            return func(**args)
        except Exception as exc:  # report errors back to Claude instead of crashing
            return f"Error running {name}: {exc}"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}

TOOLS = [
    {
        "name": "get_time",
        "description": "Get the current local date and time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_weather",
        "description": "Get current weather and today's forecast for a city. Leave city empty to use the user's home city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name, e.g. 'Dhaka'"}},
        },
    },
    {
        "name": "open_website",
        "description": "Open a website in the user's browser.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "e.g. 'youtube.com'"}},
            "required": ["url"],
        },
    },
    {
        "name": "search_web",
        "description": "Open a Google search in the user's browser.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "set_timer",
        "description": "Set a countdown timer. Groot announces out loud when it finishes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Duration in seconds"},
                "label": {"type": "string", "description": "What the timer is for"},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "add_note",
        "description": "Save a note or reminder for the user.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "read_notes",
        "description": "Read all of the user's saved notes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "clear_notes",
        "description": "Delete all saved notes. Only use when the user clearly asks.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_NAMES = {tool["name"] for tool in TOOLS}
