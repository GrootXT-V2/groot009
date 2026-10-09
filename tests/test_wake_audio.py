import io
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import speech_recognition as sr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groot.voice import Listener


class RecordedMicrophone(sr.AudioSource):
    SAMPLE_RATE = 16000
    SAMPLE_WIDTH = 2
    CHUNK = 160

    def __init__(self, samples):
        self.samples = samples
        self.stream = None

    def __enter__(self):
        self.stream = io.BytesIO(self.samples)
        # AudioSource streams read sample counts, not byte counts.
        raw = self.stream
        self.stream = type('Stream', (), {'read': lambda _, count: raw.read(count * 2)})()
        return self

    def __exit__(self, *args):
        self.stream = None


def tone(amplitude, seconds):
    return struct.pack('<hh', amplitude, -amplitude) * int(8000 * seconds)


class WakeAudioTests(unittest.TestCase):
    def test_quiet_word_after_loud_greeting_is_kept(self):
        # A loud greeting, a pause, then a much quieter second word.
        quiet_word = tone(150, 0.35)
        samples = tone(0, 0.2) + tone(3000, 0.5) + tone(0, 0.4) + quiet_word + tone(0, 1.5)
        mic = RecordedMicrophone(samples)

        def calibrate(recognizer, source, duration):
            recognizer.energy_threshold = 200

        with patch.object(sr, 'Microphone', return_value=mic), patch.object(sr.Recognizer, 'adjust_for_ambient_noise', calibrate):
            listener = Listener()
        detected = []
        listener.on_speech_start = lambda: detected.append(True)
        with patch.object(listener.recognizer, 'recognize_google', return_value='hey fox') as recognize:
            self.assertEqual(listener.listen(timeout=2), 'hey fox')
        recorded = recognize.call_args.args[0].frame_data
        self.assertIn(quiet_word, recorded)
        self.assertEqual(detected, [True])
        self.assertEqual(listener.recognizer.energy_threshold, 200)


if __name__ == '__main__':
    unittest.main()
