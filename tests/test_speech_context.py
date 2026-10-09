import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groot.speech import correct_app_command, transcribe_groq

class SpeechTests(unittest.TestCase):
    def test_app_launch_correction_only(self):
        with patch('groot.speech.Path.is_dir', return_value=True):
            for text in ('open cloud', 'launch clawed', 'OpenClawed.', 'Hey Fox, open cloud please'):
                self.assertIn('Claude', correct_app_command(text))
            for text in ('what is a cloud', 'open cloud storage', 'do not open cloud', 'write open cloud in my note', 'open Claude'):
                self.assertEqual(correct_app_command(text), text)
        with patch('groot.speech.Path.is_dir', return_value=False):
            self.assertEqual(correct_app_command('open cloud'), 'open cloud')

    def test_audio_sent_without_hallucination_prone_prompt(self):
        audio = SimpleNamespace(get_wav_data=lambda **kwargs: b'RIFF-test-audio')
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test-key'}), patch('groot.speech.urllib.request.urlopen', return_value=io.BytesIO(b'{"text":"Open Claude."}')) as send:
            self.assertEqual(transcribe_groq(audio), 'Open Claude.')
        request = send.call_args.args[0]
        self.assertIn(b'RIFF-test-audio', request.data)
        self.assertNotIn(b'name="prompt"', request.data)
        self.assertIn(b'whisper-large-v3', request.data)
        self.assertEqual(send.call_args.kwargs['timeout'], 15)

if __name__ == '__main__': unittest.main()
