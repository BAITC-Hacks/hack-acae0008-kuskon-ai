"""Offline UI regressions; every test owns a disposable SQLite database."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import database as db
from i18n import tr
from scoring import KEYS, level


ROOT = Path(__file__).resolve().parents[1]


class UIFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='taskup-ui-')
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / 'test.db'
        environment = patch.dict(os.environ, {
            'TASKUP_DB': str(self.database), 'OPENAI_API_KEY': '',
        })
        environment.start()
        self.addCleanup(environment.stop)
        # The test must never issue a real AI request, even if secrets are loaded.
        provider = patch('ai_service.urlopen', side_effect=AssertionError('Unexpected network request'))
        provider.start()
        self.addCleanup(provider.stop)
        self.app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
        self.assert_healthy()

    def assert_healthy(self):
        self.assertFalse(self.app.exception, [item.message for item in self.app.exception])

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assert_healthy()

    def labelled(self, kind, translation):
        label = tr(self.app.session_state['lang'], translation)
        matches = [widget for widget in getattr(self.app, kind) if widget.label == label]
        self.assertEqual(len(matches), 1, f'{kind}: {label}')
        return matches[0]

    def submit(self, translation):
        self.labelled('button', translation).click().run()
        self.assert_healthy()

    def enter(self, role):
        if self.app.session_state['user_role'] is not None:
            self.click('change_role')
        self.click('enter_' + role)

    def test_trilingual_role_selection_and_navigation(self):
        for lang in ('kk', 'en', 'ru'):
            with self.subTest(lang=lang):
                if self.app.session_state['lang'] != lang:
                    self.click('landing_language_' + lang)
                self.assertEqual(self.app.session_state['lang'], lang)
                self.assertIsNone(self.app.session_state['user_role'])
                self.assertEqual(len(self.app.radio), 0)
                self.assertEqual(len(self.app.selectbox), 0)
                self.enter('business')
                self.assertEqual(self.app.session_state['active_page'], 'business')
                for page in ('constructor', 'catalog', 'about', 'business'):
                    self.click('nav_' + page)
                    self.assertEqual(self.app.session_state['active_page'], page)
                self.assertNotIn('nav_team', [button.key for button in self.app.button])
                self.enter('team')
                self.assertEqual(self.app.session_state['active_page'], 'catalog')
                for page in ('team', 'about', 'catalog'):
                    self.click('nav_' + page)
                    self.assertEqual(self.app.session_state['active_page'], page)
                self.assertNotIn('nav_constructor', [button.key for button in self.app.button])
                other = 'en' if lang != 'en' else 'kk'
                self.click('sidebar_language_' + other)
                self.assertEqual(self.app.session_state['lang'], other)
                self.assertEqual(self.app.session_state['user_role'], 'team')
                self.click('sidebar_language_' + lang)
                self.click('change_role')
                self.assertIsNone(self.app.session_state['user_role'])
                self.assertEqual(self.app.session_state['lang'], lang)

    def test_marketplace_filters_survive_detail_and_back(self):
        self.enter('team')
        task = min(db.tasks(published=True), key=lambda item: item['score'])
        title = task['card']['title']
        self.app.text_input(key='search').set_value(title)
        self.app.selectbox(key='theme_filter').select(task['theme'])
        self.app.selectbox(key='readiness_filter').select(level(task['score'])).run()
        self.assert_healthy()
        open_keys = [button.key for button in self.app.button if str(button.key).startswith('open_task_')]
        self.assertEqual(open_keys, [f'open_task_{task["id"]}'])
        self.click(open_keys[0])
        self.assertEqual(self.app.session_state['selected_catalog_task'], task['id'])
        self.assertEqual(self.labelled('button', 'send_proposal').disabled, False)
        self.click('back_catalog')
        self.assertEqual(self.app.text_input(key='search').value, title)
        self.assertEqual(self.app.selectbox(key='theme_filter').value, task['theme'])
        self.assertEqual(self.app.selectbox(key='readiness_filter').value, level(task['score']))
        self.app.text_input(key='search').set_value('nonexistent-task-qa-937').run()
        self.click('reset_filters')
        self.assertEqual(self.app.text_input(key='search').value, '')
        self.assertEqual(len([button for button in self.app.button if str(button.key).startswith('open_task_')]),
                         len(db.tasks(published=True)))

    def test_local_interview_publication_proposal_selection_and_milestone(self):
        self.click('landing_language_en')
        full = next(task['card'] for task in db.tasks(published=True) if task['score'] == 100)
        self.enter('business')
        owner = self.app.session_state['business_profile']
        self.click('nav_constructor')
        original = 'Our school managers answer the same enrollment questions every day.'
        self.labelled('text_area', 'describe_need').set_value(original)
        self.submit('analyze_need')
        task_id = self.app.session_state['editor_task']
        task = db.task(task_id)
        self.assertEqual(task['owner_id'], owner)
        self.assertEqual(task['score'], 0)
        self.assertFalse(task['published'])
        self.assertTrue(all(not value or value in original for value in task['card'].values()))
        self.assertGreaterEqual(len(task['questions']), 3)

        for question in task['questions']:
            key = question['field']
            self.app.text_area(key=f'answer_{task_id}_{task["version"]}_{key}').set_value(full[key])
        self.submit('answers_to_card')
        task = db.task(task_id)
        self.assertEqual(task['version'], 2)
        self.assertEqual(task['score'], 0)
        self.labelled('text_input', 'title').set_value('UI regression: school enrollment assistant')
        for key in KEYS:
            self.app.text_area(key=f'field_{task_id}_{task["version"]}_{key}').set_value(full[key])
        self.submit('preview_score')
        self.assertEqual(db.task(task_id)['version'], 2)
        self.assertEqual(db.task(task_id)['score'], 0)

        self.labelled('checkbox', 'publish_catalog').check()
        self.submit('save_card')
        self.assertTrue(self.app.error)
        self.assertFalse(db.task(task_id)['published'])
        self.app.checkbox(key=f'confirm_{task_id}_2').check()
        self.submit('save_card')
        published = db.task(task_id)
        self.assertTrue(published['published'])
        self.assertEqual(published['score'], 100)
        self.assertEqual(published['version'], 3)

        self.enter('team')
        team = self.app.session_state['team_profile']
        self.click(f'open_task_{task_id}')
        self.labelled('text_area', 'idea').set_value('Build an assistant for school enrollment questions.')
        self.labelled('text_area', 'plan').set_value('Collect the FAQ, build a prototype, and validate answers.')
        self.labelled('text_input', 'deadline').set_value('2 weeks')
        self.labelled('text_input', 'prototype_link').set_value('https://example.com/prototype')
        self.submit('send_proposal')
        proposal = db.rows('SELECT * FROM proposals WHERE task_id=?', (task_id,))[0]
        self.assertEqual(proposal['team_id'], team)
        self.assertEqual(proposal['status'], 'pending')
        self.assertEqual(proposal['task_version'], published['version'])

        self.enter('business')
        self.app.selectbox(key='dashboard_task').select(task_id).run()
        self.click(f'select_{proposal["id"]}')
        self.assertEqual(db.rows('SELECT status FROM proposals WHERE id=?', (proposal['id'],))[0]['status'], 'selected')
        self.enter('team')
        self.click('nav_team')
        self.labelled('text_area', 'actual_ready').set_value('The working prototype passes all acceptance checks.')
        self.labelled('text_input', 'result_link').set_value('https://example.com/result')
        self.submit('send_stage')
        milestone = db.rows('SELECT * FROM milestones WHERE proposal_id=?', (proposal['id'],))[0]
        self.assertIsNone(milestone['approved_at'])
        self.assertEqual(milestone['points'], 0)

        self.enter('business')
        self.app.selectbox(key='dashboard_task').select(task_id).run()
        self.click(f'approve_{milestone["id"]}')
        approved = db.rows('SELECT * FROM milestones WHERE id=?', (milestone['id'],))[0]
        self.assertEqual(approved['approved_by'], owner)
        self.assertEqual(approved['points'], 50)
        self.assertEqual(db.task(task_id)['score'], 100)
        self.enter('team')
        self.click('nav_team')
        self.assertTrue(any(metric.label == tr('en', 'points_metric') and metric.value == '50'
                            for metric in self.app.metric))
        self.assertFalse(any(button.label == tr('en', 'send_stage') for button in self.app.button))


if __name__ == '__main__':
    unittest.main()
