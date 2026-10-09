"""The main loop that ties ears, brain and mouth together."""

EXIT_WORDS = ("goodbye", "bye", "exit", "quit", "stop listening", "shut down")
RESET_WORDS = ("forget everything", "new conversation", "reset")


def strip_wake_word(text: str, wake_words) -> str | None:
    """Return the command after the wake word, '' if only the wake word was said,
    or None if the wake word wasn't said at all."""
    lowered = text.lower().strip()
    for word in sorted(wake_words, key=len, reverse=True):
        if lowered.startswith(word):
            return text[len(word):].lstrip(" ,.!?").strip()
    return None


class Assistant:
    def __init__(self, config, brain, speak, listen, echo: bool = True):
        self.config = config
        self.echo = echo  # print what was heard (off in text mode, where you typed it)
        self.brain = brain
        self.speak = speak
        self.listen = listen

    def handle(self, text: str) -> bool:
        """Respond to one command. Returns False when the user wants to quit."""
        lowered = text.lower().strip(" .!?")
        if lowered in EXIT_WORDS:
            self.speak("Goodbye!")
            return False
        if lowered in RESET_WORDS:
            self.brain.reset()
            self.speak("Okay, starting fresh.")
            return True
        try:
            answer = self.brain.reply(text)
        except Exception as exc:
            print(f"[error: {exc}]")  # shows the real reason, e.g. a bad API key
            answer = "Sorry, something went wrong. Please try again."
        self.speak(answer)
        return True

    def run(self) -> None:
        name = self.config.name
        if self.config.use_wake_word:
            self.speak(f"{name} is ready. Say '{self.config.wake_words[0]}' to talk to me.")
        else:
            self.speak(f"Hi, I'm {name}. How can I help?")

        while True:
            heard = self.listen()
            if not heard:
                continue
            if self.echo:
                print(f"You: {heard}")

            if self.config.use_wake_word:
                command = strip_wake_word(heard, self.config.wake_words)
                if command is None:
                    continue  # not talking to us
                if not command:
                    self.speak("Yes?")
                    command = self.listen(timeout=8)
                    if not command:
                        continue
                    if self.echo:
                        print(f"You: {command}")
            else:
                command = heard

            if not self.handle(command):
                break
