import sys,time,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.buddy import Buddy
from groot.gui import Session
class EmotionTests(unittest.TestCase):
 def test_emotion_expires_and_sleep_clears_it(self):
  b=Buddy(style='fox'); b.set_state('listening'); b.tick()
  self.assertEqual(b._fox_emotion(time.monotonic()),'curious')
  b.set_emotion('annoyed'); b.tick()
  self.assertEqual(b._fox_emotion(time.monotonic()),'annoyed')
  self.assertEqual(b._fox_emotion(b.emotion_until+1),'curious')
  marks=[]; c=SimpleNamespace(text=lambda *args,**kwargs:marks.append(args))
  b._draw_fox_emotion(c,time.monotonic())
  self.assertEqual(marks[0][2],'!')
  b.set_state('idle'); b.tick()
  self.assertEqual(b._fox_emotion(time.monotonic()),'calm')
 def test_call_annoyance_and_concern(self):
  moods=[]
  s=Session(SimpleNamespace(reply=lambda text:'Understood.'),SimpleNamespace(say=lambda text:None,stop=lambda:None),lambda timeout=None:'',lambda state:None,lambda text:None,name='Kurama',on_emotion=moods.append)
  s.start(); s._conversation_turn(); s._handle('hey fox'); s._handle('hey fox')
  self.assertEqual(moods[-1],'annoyed')
  s._handle('I am worried'); self.assertEqual(moods[-1],'concerned')
  s._handle('thanks'); self.assertEqual(moods[-1],'happy')
if __name__=='__main__': unittest.main()
