import tempfile
import unittest
from groot.memory import Memory


class NameMemoryTests(unittest.TestCase):
    def test_correction_replaces_conflicts_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            m = Memory(folder)
            m.remember("User's name is Sajeeb Paul")
            m.remember("User's name pronunciation is Sajib Paul with P-A-L")
            m.remember("User's friend is Sajeeb Paul")
            m.remember("User likes tea")
            m.remember("User's name is Sajib Pal")
            m = Memory(folder)
            self.assertEqual(m.answer_identity("What's my name?"), 'Your name is Sajib Pal.')
            self.assertEqual(m.answer_identity('Spell my name'), 'Your name is Sajib Pal, spelled S-A-J-I-B P-A-L.')
            self.assertEqual(len(m.facts), 3)
            self.assertIn("User's friend is Sajeeb Paul", [f['text'] for f in m.facts])
            self.assertFalse(any('pronunciation' in f['text'] for f in m.facts))
            self.assertIsNone(m.answer_identity('Send my name to Sajib Pal'))

    def test_unknown_name_is_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(Memory(folder).answer_identity('What is my name?'))


if __name__ == '__main__':
    unittest.main()
