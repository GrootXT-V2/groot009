import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.voice import Speaker
class StreamingTests(unittest.TestCase):
 def test_playback_begins_before_generation_finishes_and_cache_reused(self):
  events=[]
  class Speech:
   def __init__(self,*args,**kwargs): events.append('request')
   async def stream(self):
    yield {'type':'audio','data':b'first'}
    selfcheck=events.index('play')
    events.append('finish'); yield {'type':'audio','data':b'last'}
  class Player:
   def __init__(self,*args,**kwargs):
    events.append('play'); self.stdin=Mock()
   def wait(self): return 0
   def poll(self): return 0
  s=Speaker(dramatic=False); s._run=Mock()
  with tempfile.TemporaryDirectory() as d,patch('groot.voice.tempfile.gettempdir',return_value=d),patch('edge_tts.Communicate',Speech),patch('groot.voice.subprocess.Popen',Player):
   s._stream_edge('Hello.')
   self.assertLess(events.index('play'),events.index('finish'))
   s._stream_edge('Hello.')
   self.assertEqual(events.count('request'),1)
   s._run.assert_called_once()
if __name__=='__main__': unittest.main()
