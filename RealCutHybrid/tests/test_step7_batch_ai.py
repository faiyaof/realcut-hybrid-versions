import ast
import json
import re
import sys
import types
import unittest
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / 'vendor' / 'experimental' /
          'scripts' / '步骤7-生成字幕.py')


def load_batch_helpers():
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    wanted_functions = {
        '_digit_tokens',
        'validate_review_candidate',
        'parse_ai_transcript_batch',
        'ai_review_segment_transcript',
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if 'BANNED_WORDS' in names:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)
    namespace = {
        'json': json,
        're': re,
        'split_text_only': lambda text: [f'LOCAL:{text}'],
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SCRIPT), 'exec'), namespace)
    return namespace


class Step7BatchAiTests(unittest.TestCase):
    def setUp(self):
        self.helpers = load_batch_helpers()
        self.previous_llm = sys.modules.get('_llm')

    def tearDown(self):
        if self.previous_llm is None:
            sys.modules.pop('_llm', None)
        else:
            sys.modules['_llm'] = self.previous_llm

    def test_batch_request_handles_all_sentences_in_one_llm_call(self):
        calls = []
        response = {
            'items': [
                {
                    'index': 1,
                    'text': '这件桑蚕丝只要200元',
                    'segments': ['这件桑蚕丝', '只要200元'],
                    'keywords': ['桑蚕丝', '200元'],
                },
                {
                    'index': 2,
                    'text': '今天上车看面料',
                    'segments': ['今天上车', '看面料'],
                    'keywords': ['上车', '面料'],
                },
            ]
        }

        fake_llm = types.ModuleType('_llm')

        def llm_text_with_provider(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return json.dumps(response, ensure_ascii=False), 'fake-provider'

        fake_llm.llm_text_with_provider = llm_text_with_provider
        sys.modules['_llm'] = fake_llm

        sentences = [
            {'text': '这件桑蚕丝只要200元'},
            {'text': '今天上车看面料'},
        ]
        result = self.helpers['ai_review_segment_transcript'](
            sentences, {'preserve': ['桑蚕丝']},
        )

        self.assertEqual(1, len(calls))
        items, provider = result
        self.assertEqual('fake-provider', provider)
        self.assertEqual(['这件桑蚕丝', '只要200元'], items[0]['segments'])
        self.assertEqual(['上车', '面料'], items[1]['keywords'])
        self.assertFalse(items[0]['used_local_split'])

    def test_invalid_digits_fall_back_locally_and_discard_keywords(self):
        content = json.dumps({
            'items': [{
                'index': 1,
                'text': '这件只要300元',
                'segments': ['这件只要', '300元'],
                'keywords': ['300元'],
            }]
        }, ensure_ascii=False)

        items = self.helpers['parse_ai_transcript_batch'](
            content, [{'text': '这件只要200元'}], {},
        )

        self.assertEqual('这件只要200元', items[0]['text'])
        self.assertEqual(['LOCAL:这件只要200元'], items[0]['segments'])
        self.assertEqual([], items[0]['keywords'])
        self.assertTrue(items[0]['used_local_split'])

    def test_protected_word_loss_falls_back_to_original_text(self):
        content = json.dumps({
            'items': [{
                'index': 1,
                'text': '这件面料很舒服',
                'segments': ['这件面料', '很舒服'],
                'keywords': ['面料'],
            }]
        }, ensure_ascii=False)

        items = self.helpers['parse_ai_transcript_batch'](
            content,
            [{'text': '这件桑蚕丝面料很舒服'}],
            {'preserve': ['桑蚕丝']},
        )

        self.assertEqual('这件桑蚕丝面料很舒服', items[0]['text'])
        self.assertTrue(items[0]['used_local_split'])
        self.assertEqual([], items[0]['keywords'])

    def test_partial_shuffled_response_maps_by_index_and_fills_missing_locally(self):
        content = json.dumps({
            'items': [
                {
                    'index': 2,
                    'text': '中间句面料很好',
                    'segments': ['中间句', '面料很好'],
                    'keywords': ['面料'],
                },
                {
                    'index': 1,
                    'text': '开头句只要200元',
                    'segments': ['开头句', '只要200元'],
                    'keywords': ['200元'],
                },
            ]
        }, ensure_ascii=False)

        items = self.helpers['parse_ai_transcript_batch'](
            content,
            [
                {'text': '开头句只要200元'},
                {'text': '中间句面料很好'},
                {'text': '结尾句没有返回'},
            ],
            {},
        )

        self.assertEqual(['开头句', '只要200元'], items[0]['segments'])
        self.assertEqual(['中间句', '面料很好'], items[1]['segments'])
        self.assertEqual(['LOCAL:结尾句没有返回'], items[2]['segments'])
        self.assertTrue(items[2]['used_local_split'])

    def test_string_item_is_accepted_without_invalidating_other_items(self):
        content = json.dumps({
            'sentences': [
                '开头句原文',
                {
                    'index': 2,
                    'text': '中间句原文',
                    'segments': ['中间句', '原文'],
                    'keywords': [],
                },
            ]
        }, ensure_ascii=False)

        items = self.helpers['parse_ai_transcript_batch'](
            content,
            [{'text': '开头句原文'}, {'text': '中间句原文'}],
            {},
        )

        self.assertEqual('开头句原文', items[0]['text'])
        self.assertEqual(['LOCAL:开头句原文'], items[0]['segments'])
        self.assertTrue(items[0]['used_local_split'])
        self.assertEqual(['中间句', '原文'], items[1]['segments'])

    def test_unparseable_json_still_returns_none(self):
        result = self.helpers['parse_ai_transcript_batch'](
            'not-json', [{'text': '第一句'}], {},
        )

        self.assertIsNone(result)

    def test_full_audio_path_has_no_per_sentence_ai_segmentation_call(self):
        tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == 'generate_subs_from_full_audio'
        )
        calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertIn('ai_review_segment_transcript', calls)
        self.assertNotIn('ai_review_transcript', calls)
        self.assertNotIn('ai_segment_text', calls)


if __name__ == '__main__':
    unittest.main()
