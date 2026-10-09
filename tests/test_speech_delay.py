import io,json,os,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.voice import Speaker
from groot.speech import transcribe_groq
from groot.gui import wake_command

class DelayTests(unittest.TestCase):
 def test_repeated_wake_is_not_a_question(self):
  self.assertEqual(wake_command('Hey Fox hey Fox', 'Kurama'),'')
  self.assertEqual(wake_command('Hey Fox hey Fox open Claude','Kurama'),'open claude')
 def test_silence_and_low_confidence_are_ignored(self):
  audio=SimpleNamespace(get_wav_data=lambda **kwargs:b'audio')
  for segments,expected in [([],''),([{'text':'Hey Fox','no_speech_prob':0.9}],''),([{'text':'hello','avg_logprob':-2}],''),([{'text':'open Claude','no_speech_prob':0.01,'avg_logprob':-0.1}],'open Claude')]:
   data={'text':'hallucination','segments':segments}
   with patch.dict(os.environ,{'GROQ_API_KEY':'test'}),patch('groot.speech.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
    self.assertEqual(transcribe_groq(audio),expected)
 def test_audio_cached_with_same_voice_and_short_timeouts(self):
  calls=[]
  class Speech:
   def __init__(self,text,voice,**kwargs): calls.append((text,voice,kwargs))
   async def save(self,path): Path(path).write_bytes(b'audio')
  s=Speaker(dramatic=False,edge_pitch='-28Hz'); played=[]; s._run=played.append
  with patch('edge_tts.Communicate',Speech), patch('groot.voice.shutil.which', return_value=None):
   s._say_edge('What is it?'); s._say_edge('What is it?')
  self.assertEqual(len(calls),1); self.assertEqual(len(played),2)
  self.assertEqual(calls[0][2]['receive_timeout'],5)
  self.assertEqual(calls[0][2]['pitch'],'-28Hz')
if __name__=='__main__': unittest.main()
