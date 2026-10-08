"""The thinking part: sends what you said to Claude and lets it use skills."""

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
