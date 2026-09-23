"""Display translation never changes original forms, contacts, scores, or SQLite."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import database as db
import translation_service as service
from i18n import tr
from scoring import KEYS


ROOT = Path(__file__).resolve().parents[1]


def fake_translations(texts, target_lang, protected_terms=()):
    return {text: service.TextTranslation(f'UI-{target_lang}: {text}', translated=True)
            for text in texts}


class TranslationUIFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='taskup-translated-ui-')
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {
            'TASKUP_DB': str(Path(temporary.name) / 'test.db'),
            'TASKUP_TRANSLATION_CACHE_DIR': str(Path(temporary.name) / 'translations'),
            'OPENAI_API_KEY': 'unit-test-not-a-secret',
        })
        environment.start()
        self.addCleanup(environment.stop)
        service._MEMORY.clear()
        service._FAILURES.clear()
        provider = patch('ai_service.urlopen', side_effect=AssertionError('Unexpected real AI request'))
        provider.start()
        self.addCleanup(provider.stop)
        translation_provider = patch('translation_service.urlopen', side_effect=TimeoutError('Offline UI test'))
        self.provider = translation_provider.start()
        self.addCleanup(translation_provider.stop)
        self.fake = patch('translation_service.translate_texts', side_effect=fake_translations)
        self.translator = self.fake.start()
        self.addCleanup(self.fake.stop)
        self.app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
        self.assert_healthy()
        self.before = self.snapshot()
        self.task = next(task for task in db.tasks(published=True) if task['score'] == 100)

    @staticmethod
    def snapshot():
        return {table: db.rows(f'SELECT * FROM {table} ORDER BY rowid')
                for table in ('profiles', 'tasks', 'revisions', 'proposals', 'milestones', 'meta')}

    def assert_healthy(self):
        self.assertFalse(self.app.exception, [item.message for item in self.app.exception])

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assert_healthy()

    def rendered(self):
        return '\n'.join(str(item.value) for kind in ('markdown', 'text', 'subheader', 'caption')
                         for item in getattr(self.app, kind))

    def test_translation_and_original_controls_leave_editor_and_database_unchanged(self):
        card, task_id = self.task['card'], self.task['id']
        self.click('landing_language_en')
        self.click('enter_team')
        self.assertIn('UI-en: ' + card['title'], self.rendered())
        self.assertIn('UI-en: ' + card['result'], self.rendered())
        self.assertTrue(any(item.value == tr('en', 'auto_translation') for item in self.app.caption))
        self.assertTrue(any(item.label == tr('en', 'show_original') for item in self.app.expander))
        self.assertTrue(any(item.value == card['title'] for item in self.app.text))

        self.app.text_input(key='search').set_value('UI-en: ' + card['title']).run()
        self.assert_healthy()
        self.assertEqual(
            [button.key for button in self.app.button if str(button.key).startswith('open_task_')],
            [f'open_task_{task_id}'],
        )

        self.click(f'open_task_{task_id}')
        for key in service.TRANSLATABLE_FIELDS:
            if card[key]:
                self.assertIn('UI-en: ' + card[key], self.rendered())
        self.assertIn(card['contact'], self.rendered())
        self.assertNotIn('UI-en: ' + card['contact'], self.rendered())
        for call in self.translator.call_args_list:
            self.assertNotIn(card['contact'], call.args[0])
        self.click('sidebar_language_kk')
        self.assertIn('UI-kk: ' + card['title'], self.rendered())
        self.assertTrue(any(item.value == tr('kk', 'auto_translation') for item in self.app.caption))

        calls_before_original = self.translator.call_count
        self.app.checkbox(key='show_original_content').check().run()
        self.assert_healthy()
        self.assertEqual(self.translator.call_count, calls_before_original)
        self.assertIn(card['title'], self.rendered())
        self.assertNotIn('UI-kk:', self.rendered())
        self.app.checkbox(key='show_original_content').uncheck().run()
        self.assertIn('UI-kk: ' + card['title'], self.rendered())

        self.click('change_role')
        self.click('enter_business')
        self.app.selectbox(key='business_profile').select(self.task['owner_id']).run()
        self.click('nav_constructor')
        self.app.selectbox(key='editor_task').select(task_id).run()
        self.assert_healthy()
        title_inputs = [item for item in self.app.text_input if item.label == tr('kk', 'title')]
        self.assertEqual(len(title_inputs), 1)
        self.assertEqual(title_inputs[0].value, card['title'])
        for key in KEYS:
            self.assertEqual(self.app.text_area(key=f'field_{task_id}_{self.task["version"]}_{key}').value, card[key])
        self.assertIn('UI-kk: ' + card['title'], self.rendered())
        self.assertEqual(self.snapshot(), self.before)
        self.provider.assert_not_called()

    def test_provider_failure_shows_original_without_changing_database(self):
        self.fake.stop()
        self.click('landing_language_en')
        self.click('enter_team')
        self.assertGreater(self.provider.call_count, 0)
        self.assertIn(self.task['card']['title'], self.rendered())
        self.assertTrue(any(item.value == tr('en', 'translation_unavailable') for item in self.app.caption))
        self.assertFalse(any(item.value == tr('en', 'auto_translation') for item in self.app.caption))
        self.click(f'open_task_{self.task["id"]}')
        self.assertIn(self.task['card']['result'], self.rendered())
        self.assertIn(self.task['card']['context'], self.rendered())
        self.assertEqual(self.snapshot(), self.before)


if __name__ == '__main__':
    unittest.main()
