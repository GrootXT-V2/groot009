import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.skills import Skills
from groot.integrations import Slack,SLACK_TOOLS
class SlackBodyTests(unittest.TestCase):
 def test_exact_message_is_confirmed_before_sending(self):
  for request in ('send hi to Sajib Pal','Say hi to Sajib Pal.','send hi to Sajib Pal on Slack'):
   with self.subTest(request=request),tempfile.TemporaryDirectory() as d:
    skills=Skills(Path(d),mac_apps=False); posted=[]
    def api(token,method,params=None,post=False):
     self.assertEqual(method,'chat.postMessage'); posted.append(params); return {'ok':True}
    slack=Slack('fake',skills.ask_confirmation,call=api)
    slack._find_conversation=lambda name: 'DM' if name=='Sajib Pal' else self.fail(name)
    skills.integrations.append((slack,SLACK_TOOLS))
    self.assertEqual(skills.prepare_slack_greeting(request),'Send "hi" to Sajib Pal on Slack? Say yes or no.')
    self.assertEqual(posted,[])
    skills.handle_confirmation('yes')
    self.assertEqual(posted,[{'channel':'DM','text':'hi'}])
 def test_negations_and_quoted_messages_not_rewritten(self):
  with tempfile.TemporaryDirectory() as d:
   skills=Skills(Path(d),mac_apps=False)
   for text in ('do not send hi to Sajib Pal','send "Say hi to Sajib Pal" to Sam','tell me how to send hi to Sajib Pal'):
    self.assertIsNone(skills.prepare_slack_greeting(text))
if __name__=='__main__': unittest.main()
