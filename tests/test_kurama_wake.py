import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groot.buddy import Buddy
from groot.gui import Session, find_wake_word, is_stop_command, WAKE_REPLIES


class KuramaWakeTests(unittest.TestCase):
    def test_name_and_greeting_variants(self):
        for phrase in ("hay kurama", "hey Kurama!", "Kurama"):
            self.assertEqual(find_wake_word(phrase, "Kurama"), "")
        self.assertEqual(find_wake_word("Hay Kurama, remember buy milk", "Kurama"),
                         "remember buy milk")
        for phrase in ("hey groot", "hey kuramatic", "I saw Kurama yesterday"):
            self.assertIsNone(find_wake_word(phrase, "Kurama"))

    def test_fox_wake_phrase_keeps_kurama_name(self):
        for phrase in ("hay fox", "Hey Fox!", "hai fox", "hy fox", "hi fox", "I Fox"):
            self.assertEqual(find_wake_word(phrase, "Kurama"), "")
            self.assertEqual(find_wake_word(phrase + " what time is it", "Kurama"), "what time is it")
            self.assertTrue(is_stop_command(phrase + " stop", "Kurama"))
        for phrase in ("I saw a fox", "hey foxes", "hey foxtrot", "fox news", "hy", "hey"):
            self.assertIsNone(find_wake_word(phrase, "Kurama"))

    def test_clipped_greeting_wakes_and_speaks(self):
        heard = iter(["hy", "hypox"])
        said, captions = [], []
        session = Session(SimpleNamespace(), SimpleNamespace(say=said.append, stop=lambda: None),
                          lambda timeout=None: next(heard), lambda state: None, captions.append,
                          name="Kurama")
        session._wake_word_turn()
        self.assertFalse(session.active)
        session._wake_word_turn()
        self.assertTrue(session.active)
        session._conversation_turn()
        self.assertEqual(len(said), 1)
        self.assertIn(said[-1], WAKE_REPLIES[0])
        self.assertEqual(captions[-1], "Kurama: " + said[-1])
        self.assertIsNone(find_wake_word("Fox", "Groot"))

    def test_repeated_calls_escalate_without_repeating_and_real_request_resets(self):
        said, asked = [], []
        session = Session(SimpleNamespace(reply=lambda text: asked.append(text) or "Answered."),
                          SimpleNamespace(say=said.append, stop=lambda: None),
                          lambda timeout=None: "", lambda state: None, lambda text: None,
                          name="Kurama")
        session.start()
        with patch('groot.gui.time.monotonic', return_value=10):
            session._conversation_turn()
            for _ in range(8):
                session._handle("hay fox")
            self.assertIn(said[0], WAKE_REPLIES[0])
            self.assertIn(said[1], WAKE_REPLIES[1])
            self.assertTrue(all(line in WAKE_REPLIES[2] for line in said[2:]))
            self.assertTrue(all(a != b for a, b in zip(said, said[1:])))
            self.assertEqual(asked, [])
            session._handle("hey fox what time is it")
            self.assertEqual(asked, ["what time is it"])
            session._handle("hey fox")
            self.assertIn(said[-1], WAKE_REPLIES[0])

    def test_stop_wake_preserves_annoyance_but_time_cools_it(self):
        said = []
        session = Session(SimpleNamespace(), SimpleNamespace(say=said.append, stop=lambda: None),
                          lambda timeout=None: "", lambda state: None, lambda text: None,
                          name="Kurama")
        with patch('groot.gui.time.monotonic', return_value=10):
            session.start()
            session._conversation_turn()
            session._handle("stop")
            self.assertEqual(said[-1], "Okay.")
            session.start()
            session._conversation_turn()
            self.assertIn(said[-1], WAKE_REPLIES[1])
        with patch('groot.gui.time.monotonic', return_value=100):
            session._handle("hay fox")
            self.assertIn(said[-1], WAKE_REPLIES[0])

    def test_stop_with_new_name(self):
        for phrase in ("stop", "hay Kurama stop", "Hey Kurama, stop please", "you can stop Kurama"):
            self.assertTrue(is_stop_command(phrase, "Kurama"))
        self.assertFalse(is_stop_command("Kurama, don't stop", "Kurama"))

    def test_observed_microphone_transcripts(self):
        for phrase in ("hai khura", "hey crom", "hey Kura", "hey Chrome"):
            with self.subTest(phrase=phrase):
                self.assertEqual(find_wake_word(phrase, "Kurama"), "")
                self.assertEqual(find_wake_word(phrase + " remember buy milk", "Kurama"),
                                 "remember buy milk")
                self.assertTrue(is_stop_command(phrase + " stop", "Kurama"))

    def test_aliases_require_greeting_and_kurama_name(self):
        for phrase in ("Chrome", "open chrome", "Kura", "karma", "I saw khura yesterday",
                       "hey chromebook", "okay chrome", "a kura"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(find_wake_word(phrase, "Kurama"))
        for name in ("Groot", "Alice", ""):
            self.assertIsNone(find_wake_word("hey Kura", name))

    def test_wake_answer_and_return_to_corner(self):
        b = Buddy(name="Kurama", style="fox")
        b.set_state("idle")
        b.tick()
        heard = iter(["hey fox remember buy milk", "hay fox stop"])
        asked, said = [], []
        brain = SimpleNamespace(reply=lambda text: asked.append(text) or "Saved.")
        session = Session(brain, SimpleNamespace(say=said.append, stop=lambda: None),
                          lambda timeout=None: next(heard), b.set_state, b.set_text,
                          name="Kurama", on_stop=b.end_conversation)
        session._wake_word_turn()
        b.tick()
        self.assertTrue(session.active)
        self.assertFalse(b._fox_curled_up(0))
        session._conversation_turn()
        self.assertEqual(asked, ["remember buy milk"])
        self.assertEqual(session.name, "Kurama")
        session._conversation_turn()
        b.tick()
        self.assertFalse(session.active)
        self.assertEqual(b._fox_destination, "left")
        self.assertEqual(said[-1], "Okay.")


if __name__ == "__main__":
    unittest.main()
