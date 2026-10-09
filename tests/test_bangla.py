import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from groot.voice import Speaker, clean_for_speech
from groot.speech import transcribe_groq
from groot.gui import find_wake_word


class BanglaTests(unittest.TestCase):
    def test_voice_selection_preserves_english_voice(self):
        speaker = Speaker.__new__(Speaker)
        speaker.edge_voice = 'en-US-AndrewNeural'
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(speaker._voice_for_text('আমি শুনছি।'), 'bn-BD-PradeepNeural')
            self.assertEqual(speaker._voice_for_text('Hello!'), speaker.edge_voice)
        self.assertEqual(clean_for_speech('আমি শুনছি।'), 'আমি শুনছি।')

    def test_auto_language_does_not_force_english(self):
        audio = SimpleNamespace(get_wav_data=lambda **kwargs: b'RIFF')
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test', 'GROOT_STT_LANGUAGE': 'auto'}), patch(
                'groot.speech.urllib.request.urlopen', return_value=io.BytesIO(b'{"text":"hello"}')) as send:
            transcribe_groq(audio)
        self.assertNotIn(b'name="language"', send.call_args.args[0].data)

    def test_bangla_wake_preserves_command(self):
        self.assertEqual(find_wake_word('হেই কুরামা এখন কয়টা বাজে', 'Kurama'), 'এখন কয়টা বাজে')
        self.assertEqual(find_wake_word('ফক্স', 'Kurama'), '')


if __name__ == '__main__':
    unittest.main()
