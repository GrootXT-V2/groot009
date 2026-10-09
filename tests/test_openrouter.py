import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from groot.brain import OpenRouterBrain, APIError

class OpenRouterTests(unittest.TestCase):
    def test_selected_model_endpoint_and_reply(self):
        calls=[]
        def post(url,payload,headers):
            calls.append((url,payload,headers))
            return {'choices':[{'message':{'content':'Ready.'}}]}
        brain=OpenRouterBrain('test-key','nvidia/nemotron-3.5-lightning',SimpleNamespace(tools=[]),post=post)
        self.assertEqual(brain.reply('Hello'),'Ready.')
        self.assertEqual(calls[0][0],'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(calls[0][1]['model'],'nvidia/nemotron-3.5-lightning')
        self.assertEqual(calls[0][2]['Authorization'],'Bearer test-key')

    def test_error_does_not_switch_models_or_keep_failed_turn(self):
        def post(*args): raise APIError(429,'Rate limited')
        brain=OpenRouterBrain('test-key','nvidia/nemotron-3.5-lightning',SimpleNamespace(tools=[]),post=post)
        with self.assertRaises(APIError): brain.reply('Hello')
        self.assertEqual(brain.history,[])
        self.assertEqual(brain.model,'nvidia/nemotron-3.5-lightning')

if __name__=='__main__': unittest.main()
