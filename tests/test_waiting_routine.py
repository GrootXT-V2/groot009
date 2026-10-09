import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groot.buddy import Buddy
from groot.gui import Session, is_stop_command

class WaitingTests(unittest.TestCase):
    def test_stroll_sit_timeout_and_corner_sleep(self):
        b = Buddy(style='fox')
        said, stopped = [], []
        def stop():
            stopped.append(True)
            b.end_conversation()
        s = Session(SimpleNamespace(), SimpleNamespace(say=said.append, stop=lambda: None),
                    lambda timeout=None: '', b.set_state, b.set_text, name='Kurama', on_stop=stop)
        with patch('groot.gui.time.monotonic', return_value=10):
            s.start()
            s._conversation_turn()
            s._conversation_turn()
            b.tick()
            x = b.x
            for _ in range(20): b.tick()
            self.assertNotEqual(b.x, x)
            self.assertTrue(b.pose['walking'])
            s.speech_started()
            b.tick()
            x = b.x
            for _ in range(20): b.tick()
            self.assertEqual(b.x, x)
            self.assertFalse(b.pose.get('walking', False))
        with patch('groot.gui.time.monotonic', return_value=129):
            s._conversation_turn()
            self.assertTrue(s.active)
        count = len(said)
        with patch('groot.gui.time.monotonic', return_value=130):
            s._conversation_turn()
        self.assertFalse(s.active)
        self.assertEqual(len(said), count)
        self.assertEqual(stopped, [True])
        for _ in range(4000): b.tick()
        self.assertTrue(b._fox_curled_up(0))

    def test_sleep_commands_and_negations(self):
        for phrase in ('go to sleep', 'you can stop now', 'you can sleep now',
                       'please go back to sleep', 'hey fox you can sleep now',
                       'you may rest now please', 'take a nap'):
            self.assertTrue(is_stop_command(phrase, 'Kurama'), phrase)
        for phrase in ("don't go to sleep", "you cannot sleep now", "why do foxes sleep", "don't stop"):
            self.assertFalse(is_stop_command(phrase, 'Kurama'), phrase)

    def test_unconfirmed_noise_does_not_refresh_timeout(self):
        s = Session(SimpleNamespace(), SimpleNamespace(say=lambda text: None, stop=lambda: None),
                    lambda timeout=None: '', lambda state: None, lambda text: None)
        with patch('groot.gui.time.monotonic', return_value=10): s.start()
        s._greet = False
        with patch('groot.gui.time.monotonic', return_value=129): s.speech_started()
        with patch('groot.gui.time.monotonic', return_value=130): s._conversation_turn()
        self.assertFalse(s.active)

if __name__ == '__main__': unittest.main()
