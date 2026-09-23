"""Core checks run offline; no Streamlit or real model requests required."""
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import database as db
from ai_service import CARD_KEYS, interview, local_interview, validate_output
from scoring import FIELDS, KEYS, level, score_card
from seed_data import seed


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'TASKUP_DB': str(Path(self.tmp.name) / 'test.db'), 'OPENAI_API_KEY': ''})
        self.env.start()
        seed()
        self.full = next(t['card'] for t in db.tasks(published=True) if t['score'] == 100)
        self.low = min(db.tasks(published=True), key=lambda t: t['score'])

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_seed_minimum_and_idempotence(self):
        seed()
        self.assertEqual(len(db.tasks()), 10)
        self.assertEqual(len(db.tasks(published=True)), 5)
        self.assertEqual(len(db.rows("SELECT * FROM profiles WHERE role='team'")), 5)
        self.assertEqual(len(db.rows('SELECT * FROM proposals')), 5)
        self.assertEqual(len({len(t['original']) for t in db.tasks(published=True)}), 5)

    def test_weights_total_100(self):
        self.assertEqual(sum(f[2] for f in FIELDS), 100)
        self.assertEqual([g['Максимум'] for g in score_card({}, [])['groups']], [20, 20, 15, 15, 10, 10, 10])

    def test_boundaries(self):
        for score, name in [(0, 'Черновик'), (39, 'Черновик'), (40, 'Рабочая'), (69, 'Рабочая'),
                            (70, 'Готовая'), (89, 'Готовая'), (90, 'Приоритетная'), (100, 'Приоритетная')]:
            with self.subTest(score=score):
                self.assertEqual(level(score), name)
        for bad in (-1, 101):
            with self.assertRaises(ValueError):
                level(bad)

    def test_confirmation_required_for_points(self):
        self.assertEqual(score_card(self.full, [])['total'], 0)
        self.assertEqual(score_card(self.full, KEYS)['total'], 100)

    def test_placeholders_and_duplicates_score_zero(self):
        for value in ['не знаю', 'потом уточним', 'test', 'аааааааааааа', 'одинаковый длинный текст везде']:
            with self.subTest(value=value):
                self.assertEqual(score_card({k: value for k in KEYS}, KEYS)['total'], 0)

    def test_vague_success_is_partial(self):
        card = dict(self.full, success='Сделать удобно чтобы всё хорошо работало')
        self.assertEqual(score_card(card, KEYS)['total'], 90)

    def test_sorting_and_low_score_visible(self):
        scores = [t['score'] for t in db.tasks(published=True)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertLess(scores[-1], 40)
        pid = db.propose(self.low['id'], 11, 'Сделаем понятный прототип', 'Сначала согласуем рабочий сценарий', '2 недели', 'https://example.com')
        self.assertTrue(pid)

    def test_zero_score_publication_allowed(self):
        tid = db.create_draft(1, 'Хочу автоматизировать работу', 'Другое')
        db.save_card(tid, 1, 1, {'title': 'Нулевая задача'}, True, True)
        self.assertEqual(db.task(tid)['score'], 0)
        self.assertTrue(db.task(tid)['published'])

    def test_unconfirmed_publication_rejected(self):
        tid = db.create_draft(1, 'Хочу автоматизировать работу', 'Другое')
        with self.assertRaises(ValueError):
            db.save_card(tid, 1, 1, self.full, False, True)
        self.assertFalse(db.task(tid)['published'])

    def test_public_card_requires_title_and_confirmation_on_edit(self):
        t = self.low
        for card, confirmed in [(dict(self.full, title=''), True), (self.full, False)]:
            with self.assertRaises(ValueError):
                db.save_card(t['id'], t['owner_id'], t['version'], card, confirmed)
        self.assertEqual(db.task(t['id'])['version'], t['version'])

    def test_draft_cannot_receive_proposals(self):
        tid = db.create_draft(1, 'Хочу автоматизировать работу', 'Другое')
        with self.assertRaises(ValueError):
            db.propose(tid, 11, 'Достаточно длинная идея', 'Достаточно длинный план', '14 дней', 'https://example.com')

    def test_owner_guard(self):
        t = self.low
        with self.assertRaises(ValueError):
            db.save_card(t['id'], 2 if t['owner_id'] == 1 else 1, t['version'], self.full, True)

    def test_wrong_role_cannot_create_or_apply(self):
        with self.assertRaises(ValueError):
            db.create_draft(11, 'Хочу автоматизировать работу', 'Другое')
        with self.assertRaises(ValueError):
            db.propose(self.low['id'], 1, 'Достаточно длинная идея', 'Достаточно длинный план', '2 недели', 'https://example.com')

    def test_version_lock_and_history(self):
        t = self.low
        db.save_card(t['id'], t['owner_id'], t['version'], self.full, True)
        with self.assertRaises(ValueError):
            db.save_card(t['id'], t['owner_id'], t['version'], {'title': 'Устаревший текст'}, True)
        self.assertEqual(db.task(t['id'])['score'], 100)
        self.assertEqual(len(db.rows('SELECT * FROM revisions WHERE task_id=?', (t['id'],))), 2)

    def test_link_validation(self):
        for url in ['javascript:alert(1)', 'file:///tmp/test', 'https://', 'https://user:pass@example.com', 'https://exa mple.com']:
            with self.subTest(url=url):
                self.assertFalse(db.valid_url(url))
        self.assertTrue(db.valid_url('https://example.com/demo'))

    def test_no_automatic_or_exclusive_selection(self):
        t = self.low
        pids = [db.propose(t['id'], team, 'Предлагаем рабочий прототип', 'Согласуем детали и реализуем', '14 дней', 'https://example.com') for team in (11, 12)]
        for pid in pids:
            self.assertEqual(db.rows('SELECT status FROM proposals WHERE id=?', (pid,))[0]['status'], 'pending')
            db.decide(pid, t['owner_id'], 'selected')
        self.assertEqual(len(db.rows("SELECT * FROM proposals WHERE task_id=? AND status='selected'", (t['id'],))), 2)

    def test_business_can_reject_all(self):
        t = self.low
        props = db.rows('SELECT * FROM proposals WHERE task_id=?', (t['id'],))
        for p in props:
            db.decide(p['id'], t['owner_id'], 'rejected')
        self.assertEqual(len(db.rows("SELECT * FROM proposals WHERE task_id=? AND status='selected'", (t['id'],))), 0)
        self.assertTrue(all(p['status'] == 'rejected' for p in db.rows('SELECT * FROM proposals WHERE task_id=?', (t['id'],))))

    def test_cannot_decide_for_other_business(self):
        p = db.rows('SELECT * FROM proposals')[0]
        owner = db.task(p['task_id'])['owner_id']
        with self.assertRaises(ValueError):
            db.decide(p['id'], 2 if owner == 1 else 1, 'selected')

    def test_pending_team_cannot_submit_progress(self):
        p = db.rows('SELECT * FROM proposals')[0]
        with self.assertRaises(ValueError):
            db.submit_milestone(p['id'], p['team_id'], 'Прототип действительно готов', 'https://example.com')

    def test_complete_scenario_and_single_reward(self):
        original = 'Менеджеры учебного центра отвечают на одинаковые вопросы'
        result, _ = interview(original, 'Образование')
        tid = db.create_draft(1, original, 'Образование', result['card'], result['questions'])
        self.assertEqual(db.task(tid)['score'], 0)
        db.save_card(tid, 1, 1, self.full, True, True)
        self.assertEqual(db.task(tid)['score'], 100)
        pid = db.propose(tid, 11, 'Соберём бота для ответов', 'Согласуем FAQ, реализуем и проверим', '2 недели', 'https://example.com')
        db.decide(pid, 1, 'selected')
        db.submit_milestone(pid, 11, 'Готов прототип и проведены тесты', 'https://example.com/result')
        mid = db.rows('SELECT id FROM milestones WHERE proposal_id=?', (pid,))[0]['id']
        with self.assertRaises(ValueError):
            db.approve_milestone(mid, 2)
        self.assertTrue(db.approve_milestone(mid, 1))
        self.assertFalse(db.approve_milestone(mid, 1))
        self.assertEqual(db.rows('SELECT SUM(points) AS n FROM milestones')[0]['n'], 50)
        with self.assertRaises(ValueError):
            db.submit_milestone(pid, 11, 'Повторяем тот же результат', 'https://example.com')
        with self.assertRaises(ValueError):
            db.decide(pid, 1, 'rejected')
        self.assertEqual(db.task(tid)['score'], 100)

    def test_repeated_proposals_allowed_but_not_duplicate_reward(self):
        t = self.low
        pids = [db.propose(t['id'], 11, 'Соберём рабочий прототип', 'Согласуем этапы и реализуем', '14 дней', 'https://example.com') for _ in range(2)]
        self.assertNotEqual(*pids)
        for pid in pids:
            db.decide(pid, t['owner_id'], 'selected')
        db.submit_milestone(pids[0], 11, 'Готов прототип и проведены тесты', 'https://example.com')
        with self.assertRaises(ValueError):
            db.submit_milestone(pids[1], 11, 'Другой отклик на ту же задачу', 'https://example.com')

    def test_demo_questions_and_no_invented_facts(self):
        original = 'У нас кафе, хотим упростить приём заказов'
        out, note = interview(original, 'Сервисы')
        self.assertGreaterEqual(len(out['questions']), 3)
        self.assertEqual(set(out['card']), set(CARD_KEYS))
        self.assertTrue(all(not v or v in original for v in out['card'].values()))
        self.assertIn('демо', note)

    def test_real_mode_without_key_falls_back(self):
        original = 'Нужно автоматизировать учёт заказов'
        with self.assertLogs('ai_service', level='WARNING') as logs:
            out, note = interview(original, 'Торговля', True)
        self.assertIn('не задан', note)
        self.assertGreaterEqual(len(out['questions']), 3)
        self.assertNotIn(original, '\n'.join(logs.output))
        self.assertIn('missing_api_key', '\n'.join(logs.output))
        self.assertTrue(all(record.exc_info is None and record.stack_info is None for record in logs.records))

    def test_reject_malformed_ai(self):
        original = 'Нужно автоматизировать учёт заказов'
        good = local_interview(original, 'Торговля')
        self.assertEqual(validate_output(copy.deepcopy(good), original), good)
        for bad in [{}, [], dict(good, questions=[]), dict(good, questions=[good['questions'][0]] * 3),
                    dict(good, card={}), dict(good, card=dict(good['card'], need=123))]:
            with self.subTest(payload=bad):
                with self.assertRaises(ValueError):
                    validate_output(bad, original)

    def test_ungrounded_fields_are_cleared_without_mutating_input(self):
        original = 'Нужно автоматизировать учёт заказов. Доступны примеры заявок клиентов.'
        payload = local_interview(original, 'Торговля')
        payload['card']['data'] = 'Доступны примеры заявок клиентов.'
        payload['card']['need'] = 'Нужна интеллектуальная система управления продажами'
        payload['card']['title'] = 'Выдуманное название'
        before = copy.deepcopy(payload)
        result = validate_output(payload, original)
        self.assertEqual(result['card']['need'], '')
        self.assertEqual(result['card']['title'], '')
        self.assertEqual(result['card']['context'], original)
        self.assertEqual(result['card']['data'], payload['card']['data'])
        self.assertEqual(result['questions'], payload['questions'])
        self.assertEqual(payload, before)
        self.assertIsNot(result, payload)
        self.assertIsNot(result['card'], payload['card'])

    def test_title_is_quote_validated_before_length_cap(self):
        original = 'Точный исходный текст о работе магазина и заказах. ' * 5
        good = local_interview(original, 'Торговля')
        good['card']['title'] = original[:180]
        before = copy.deepcopy(good)
        result = validate_output(good, original)
        self.assertEqual(result['card']['title'], original[:140])
        self.assertEqual(good, before)
        bad = copy.deepcopy(good)
        bad['card']['title'] = original[:140] + ' НЕСУЩЕСТВУЮЩИЙ СУФФИКС'
        self.assertEqual(validate_output(bad, original)['card']['title'], '')

    def test_question_validation_remains_strict(self):
        original = 'Нужно автоматизировать учёт заказов'
        good = local_interview(original, 'Торговля')
        cases = {}
        duplicate_field = copy.deepcopy(good['questions'])
        duplicate_field[1]['field'] = duplicate_field[0]['field']
        cases['duplicate_field'] = duplicate_field
        duplicate_text = copy.deepcopy(good['questions'])
        duplicate_text[1]['question'] = duplicate_text[0]['question'].upper()
        cases['duplicate_question'] = duplicate_text
        invalid_field = copy.deepcopy(good['questions'])
        invalid_field[0]['field'] = 'nonexistent_field'
        cases['invalid_field'] = invalid_field
        bad_schema = copy.deepcopy(good['questions'])
        bad_schema[0]['extra'] = 'unexpected'
        cases['item_schema'] = bad_schema
        cases['too_few'] = copy.deepcopy(good['questions'][:2])
        cases['too_many'] = [
            {'field': key, 'question': f'Уточните сведения для поля {key}, пожалуйста.'}
            for key in KEYS[:6]
        ]
        for name, questions in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    validate_output(dict(good, questions=questions), original)

    def test_api_network_failure_is_labelled(self):
        original = 'Нужно автоматизировать учёт заказов'
        secret = 'unit-test-sensitive-secret-never-log'
        message = f'private-provider-body: {secret}; {original}'
        failures = [
            TimeoutError(message),
            HTTPError('https://example.invalid/' + secret, 429, message, None,
                      io.BytesIO(message.encode('utf-8'))),
        ]
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                with patch.dict(os.environ, {'OPENAI_API_KEY': secret}):
                    with patch('ai_service.urlopen', side_effect=failure):
                        with self.assertLogs('ai_service', level='WARNING') as logs:
                            result, note = interview(original, 'Торговля', True)
                self.assertIn('Ошибка API', note)
                self.assertEqual(result, local_interview(original, 'Торговля'))
                logged = '\n'.join(logs.output)
                self.assertRegex(logged, r'reason=[a-z_]+')
                self.assertIn(type(failure).__name__, logged)
                for sensitive in (secret, original, 'private-provider-body', 'Traceback'):
                    self.assertNotIn(sensitive, logged)
                self.assertTrue(all(record.exc_info is None and record.stack_info is None for record in logs.records))

    def test_api_success_with_mocked_provider(self):
        original = 'Нужно автоматизировать учёт заказов'
        out = local_interview(original, 'Торговля')
        raw = json.dumps({'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(out)}]}]}).encode()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-not-a-secret'}):
            with patch('ai_service.urlopen') as mock:
                mock.return_value.__enter__.return_value.read.return_value = raw
                result, note = interview(original, 'Торговля', True)
                self.assertEqual(result, out)
                self.assertIn('OpenAI API', note)

    def test_api_keeps_grounded_fields_when_one_field_is_paraphrased(self):
        need = 'Нужно автоматизировать учёт заказов.'
        data = 'Доступны примеры заявок клиентов.'
        result_quote = 'Команда передаст рабочий прототип.'
        original = f'{need} {data} {result_quote}'
        payload = local_interview(original, 'Торговля')
        payload['card'].update(need='Автоматизировать работу с заказами клиентов.',
                               data=data, result=result_quote)
        before = copy.deepcopy(payload)
        raw = json.dumps({
            'status': 'completed',
            'output': [{'content': [{'type': 'output_text', 'text': json.dumps(payload)}]}],
        }).encode()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-not-a-secret'}):
            with patch('ai_service.urlopen') as provider:
                provider.return_value.__enter__.return_value.read.return_value = raw
                result, note = interview(original, 'Торговля', True)
        self.assertIn('OpenAI API', note)
        self.assertNotIn('Ошибка API', note)
        self.assertEqual(result['card']['need'], '')
        for field in ('title', 'context', 'data', 'result'):
            self.assertEqual(result['card'][field], payload['card'][field])
        self.assertEqual(result['questions'], payload['questions'])
        self.assertEqual(payload, before)


if __name__ == '__main__':
    unittest.main()
