import sys,unittest,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.voice import Speaker,Listener
from groot.gui import Session
class SelfSpeechTests(unittest.TestCase):
 def test_speaking_state_clears_on_failure(self):
  s=Speaker(); seen=[]
  def fail(text):
   seen.append(s.speaking.is_set()); raise RuntimeError()
  s._say_impl=fail
  with self.assertRaises(RuntimeError): s.say('hello')
  self.assertEqual(seen,[True]); self.assertFalse(s.speaking.is_set()); self.assertEqual(s.audio_epoch,2)
 def test_own_voice_is_not_recorded(self):
  l=Listener.__new__(Listener)
  event=threading.Event(); event.set()
  l.speaker=SimpleNamespace(audio_epoch=1,speaking=event,last_speech_end=0)
  with patch('groot.voice.time.sleep'): self.assertEqual(l.listen(),'')
 def test_noise_onset_does_not_extend_conversation(self):
  s=Session(SimpleNamespace(),SimpleNamespace(stop=lambda:None),lambda timeout=None:'',lambda state:None,lambda text:None)
  with patch('groot.gui.time.monotonic',return_value=0): s.start()
  s._greet=False
  with patch('groot.gui.time.monotonic',return_value=119): s.speech_started()
  with patch('groot.gui.time.monotonic',return_value=120): s._conversation_turn()
  self.assertFalse(s.active)
if __name__=='__main__': unittest.main()
