import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import speech_recognition as sr
from groot.speech import transcribe_groq, UncertainTranscription
from groot.voice import Listener
from test_wake_audio import RecordedMicrophone, tone


class RecognitionRetryTests(unittest.TestCase):
    def transcribe(self, segments):
        audio = SimpleNamespace(get_wav_data=lambda **kwargs: b'RIFF-test')
        response = io.BytesIO(json.dumps({'segments': segments}).encode())
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test'}), patch(
                'groot.speech.urllib.request.urlopen', return_value=response):
            return transcribe_groq(audio)

    def segment(self, text, confidence=-0.2, silence=0.01):
        return dict(text=text, avg_logprob=confidence, no_speech_prob=silence,
                    compression_ratio=1)

    def test_uncertain_negation_does_not_become_send_command(self):
        with self.assertRaises(UncertainTranscription):
            self.transcribe([self.segment('Do not', -0.9), self.segment('send hi to Sajib Pal')])

    def test_noise_stays_silent(self):
        self.assertEqual(self.transcribe([self.segment('Thank you', silence=0.9)]), '')

    def test_complete_confident_sentence_preserved(self):
        self.assertEqual(self.transcribe([self.segment('Send hi'), self.segment('to Sajib Pal.')]),
                         'Send hi to Sajib Pal.')

    def test_retry_same_audio_without_service_cooldown(self):
        mic = RecordedMicrophone(tone(500, 0.5) + tone(0, 1.5))
        with patch.object(sr, 'Microphone', return_value=mic), patch.object(
                sr.Recognizer, 'adjust_for_ambient_noise'):
            listener = Listener(engine='groq')
        with patch('groot.voice.transcribe_groq', side_effect=UncertainTranscription) as first, patch.object(
                listener.recognizer, 'recognize_google', return_value='Do not send hi') as second:
            self.assertEqual(listener.listen(timeout=2), 'Do not send hi')
        self.assertIs(first.call_args.args[0], second.call_args.args[0])
        self.assertEqual(listener._groq_retry_after, 0)


if __name__ == '__main__':
    unittest.main()
