"""Start Groot:  python -m groot  [--text] [--no-wake]"""

import argparse
import os
import sys

from .assistant import Assistant
from .brain import Brain
from .config import Config
from .skills import Skills


def main() -> None:
    parser = argparse.ArgumentParser(description="Groot, your personal voice assistant")
    parser.add_argument("--text", action="store_true", help="type instead of talking (no microphone needed)")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    parser.add_argument("--no-wake", action="store_true", help="don't require the wake word")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    import anthropic

    config = Config()
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
    brain = Brain(anthropic.Anthropic(), config.model, skills, name=config.name, city=config.city)

    try:
        Assistant(config, brain, speak, listen).run()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
