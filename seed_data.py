"""Synthetic examples; bootstrap is transactional and never resets existing data."""
import json
import database as db
from scoring import KEYS, score_card

EXAMPLES = [
    ('Образование', 'Бот для учебного центра', 'Менеджеры учебного центра вручную отвечают на повторяющиеся вопросы о курсах.'),
    ('Торговля', 'Учёт остатков магазина', 'Продавцы магазина записывают остатки товаров в разные таблицы и теряют изменения.'),
    ('Логистика', 'Контроль доставки', 'Диспетчер службы доставки вручную собирает статусы заказов у курьеров.'),
    ('Сервисы', 'Запись клиентов в мастерскую', 'Администратор мастерской путает время заявок из звонков и сообщений клиентов.'),
    ('Аналитика', 'Отчёт по продажам', 'Руководитель еженедельно вручную объединяет отчёты о продажах из трёх филиалов.'),
]


def seed() -> None:
    db.init_db()
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM meta WHERE key='seed' AND value='done'").fetchone():
            return
        if conn.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]:
            return
        conn.executemany('INSERT INTO profiles VALUES(?,?,?,?)', [
            (1, 'business', 'Демо-бизнес: Sana Lab', 'Все данные синтетические'),
            (2, 'business', 'Демо-бизнес: Qadam', 'Все данные синтетические'),
            *[(11 + i, 'team', name, details) for i, (name, details) in enumerate([
                ('Kuskon AI', 'Интересы: образование; навыки: Python, AI; технологии: Streamlit'),
                ('Data Nomads', 'Интересы: аналитика; навыки: SQL, Python; технологии: pandas'),
                ('Qadam Dev', 'Интересы: сервисы; навыки: JavaScript; технологии: React'),
                ('Steppe Bots', 'Интересы: автоматизация; навыки: API, Python; технологии: FastAPI'),
                ('Sana Makers', 'Интересы: UX; навыки: дизайн, HTML; технологии: Figma'),
            ])]])
        for i, (theme, title, context) in enumerate(EXAMPLES):
            stamp = db.now()
            owner = 1 if i % 2 == 0 else 2
            full = {'title': title, 'context': context,
                    'need': f'Уменьшить ручные операции в процессе «{title}».',
                    'data': f'Синтетический CSV: 50 примеров для задачи «{title}».',
                    'access': 'Демо-файл предоставит куратор на первой встрече; реальные персональные данные не нужны.',
                    'result': f'Работающий веб-прототип «{title}», исходники и инструкция.',
                    'success': 'Пройти 10 согласованных тестов без ошибок; результаты проверяет куратор.',
                    'constraints': 'Срок 2 недели после старта; без платных интеграций и реальных персональных данных.',
                    'users': f'Сотрудники компании, отвечающие за процесс «{title}».',
                    'contact': f'demo{i + 1}@example.com',
                    'interaction': 'Консультация с куратором по видеосвязи раз в неделю.',
                    'feedback': 'Куратор проверяет результат по чек-листу и отвечает в течение двух рабочих дней.'}
            for k in KEYS[[2, 5, 7, 9, 11][i]:]:
                full[k] = ''
            # Five descriptions with different completeness, as requested by the brief.
            raw = ' '.join(full[k] for k in KEYS if full[k])
            blank = {'title': title, **{k: '' for k in KEYS}}
            for k in KEYS[:i + 1]:
                blank[k] = full[k]
            conn.execute('INSERT INTO tasks(owner_id,original,theme,card,created,updated) VALUES(?,?,?,?,?,?)',
                         (owner, raw, theme, json.dumps(blank, ensure_ascii=False), stamp, stamp))
            confirmed = [k for k in KEYS if full[k]]
            score = score_card(full, confirmed)['total']
            cur = conn.execute('''INSERT INTO tasks(owner_id,original,theme,card,confirmed,score,published,created,updated)
                                  VALUES(?,?,?,?,?,?,1,?,?)''',
                               (owner, raw, theme, json.dumps(full, ensure_ascii=False), json.dumps(confirmed), score, stamp, stamp))
            task_id = cur.lastrowid
            conn.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',
                         (task_id, 1, json.dumps(full, ensure_ascii=False), json.dumps(confirmed), score, stamp))
            conn.execute('''INSERT INTO proposals(task_id,team_id,task_version,idea,plan,deadline,link,created)
                             VALUES(?,?,?,?,?,?,?,?)''',
                         (task_id, 11 + i, 1, f'Создадим прототип: {title}.',
                          'Уточним сценарий, соберём прототип, проверим по чек-листу.',
                          '14 дней после согласования', 'https://example.com/demo', stamp))
        conn.execute("INSERT INTO meta VALUES('seed','done')")


if __name__ == '__main__':
    seed()
    print('Демо-данные готовы; существующие данные не изменены.')
