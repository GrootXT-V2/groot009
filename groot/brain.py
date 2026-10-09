"""The thinking part: sends what you said to an AI model and lets it use skills.

Three brains are available:
- Brain:       Claude (needs an Anthropic API key)
- GroqBrain:   free and fast cloud models from Groq (needs a free Groq API key)
- OllamaBrain: a free model running on your own computer via Ollama
"""

import json
import urllib.request

from .skills import TOOLS, Skills

SYSTEM_PROMPT = """You are {name}, a friendly personal voice assistant.
Your replies are read aloud, so:
- Keep them short (one to three sentences) unless asked for detail.
- Use plain sentences. No markdown, bullet points, emojis, or URLs.
- Say numbers and times the way a person would speak them.
Use your tools whenever they help (time, weather, browser, timers, notes).
{city_line}"""

MAX_HISTORY = 20  # messages kept for context
MAX_TOOL_ROUNDS = 5


class Brain:
    def __init__(self, client, model: str, skills: Skills, name: str = "Groot", city: str = ""):
        self.client = client
        self.model = model
        self.skills = skills
        self.system = SYSTEM_PROMPT.format(
            name=name,
            city_line=f"The user lives in {city}." if city else "",
        )
        self.history: list = []

    def reply(self, text: str) -> str:
        self.history.append({"role": "user", "content": text})

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=self.system,
                tools=TOOLS,
                messages=self.history,
            )
            self.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = self.skills.run(block.name, block.input or {})
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": output}
                    )
            self.history.append({"role": "user", "content": results})

        self._trim_history()
        answer = " ".join(b.text for b in response.content if b.type == "text").strip()
        return answer or "Done."

    def reset(self) -> None:
        self.history.clear()

    def _trim_history(self) -> None:
        # Drop old turns, but always start on a plain user message so
        # tool_use / tool_result pairs are never split.
        while len(self.history) > MAX_HISTORY:
            self.history.pop(0)
            while self.history and not (
                self.history[0]["role"] == "user" and isinstance(self.history[0]["content"], str)
            ):
                self.history.pop(0)


OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
    for tool in TOOLS
]


KEEP_ALIVE = "60m"  # keep the Ollama model in memory between questions


def _post_json(url: str, payload: dict, headers: dict = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "groot-assistant", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OllamaBrain:
    """Free brain: a model running locally in the Ollama app (https://ollama.com)."""

    def __init__(self, model: str, skills: Skills, name: str = "Groot", city: str = "",
                 url: str = "http://localhost:11434", post=_post_json):
        self.model = model
        self.skills = skills
        self.url = url.rstrip("/") + "/api/chat"
        self.post = post
        self.system = SYSTEM_PROMPT.format(
            name=name,
            city_line=f"The user lives in {city}." if city else "",
        )
        self.history: list = []

    def warm_up(self) -> None:
        """Load the model into memory now so the first answer isn't slow."""
        try:
            self.post(self.url, {"model": self.model, "messages": [], "keep_alive": KEEP_ALIVE})
        except Exception:
            pass

    def reply(self, text: str) -> str:
        self.history.append({"role": "user", "content": text})
        message = {}

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.post(
                self.url,
                {
                    "model": self.model,
                    "messages": [{"role": "system", "content": self.system}] + self.history,
                    "tools": OLLAMA_TOOLS,
                    "stream": False,
                    "keep_alive": KEEP_ALIVE,
                },
            )
            message = response.get("message", {})
            self.history.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                break
            for call in tool_calls:
                func = call.get("function", {})
                args = func.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args or "{}")
                self.history.append(
                    {
                        "role": "tool",
                        "tool_name": func.get("name", ""),
                        "content": self.skills.run(func.get("name", ""), args),
                    }
                )

        self._trim_history()
        return (message.get("content") or "").strip() or "Done."

    def reset(self) -> None:
        self.history.clear()

    def _trim_history(self) -> None:
        while len(self.history) > MAX_HISTORY:
            self.history.pop(0)
            while self.history and self.history[0].get("role") != "user":
                self.history.pop(0)


class GroqBrain:
    """Free, fast cloud brain using Groq (https://console.groq.com).

    Groq uses the OpenAI-style chat API, so this also works with other
    OpenAI-compatible services by changing the url.
    """

    def __init__(self, api_key: str, model: str, skills: Skills, name: str = "Groot", city: str = "",
                 url: str = "https://api.groq.com/openai/v1/chat/completions", post=_post_json):
        self.api_key = api_key
        self.model = model
        self.skills = skills
        self.url = url
        self.post = post
        self.system = SYSTEM_PROMPT.format(
            name=name,
            city_line=f"The user lives in {city}." if city else "",
        )
        self.history: list = []

    def reply(self, text: str) -> str:
        self.history.append({"role": "user", "content": text})
        message = {}

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.post(
                self.url,
                {
                    "model": self.model,
                    "messages": [{"role": "system", "content": self.system}] + self.history,
                    "tools": OLLAMA_TOOLS,
                    "max_tokens": 500,
                },
                {"Authorization": f"Bearer {self.api_key}"},
            )
            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            entry = {"role": "assistant", "content": message.get("content") or ""}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            self.history.append(entry)

            if not tool_calls:
                break
            for call in tool_calls:
                func = call.get("function", {})
                try:
                    args = json.loads(func.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": self.skills.run(func.get("name", ""), args),
                    }
                )

        self._trim_history()
        return (message.get("content") or "").strip() or "Done."

    def reset(self) -> None:
        self.history.clear()

    def _trim_history(self) -> None:
        while len(self.history) > MAX_HISTORY:
            self.history.pop(0)
            while self.history and self.history[0].get("role") != "user":
                self.history.pop(0)
