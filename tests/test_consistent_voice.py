import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.voice import Speaker

class ConsistentVoiceTests(unittest.TestCase):
    def speaker(self):
        s=Speaker(engine='edge',edge_voice='en-US-AndrewNeural',edge_pitch='-28Hz',dramatic=False)
        s._can_use_edge=Mock(return_value=True)
        s._say_groot=Mock()
        s._run=Mock()
        return s

    def test_retry_same_voice_then_success(self):
        s=self.speaker()
        s._say_edge=Mock(side_effect=[RuntimeError('no audio'),None])
        s.say('Opened Claude.')
        self.assertEqual(s._say_edge.call_count,2)
        s._say_groot.assert_not_called()
        s._run.assert_not_called()
        self.assertEqual(s.edge_pitch,'-28Hz')

    def test_failure_never_switches_voice_and_next_reply_retries(self):
        s=self.speaker()
        s._say_edge=Mock(side_effect=RuntimeError('no audio'))
        self.assertIs(s.say('Opened Claude.'),False)
        s._say_groot.assert_not_called()
        s._run.assert_not_called()
        s._say_edge=Mock()
        s.say('Still here.')
        s._say_edge.assert_called_once_with('Still here.')

    def test_missing_engine_does_not_use_mac_voice(self):
        s=self.speaker()
        s._can_use_edge.return_value=False
        self.assertIs(s.say('Hello.'),False)
        s._say_groot.assert_not_called()
        s._run.assert_not_called()

if __name__=='__main__': unittest.main()
