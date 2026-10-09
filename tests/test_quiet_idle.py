import sys,struct,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import speech_recognition as sr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.voice import has_voice_activity
from groot.gui import Session
class QuietTests(unittest.TestCase):
 def test_silence_room_noise_and_click_rejected(self):
  for samples in ([0]*16000,[40,-40]*8000,[3000]*320+[0]*15680):
   audio=sr.AudioData(struct.pack('<'+'h'*len(samples),*samples),16000,2)
   self.assertFalse(has_voice_activity(audio,47))
  audio=sr.AudioData(struct.pack('<hh',500,-500)*4000,16000,2)
  self.assertTrue(has_voice_activity(audio,47))
 def test_silent_wait_never_speaks_or_asks_brain(self):
  said=Mock(); brain=SimpleNamespace(reply=Mock()); stopped=Mock()
  s=Session(brain,SimpleNamespace(say=said,stop=lambda:None),lambda timeout=None:' ',lambda state:None,lambda text:None,name='Kurama',on_stop=stopped)
  with patch('groot.gui.time.monotonic',return_value=0): s.start()
  s._greet=False
  for now in (5,30,60,119,120):
   with patch('groot.gui.time.monotonic',return_value=now): s._conversation_turn()
  said.assert_not_called(); brain.reply.assert_not_called(); stopped.assert_called_once()
  self.assertFalse(s.active)
if __name__=='__main__': unittest.main()
