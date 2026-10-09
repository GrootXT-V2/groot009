"""Groot's long-term memory, kept on your computer between restarts.

- Facts about you ("my sister is Mitu", "I like football"), saved when you
  share them or say "remember ...". They're included in every conversation.
- The last few things you talked about, so Groot can pick up where you left off.

Stored in ~/.groot/memory.json and ~/.groot/recent.json.
"""

import json
import re
from datetime import datetime
from pathlib import Path

MAX_FACTS = 200
RECENT_TURNS = 8  # exchanges carried over after a restart


class Memory:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.facts_file = self.data_dir / "memory.json"
        self.recent_file = self.data_dir / "recent.json"

    # ---- storage

    def _load(self, path) -> list:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self, path, items) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def facts(self) -> list:
        return self._load(self.facts_file)

    # ---- tools the brain can call

    def remember(self, fact: str) -> str:
        fact = " ".join(fact.split()).strip()
        if not fact:
            return "Nothing to remember."
        facts = self.facts
        if any(f["text"].lower() == fact.lower() for f in facts):
            return "I already remember that."
        facts.append({"text": fact, "saved": datetime.now().strftime("%Y-%m-%d")})
        self._save(self.facts_file, facts[-MAX_FACTS:])
        return f"Saved to memory: {fact}"

    def forget(self, about: str) -> str:
        words = [w for w in re.findall(r"\w+", about.lower()) if len(w) > 2]
        if not words:
            return "Tell me what to forget."
        facts = self.facts
        keep = [f for f in facts if not all(w in f["text"].lower() for w in words)]
        removed = len(facts) - len(keep)
        if not removed:
            return f"I don't have anything saved about {about}."
        self._save(self.facts_file, keep)
        return f"Forgot {removed} thing{'s' if removed != 1 else ''} about {about}."

    def list_memories(self) -> str:
        facts = self.facts
        if not facts:
            return "I don't have anything saved yet."
        return "Things I remember:\n" + "\n".join(f"- {f['text']}" for f in facts)

    # ---- conversation carry-over

    def add_turn(self, user: str, assistant: str) -> None:
        turns = self._load(self.recent_file)
        turns.append({"user": user[:500], "groot": assistant[:500]})
        self._save(self.recent_file, turns[-RECENT_TURNS:])

    def clear_recent(self) -> None:
        self._save(self.recent_file, [])

    def prompt_block(self) -> str:
        """Added to the AI's instructions so it always knows what it remembers."""
        parts = []
        facts = self.facts
        if facts:
            parts.append("What you remember about the user (saved from earlier conversations):\n"
                         + "\n".join(f"- {f['text']}" for f in facts))
        turns = self._load(self.recent_file)
        if turns:
            parts.append("The last things you talked about (earlier, possibly before a restart):\n"
                         + "\n".join(f"User: {t['user']}\nYou: {t['groot']}" for t in turns))
        return ("\n\n" + "\n\n".join(parts)) if parts else ""


MEMORY_TOOLS = [
    {"name": "remember",
     "description": "Save a lasting fact about the user to long-term memory, e.g. their name, family, friends, "
                    "likes, routines, important dates, work, or anything they ask you to remember. "
                    "Write it as a short sentence like 'User's sister is named Mitu'. "
                    "Never save passwords, card numbers or other secrets.",
     "input_schema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
    {"name": "forget",
     "description": "Remove saved memories about something when the user asks you to forget it.",
     "input_schema": {"type": "object", "properties": {"about": {"type": "string"}}, "required": ["about"]}},
    {"name": "list_memories",
     "description": "List everything saved in long-term memory.",
     "input_schema": {"type": "object", "properties": {}}},
]
