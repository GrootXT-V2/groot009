"""Start Groot:  python -m groot  [--text] [--no-wake]"""

import argparse
import os
import json
import sys
import urllib.request

from .assistant import Assistant
from .brain import Brain, GroqBrain, OllamaBrain
from .config import Config
from .skills import Skills


def check_ollama(config: Config) -> None:
    """Exit with a helpful message if Ollama isn't running or the model isn't downloaded."""
    try:
        with urllib.request.urlopen(config.ollama_url.rstrip("/") + "/api/tags", timeout=5) as resp:
            models = [m["name"] for m in json.loads(resp.read().decode("utf-8")).get("models", [])]
    except Exception:
        sys.exit(
            "No API key found, so Groot wants to use the free local brain (Ollama), but Ollama isn't running.\n"
            "1. Install it from https://ollama.com and open the Ollama app\n"
            f"2. Run: ollama pull {config.ollama_model}\n"
            "3. Start Groot again"
        )
    wanted = config.ollama_model
    if not any(m == wanted or m.split(":")[0] == wanted for m in models):
        sys.exit(f"The model '{wanted}' isn't downloaded yet. Run: ollama pull {wanted}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Groot, your personal voice assistant")
    parser.add_argument("--text", action="store_true", help="type instead of talking (no microphone needed)")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    parser.add_argument("--no-wake", action="store_true", help="don't require the wake word")
    args = parser.parse_args()

    config = Config()
    brain_kind = config.brain
    if brain_kind == "auto":
        if os.getenv("ANTHROPIC_API_KEY"):
            brain_kind = "claude"
        elif os.getenv("GROQ_API_KEY"):
            brain_kind = "groq"
        else:
            brain_kind = "ollama"
    if brain_kind == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Add it to .env, or set GROOT_BRAIN=ollama to use the free local brain.")
    if brain_kind == "groq" and not os.getenv("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys and add it to .env.")
    if brain_kind == "ollama":
        check_ollama(config)
    if args.no_wake or args.text:
        config.use_wake_word = False

    if args.mute:
        def speak(text):
            print(f"{config.name}: {text}")
    else:
        from .voice import Speaker

        speaker = Speaker(rate=config.voice_rate)

        def speak(text):
            print(f"{config.name}: {text}")
            speaker.say(text)

    if args.text:
        def listen(timeout=None):
            try:
                return input("You: ").strip()
            except EOFError:
                return "exit"
    else:
        from .voice import Listener

        print("Calibrating microphone, stay quiet for a second...")
        ears = Listener(engine=config.stt_engine, whisper_model=config.whisper_model)

        def listen(timeout=None):
            return ears.listen(timeout=timeout)

    skills = Skills(config.data_dir, default_city=config.city, announce=speak)
    if brain_kind == "ollama":
        print(f"Using free local brain: Ollama ({config.ollama_model}). Loading model...")
        brain = OllamaBrain(config.ollama_model, skills, name=config.name, city=config.city,
                            url=config.ollama_url)
        brain.warm_up()
    elif brain_kind == "groq":
        print(f"Using free fast cloud brain: Groq ({config.groq_model or 'auto model'})")
        brain = GroqBrain(os.environ["GROQ_API_KEY"], config.groq_model, skills,
                          name=config.name, city=config.city)
    else:
        import anthropic

        print(f"Using Claude ({config.model})")
        brain = Brain(anthropic.Anthropic(), config.model, skills, name=config.name, city=config.city)

    try:
        Assistant(config, brain, speak, listen, echo=not args.text).run()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
