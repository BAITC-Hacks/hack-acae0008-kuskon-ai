"""Offline display-translation contracts: caches, fallback, and protected facts."""
import copy
import importlib
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, patch

import translation_service as service


def provider_response(translations=None, *, status='completed', content=None):
    if content is None:
        content = [{'type': 'output_text', 'text': json.dumps({'translations': translations})}]
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        'status': status, 'output': [{'type': 'message', 'content': content}],
    }).encode('utf-8')
    return response


def translated_response(request, **kwargs):
    body = json.loads(request.data)
    payload = json.loads(body['input'])
    return provider_response([
        {'id': item['id'], 'text': f'[{payload["target_language"]}] ' + item['text']}
        for item in payload['texts']
    ])


class TranslationServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='taskup-translation-')
        self.addCleanup(temporary.cleanup)
        self.cache_dir = Path(temporary.name) / 'translations'
        environment = patch.dict(os.environ, {
            'TASKUP_TRANSLATION_CACHE_DIR': str(self.cache_dir),
            'OPENAI_API_KEY': 'unit-test-not-a-secret',
            'OPENAI_MODEL': 'unit-test-model',
        })
        environment.start()
        self.addCleanup(environment.stop)
        service._MEMORY.clear()
        service._FAILURES.clear()

    def test_fields_are_display_only_and_results_are_immutable(self):
        self.assertEqual(service.TRANSLATABLE_FIELDS, (
            'title', 'context', 'need', 'data', 'access', 'result', 'success',
            'constraints', 'users', 'interaction', 'feedback',
        ))
        self.assertNotIn('contact', service.TRANSLATABLE_FIELDS)
        result = service.TextTranslation('Original')
        self.assertFalse(result.translated)
        self.assertFalse(result.unavailable)
        with self.assertRaises(FrozenInstanceError):
            result.text = 'Changed'

    def test_batch_request_schema_and_duplicate_memory_cache(self):
        first, second = 'Помощник при зачислении учеников', 'Рабочий прототип для менеджеров'
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            results = service.translate_texts([first, second, first], 'en')
            self.assertEqual(set(results), {first, second})
            self.assertTrue(all(value.translated for value in results.values()))
            self.assertTrue(all(not value.unavailable for value in results.values()))
            self.assertEqual(provider.call_count, 1)
            request = provider.call_args.args[0]
            body = json.loads(request.data)
            payload = json.loads(body['input'])
            self.assertEqual(payload['target_language'], 'en')
            self.assertEqual(len(payload['texts']), 2)
            self.assertEqual({item['id'] for item in payload['texts']}, {'0', '1'})
            self.assertFalse(body['store'])
            self.assertEqual(body['text']['format']['type'], 'json_schema')
            self.assertTrue(body['text']['format']['strict'])
            self.assertFalse(body['text']['format']['schema']['additionalProperties'])
            self.assertEqual(service.translate_texts([second, first], 'en'), results)
            self.assertEqual(provider.call_count, 1)

    def test_locale_and_source_changes_require_new_translation(self):
        original = 'Помощник по вопросам зачисления'
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            english = service.translate_texts([original], 'en')[original]
            kazakh = service.translate_texts([original], 'kk')[original]
            russian = service.translate_texts(['School enrollment assistant'], 'ru')
            service.translate_texts([original + ' в школу'], 'en')
            self.assertEqual(provider.call_count, 4)
            self.assertNotEqual(english.text, kazakh.text)
            self.assertTrue(russian['School enrollment assistant'].translated)

    def test_irrelevant_glossary_terms_do_not_invalidate_cache(self):
        original = 'TaskUp помогает командам найти задачу'
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            first = service.translate_texts([original], 'en', ['TaskUp', 'UnrelatedCompany'])
            second = service.translate_texts([original], 'en', ['AnotherCompany', 'TaskUp'])
            self.assertEqual(first, second)
            self.assertEqual(provider.call_count, 1)

    def test_cache_survives_module_restart_without_provider(self):
        original = 'Команда передаёт работающий прототип'
        with patch.object(service, 'urlopen', side_effect=translated_response):
            expected = service.translate_texts([original], 'en')[original].text
        self.assertTrue(list(self.cache_dir.glob('*.json')))
        importlib.reload(service)
        with patch.object(service, 'urlopen', side_effect=AssertionError('Cache miss after restart')) as provider:
            result = service.translate_texts([original], 'en')[original]
        provider.assert_not_called()
        self.assertTrue(result.translated)
        self.assertEqual(result.text, expected)

    def test_missing_key_falls_back_and_can_retry_after_configuration(self):
        original = 'Задача для студенческой команды'
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            with patch.object(service, 'urlopen') as provider:
                result = service.translate_texts([original], 'kk')[original]
            provider.assert_not_called()
            self.assertEqual(result.text, original)
            self.assertFalse(result.translated)
            self.assertTrue(result.unavailable)
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            self.assertTrue(service.translate_texts([original], 'kk')[original].translated)
        self.assertEqual(provider.call_count, 1)

    def test_failure_cooldown_then_retry(self):
        original = 'Согласовать ожидаемый результат работы'
        with patch.object(service.time, 'monotonic', return_value=100):
            with patch.object(service, 'urlopen', side_effect=TimeoutError('offline')) as provider:
                failed = service.translate_texts([original], 'en')[original]
                self.assertEqual(provider.call_count, 1)
        self.assertTrue(failed.unavailable)
        self.assertEqual(failed.text, original)
        with patch.object(service.time, 'monotonic', return_value=101):
            with patch.object(service, 'urlopen') as provider:
                self.assertEqual(service.translate_texts([original], 'en')[original], failed)
            provider.assert_not_called()
        with patch.object(service.time, 'monotonic', return_value=161):
            with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
                self.assertTrue(service.translate_texts([original], 'en')[original].translated)
            self.assertEqual(provider.call_count, 1)

    def test_incomplete_refusal_or_malformed_output_falls_back(self):
        cases = {
            'timeout': TimeoutError('offline'),
            'incomplete': provider_response([], status='incomplete'),
            'refusal': provider_response(content=[{'type': 'refusal', 'refusal': 'Unable'}]),
            'invalid_json': provider_response(content=[{'type': 'output_text', 'text': '{bad'}]),
            'missing_id': provider_response([]),
            'wrong_id': provider_response([{'id': '9', 'text': 'Translated'}]),
            'duplicate_id': provider_response([{'id': '0', 'text': 'One'}, {'id': '0', 'text': 'Two'}]),
            'unexpected_key': provider_response([{'id': '0', 'text': 'Translated', 'extra': 'unsafe'}]),
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                original = 'Описание задачи: ' + name
                options = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
                with patch.object(service, 'urlopen', **options):
                    result = service.translate_texts([original], 'en')[original]
                self.assertEqual(result.text, original)
                self.assertFalse(result.translated)
                self.assertTrue(result.unavailable)

    def test_names_contacts_links_technology_and_numbers_are_exact(self):
        protected = ['TaskUp', 'Kuskon AI']
        facts = ['TaskUp', 'Kuskon AI', 'Python', 'Streamlit', 'SQLite', 'OpenAI',
                 'https://example.com/demo?q=42', 'owner@example.com', '@taskup_team',
                 '+7 (777) 123-45-67', '2026-09-23', '50%', '14', '100 000']
        original = ('TaskUp от Kuskon AI использует Python, Streamlit, SQLite и OpenAI. '
                    'Материалы https://example.com/demo?q=42; контакты owner@example.com, '
                    '@taskup_team, +7 (777) 123-45-67. Срок 2026-09-23: 50% за 14 дней, 100 000 тенге.')
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            result = service.translate_texts([original], 'en', protected)[original]
        self.assertTrue(result.translated)
        for fact in facts:
            with self.subTest(fact=fact):
                self.assertEqual(result.text.count(fact), original.count(fact))
        request_text = json.loads(json.loads(provider.call_args.args[0].data)['input'])['texts'][0]['text']
        for sensitive in facts[:11]:
            self.assertNotIn(sensitive, request_text)
        self.assertNotIn('__TU_', result.text)

    def test_missing_duplicate_and_unknown_placeholders_are_rejected(self):
        for mode in ('missing', 'duplicate', 'unknown'):
            with self.subTest(mode=mode):
                original = f'TaskUp проверяет рабочий прототип ({mode}).'
                masked, tokens = service._mask_text(original, ['TaskUp'])
                token = next(iter(tokens))
                changed = (masked.replace(token, '') if mode == 'missing' else
                           masked + token if mode == 'duplicate' else
                           masked + '__TU_ffffffffffff_999__')
                with patch.object(service, 'urlopen', return_value=provider_response([{'id': '0', 'text': changed}])):
                    result = service.translate_texts([original], 'en', ['TaskUp'])[original]
                self.assertEqual(result.text, original)
                self.assertTrue(result.unavailable)
                self.assertFalse(result.translated)

    def test_lowercase_technologies_and_profile_names_keep_source_spelling(self):
        original = 'taskup использует python, javascript и docker для прототипа.'
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            result = service.translate_texts([original], 'en', ['TaskUp'])[original]
            service.translate_texts([original], 'en', ['TASKUP'])
        self.assertTrue(result.translated)
        self.assertEqual(provider.call_count, 1)
        request_text = json.loads(json.loads(provider.call_args.args[0].data)['input'])['texts'][0]['text']
        for term in ('taskup', 'python', 'javascript', 'docker'):
            self.assertIn(term, result.text)
            self.assertNotIn(term, request_text)

    def test_outage_stops_remaining_batches_and_cools_down_all_items(self):
        sources = [f'Рабочий прототип задачи номер {index}' for index in range(25)]
        with patch.object(service.time, 'monotonic', return_value=100):
            with patch.object(service, 'urlopen', side_effect=TimeoutError('offline')) as provider:
                results = service.translate_texts(sources, 'en')
                self.assertEqual(provider.call_count, 1)
                self.assertTrue(all(item.unavailable for item in results.values()))
                self.assertTrue(all(results[source].text == source for source in sources))
                service.translate_texts(sources, 'en')
                self.assertEqual(provider.call_count, 1)

    def test_invented_quantity_contact_or_lost_line_break_falls_back(self):
        for mode in ('quantity', 'contact', 'linebreak'):
            with self.subTest(mode=mode):
                original = f'Описание задачи ({mode}).\nОжидаемый результат для команды.'
                masked, _ = service._mask_text(original)
                changed = (masked + ' 500' if mode == 'quantity' else
                           masked + ' invented@example.com' if mode == 'contact' else
                           masked.replace('\n', ' '))
                with patch.object(service, 'urlopen', return_value=provider_response([{'id': '0', 'text': changed}])):
                    result = service.translate_texts([original], 'en')[original]
                self.assertEqual(result.text, original)
                self.assertTrue(result.unavailable)
                self.assertFalse(result.translated)

    def test_same_language_exact_echo_is_unlabelled_and_cached(self):
        original = 'Build a school enrollment assistant using Python.'

        def echo(request, **kwargs):
            texts = json.loads(json.loads(request.data)['input'])['texts']
            return provider_response(texts)

        with patch.object(service, 'urlopen', side_effect=echo) as provider:
            result = service.translate_texts([original], 'en')[original]
            cached = service.translate_texts([original], 'en')[original]
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result.text, original)
        self.assertEqual(result, cached)
        self.assertFalse(result.translated)
        self.assertFalse(result.unavailable)

    def test_corrupted_persistent_cache_is_validated_and_refetched(self):
        original = 'Прототип показывает статус зачисления'
        with patch.object(service, 'urlopen', side_effect=translated_response):
            expected = service.translate_texts([original], 'en')[original]
        cache_file, = self.cache_dir.glob('*.json')
        record = json.loads(cache_file.read_text(encoding='utf-8'))
        record['output'] += ' 987654321'
        cache_file.write_text(json.dumps(record), encoding='utf-8')
        service._MEMORY.clear()
        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            result = service.translate_texts([original], 'en')[original]
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result, expected)

    def test_concurrent_duplicate_requests_share_one_provider_call(self):
        original = 'Команды проверяют рабочий сценарий'
        starting = threading.Barrier(4)

        def translate(_):
            starting.wait(timeout=5)
            return service.translate_texts([original], 'en')[original]

        with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(translate, range(4)))
        self.assertEqual(provider.call_count, 1)
        self.assertTrue(all(result.translated for result in results))
        self.assertTrue(all(result == results[0] for result in results))

    def test_disk_write_failure_preserves_translation_and_memory_cache(self):
        original = 'Команда получает доступ к материалам'
        with patch.object(service.os, 'replace', side_effect=OSError('Cache is read-only')):
            with patch.object(service, 'urlopen', side_effect=translated_response) as provider:
                result = service.translate_texts([original], 'en')[original]
                cached = service.translate_texts([original], 'en')[original]
        self.assertEqual(provider.call_count, 1)
        self.assertTrue(result.translated)
        self.assertFalse(result.unavailable)
        self.assertEqual(result, cached)
        self.assertFalse(list(self.cache_dir.glob('*.json')))

    def test_caller_objects_are_unchanged(self):
        card = {'title': 'Задача для студенческой команды', 'result': 'Передать готовый прототип'}
        terms = ['TaskUp', 'Python']
        original_card, original_terms = copy.deepcopy(card), list(terms)
        with patch.object(service, 'urlopen', side_effect=translated_response):
            service.translate_texts((text for text in card.values()), 'en', terms)
        self.assertEqual(card, original_card)
        self.assertEqual(terms, original_terms)


if __name__ == '__main__':
    unittest.main()
