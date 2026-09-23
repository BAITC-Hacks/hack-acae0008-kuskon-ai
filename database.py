"""SQLite persistence and guarded transitions. Demo identity is NOT authentication."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from scoring import KEYS, THEMES, score_card


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


@contextmanager
def connect():
    path = Path(os.getenv('TASKUP_DB') or Path(__file__).parent / 'data' / 'taskup.db')
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS profiles(
            id INTEGER PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL, details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES profiles(id),
            original TEXT NOT NULL, theme TEXT NOT NULL, card TEXT NOT NULL,
            confirmed TEXT NOT NULL DEFAULT '[]', score INTEGER NOT NULL DEFAULT 0 CHECK(score BETWEEN 0 AND 100),
            published INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
            questions TEXT NOT NULL DEFAULT '[]', created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions(
            task_id INTEGER NOT NULL REFERENCES tasks(id), version INTEGER NOT NULL,
            card TEXT NOT NULL, confirmed TEXT NOT NULL, score INTEGER NOT NULL, created TEXT NOT NULL,
            PRIMARY KEY(task_id, version));
        CREATE TABLE IF NOT EXISTS proposals(
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
            team_id INTEGER NOT NULL REFERENCES profiles(id), task_version INTEGER NOT NULL,
            idea TEXT NOT NULL, plan TEXT NOT NULL, deadline TEXT NOT NULL, link TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','selected','rejected')),
            created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS milestones(
            id INTEGER PRIMARY KEY, proposal_id INTEGER NOT NULL REFERENCES proposals(id),
            task_id INTEGER NOT NULL REFERENCES tasks(id), team_id INTEGER NOT NULL REFERENCES profiles(id),
            description TEXT NOT NULL, link TEXT NOT NULL, approved_by INTEGER REFERENCES profiles(id),
            approved_at TEXT, points INTEGER NOT NULL DEFAULT 0,
            UNIQUE(task_id, team_id));
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')


def rows(sql: str, args=()) -> list:
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


def decode(row) -> dict:
    item = dict(row)
    for key in ('card', 'confirmed', 'questions'):
        item[key] = json.loads(item[key])
    return item


def task(task_id: int) -> dict:
    result = rows('SELECT * FROM tasks WHERE id=?', (task_id,))
    if not result:
        raise ValueError('Задача не найдена.')
    return decode(result[0])


def tasks(owner_id=None, published=False) -> list:
    sql, args = 'SELECT * FROM tasks WHERE 1=1', []
    if owner_id is not None:
        sql += ' AND owner_id=?'
        args.append(owner_id)
    if published:
        sql += ' AND published=1'
    return [decode(r) for r in rows(sql + ' ORDER BY score DESC, created ASC, id ASC', args)]


def require_role(db, profile_id: int, role: str) -> None:
    row = db.execute('SELECT role FROM profiles WHERE id=?', (profile_id,)).fetchone()
    if not row or row['role'] != role:
        raise ValueError('Действие недоступно для этого профиля.')


def owned(db, task_id: int, owner: int):
    row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not row or row['owner_id'] != owner:
        raise ValueError('Изменять задачу может только её владелец.')
    return row


def create_draft(owner: int, original: str, theme: str, card=None, questions=None) -> int:
    if not 10 <= len(original.strip()) <= 12000 or theme not in THEMES:
        raise ValueError('Опишите потребность: от 10 до 12 000 символов; выберите тему.')
    card = card or {'title': '', **{k: '' for k in KEYS}}
    stamp = now()
    with connect() as db:
        require_role(db, owner, 'business')
        cur = db.execute('INSERT INTO tasks(owner_id,original,theme,card,questions,created,updated) VALUES(?,?,?,?,?,?,?)',
                         (owner, original.strip(), theme, json.dumps(card, ensure_ascii=False),
                          json.dumps(questions or [], ensure_ascii=False), stamp, stamp))
        return cur.lastrowid


def save_card(task_id: int, owner: int, version: int, card: dict, confirmed: bool, publish=False) -> int:
    clean = {k: str(card.get(k, '')).strip() for k in ['title'] + KEYS}
    if len(clean['title']) > 140 or any(len(v) > 6000 for v in clean.values()):
        raise ValueError('Название: до 140 символов; каждое поле: до 6000.')
    fields = [k for k in KEYS if confirmed and clean[k]]
    rating = score_card(clean, fields)['total']
    encoded, confirms = json.dumps(clean, ensure_ascii=False), json.dumps(fields)
    stamp = now()
    with connect() as db:
        old = owned(db, task_id, owner)
        is_public = publish or old['published']
        if is_public and (not confirmed or len(clean['title']) < 3):
            raise ValueError('Публичной карточке нужны название и ручное подтверждение. Минимального рейтинга нет.')
        # Optimistic lock prevents stale tabs from overwriting a newer revision.
        result = db.execute('''UPDATE tasks SET card=?,confirmed=?,score=?,published=?,version=version+1,updated=?
                               WHERE id=? AND version=?''',
                            (encoded, confirms, rating, int(is_public), stamp, task_id, version))
        if result.rowcount != 1:
            raise ValueError('Карточка уже изменена. Обновите страницу и повторите редактирование.')
        db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)', (task_id, version + 1, encoded, confirms, rating, stamp))
    return rating


def valid_url(value: str) -> bool:
    try:
        url = urlparse(value.strip())
        return url.scheme in ('http', 'https') and bool(url.hostname) and not url.username and not any(c.isspace() for c in value)
    except ValueError:
        return False


def propose(task_id: int, team_id: int, idea: str, plan: str, deadline: str, link: str) -> int:
    if not (10 <= len(idea.strip()) <= 6000 and 10 <= len(plan.strip()) <= 6000
            and 2 <= len(deadline.strip()) <= 300 and len(link) <= 2000 and valid_url(link)):
        raise ValueError('Заполните идею и план (от 10 символов), срок и корректную http/https-ссылку.')
    with connect() as db:
        require_role(db, team_id, 'team')
        row = db.execute('SELECT * FROM tasks WHERE id=? AND published=1', (task_id,)).fetchone()
        if not row:
            raise ValueError('Отклики принимаются только на опубликованные задачи.')
        return db.execute('''INSERT INTO proposals(task_id,team_id,task_version,idea,plan,deadline,link,created)
                             VALUES(?,?,?,?,?,?,?,?)''',
                          (task_id, team_id, row['version'], idea.strip(), plan.strip(), deadline.strip(), link.strip(), now())).lastrowid


def decide(proposal_id: int, owner: int, status: str) -> None:
    if status not in ('selected', 'rejected'):
        raise ValueError('Выберите или отклоните команду.')
    with connect() as db:
        prop = db.execute('SELECT * FROM proposals WHERE id=?', (proposal_id,)).fetchone()
        if not prop:
            raise ValueError('Отклик не найден.')
        owned(db, prop['task_id'], owner)
        approved = db.execute('SELECT 1 FROM milestones WHERE proposal_id=? AND approved_at IS NOT NULL', (proposal_id,)).fetchone()
        if approved and status == 'rejected':
            raise ValueError('Нельзя отклонить отклик после подтверждения результата.')
        db.execute('UPDATE proposals SET status=? WHERE id=?', (status, proposal_id))


def submit_milestone(proposal_id: int, team: int, description: str, link: str) -> None:
    if not 10 <= len(description.strip()) <= 6000 or not valid_url(link) or len(link) > 2000:
        raise ValueError('Опишите результат (10–6000 символов) и укажите http/https-ссылку.')
    with connect() as db:
        p = db.execute("SELECT * FROM proposals WHERE id=? AND team_id=? AND status='selected'", (proposal_id, team)).fetchone()
        if not p:
            raise ValueError('Отправить результат может только выбранная команда.')
        try:
            db.execute('INSERT INTO milestones(proposal_id,task_id,team_id,description,link) VALUES(?,?,?,?,?)',
                       (proposal_id, p['task_id'], team, description.strip(), link.strip()))
        except sqlite3.IntegrityError as exc:
            raise ValueError('Этап этой команды по задаче уже отправлен; повторные баллы запрещены.') from exc


def approve_milestone(milestone_id: int, owner: int) -> bool:
    with connect() as db:
        m = db.execute('''SELECT m.*, p.status FROM milestones m JOIN proposals p ON p.id=m.proposal_id
                          WHERE m.id=?''', (milestone_id,)).fetchone()
        if not m:
            raise ValueError('Этап не найден.')
        owned(db, m['task_id'], owner)
        if m['status'] != 'selected':
            raise ValueError('Команда больше не выбрана.')
        # Separate from readiness; a proposed MVP reward, not a requirement's weight.
        return db.execute('UPDATE milestones SET approved_by=?,approved_at=?,points=50 WHERE id=? AND approved_at IS NULL',
                          (owner, now(), milestone_id)).rowcount == 1
