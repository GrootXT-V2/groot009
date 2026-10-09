import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from groot.brain import GeminiBrain, APIError
from groot.__main__ import choose_brain_kind


class GeminiTests(unittest.TestCase):
    def test_chat_and_tool_round_trip(self):
        skills = SimpleNamespace(tools=[{'name': 'get_time', 'description': 'Read time',
                                        'input_schema': {'type': 'object', 'properties': {}}}],
                                 run=Mock(return_value='12:00'))
        post = Mock(side_effect=[
            {'candidates': [{'content': {'parts': [{'functionCall': {'name': 'get_time', 'args': {}}, 'thoughtSignature': 'sig'}]}}]},
            {'candidates': [{'content': {'parts': [{'text': 'It is noon.'}]}}]}])
        brain = GeminiBrain('test', 'gemini-2.5-flash-lite', skills, post=post)
        self.assertEqual(brain.reply('What time is it?'), 'It is noon.')
        skills.run.assert_called_once_with('get_time', {})
        url, payload, headers = post.call_args.args
        self.assertEqual(url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent')
        self.assertEqual(payload['generationConfig']['thinkingConfig']['thinkingBudget'], 0)
        self.assertEqual(payload['contents'][-1]['parts'][0]['functionResponse']['response']['result'], '12:00')
        self.assertEqual(payload['contents'][-2]['parts'][0]['thoughtSignature'], 'sig')
        self.assertEqual(headers['x-goog-api-key'], 'test')

    def test_quota_error_does_not_change_provider_or_retry(self):
        post = Mock(side_effect=APIError(429, 'Quota exceeded'))
        brain = GeminiBrain('test', 'gemini-2.5-flash-lite', SimpleNamespace(tools=[]), post=post)
        with self.assertRaises(APIError):
            brain.reply('Hello')
        self.assertEqual(brain.history, [])
        post.assert_called_once()

    def test_missing_key_has_clear_error(self):
        with patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(SystemExit, 'GEMINI_API_KEY'):
            choose_brain_kind(SimpleNamespace(brain='gemini'))


if __name__ == '__main__':
    unittest.main()
