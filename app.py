"""TaskUp by Kuskon AI. Run: python -m streamlit run app.py"""
import json
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
import database as db
from ai_service import PROMPT, SCHEMA, interview, local_interview
from scoring import FIELDS, KEYS, THEMES, LEVELS, level, score_card
from seed_data import seed

load_dotenv(Path(__file__).with_name('.env'))
st.set_page_config(page_title='TaskUp · Kuskon AI', page_icon='↗', layout='wide')
try:
    seed()
except (OSError, db.sqlite3.Error):
    st.error('Не удалось открыть базу. Проверьте права на папку data и значение TASKUP_DB.')
    st.stop()

st.markdown('''<style>
.block-container {max-width:1280px;padding-top:2rem;padding-bottom:3rem}
h1,h2,h3 {letter-spacing:-.03em}
[data-testid="stSidebar"] {border-right:1px solid #29314a}
.hero {padding:24px 28px;border:1px solid #393360;border-radius:18px;
background:linear-gradient(120deg,#171f36,#2b2046);margin-bottom:22px;color:#f5f5ff}
.hero p {color:#c5c9dc;margin:8px 0 0}
.hero small {color:#b8a2ff;letter-spacing:.14em;font-weight:700}
[data-testid="stMetricValue"] {font-size:2rem}
</style>''', unsafe_allow_html=True)

STATUS = {'pending': 'На рассмотрении', 'selected': 'Команда выбрана', 'rejected': 'Отклонено'}
profiles = db.rows('SELECT * FROM profiles ORDER BY id')
by_id = {p['id']: p for p in profiles}
with st.sidebar:
    st.title('TaskUp ↗')
    st.caption('KUSKON AI · AI SANA')
    role = st.radio('Демо-роль', ['Гость', 'Бизнес', 'Команда'], key='role')
    person = None
    if role != 'Гость':
        options = [p['id'] for p in profiles if p['role'] == ('business' if role == 'Бизнес' else 'team')]
        person = st.selectbox('Профиль', options, format_func=lambda i: by_id[i]['name'], key=f'profile_{role}')
    st.caption('Демонстрационные профили — не авторизация. Используйте только тестовые данные.')
    page = st.radio('Раздел', ['Каталог', 'Конструктор', 'Кабинет бизнеса', 'Кабинет команды', 'О проекте'], key='page')
    st.divider()
    st.caption('Полнее задача → выше рейтинг. Команды выбирают сами. Решение — за бизнесом.')

st.markdown('''<div class="hero"><small>БИЗНЕС × СТУДЕНЧЕСКИЕ КОМАНДЫ</small>
<h1>Понятная задача. Сильный старт.</h1>
<p>Превратите потребность в карточку, улучшите её готовность и найдите команду через открытые отклики.</p></div>''', unsafe_allow_html=True)
if 'flash' in st.session_state:
    st.info(st.session_state.pop('flash'))


def finish(message: str) -> None:
    st.session_state['flash'] = message
    st.rerun()


def rating(card: dict, confirmed, preview=False) -> None:
    r = score_card(card, confirmed)
    st.metric('Предварительная оценка' if preview else 'Подтверждённый рейтинг', f"{r['total']}/100")
    st.progress(r['total'] / 100)
    st.write(r['level'])
    st.dataframe(r['groups'], hide_index=True, use_container_width=True)
    if r['missing']:
        st.markdown('**Следующий шаг**')
        item = r['missing'][0]
        st.info(f"+{item['gain']} · {item['label']}. {item['question']} {item['reason']}.")
        st.markdown('**Все недостающие сведения**')
        st.dataframe([{'Поле': m['label'], 'Можно получить': m['gain'], 'Что уточнить': m['question'],
                       'Причина': m['reason']} for m in r['missing']], hide_index=True, use_container_width=True)
    else:
        st.success('Все пункты рубрики заполнены и подтверждены.')
    st.caption('Оценка полноты по правилам MVP, не гарантия достоверности или реализуемости. Детали — в «О проекте».')


def details(t: dict) -> None:
    for k, label, *_ in FIELDS:
        st.markdown(f'**{label}**')
        st.text(t['card'].get(k) or 'Нужно уточнить')
    st.caption(f"Версия {t['version']} · задача #{t['id']}")


def catalogue() -> None:
    all_tasks = db.tasks(published=True)
    c1, c2, c3 = st.columns(3)
    c1.metric('Открытых задач', len(all_tasks))
    c2.metric('Готовых и приоритетных', sum(t['score'] >= 70 for t in all_tasks))
    c3.metric('Команд в демо', sum(p['role'] == 'team' for p in profiles))
    st.subheader('Открытый каталог')
    a, b, c = st.columns([2, 1, 1])
    query = a.text_input('Поиск', placeholder='Название, потребность, результат', key='search')
    theme = b.selectbox('Тема', ['Все'] + THEMES, key='theme_filter')
    readiness = c.selectbox('Уровень готовности', ['Все'] + LEVELS, key='readiness_filter')
    filtered = [t for t in all_tasks if (theme == 'Все' or t['theme'] == theme)
                and (readiness == 'Все' or level(t['score']) == readiness)
                and query.casefold() in ' '.join(t['card'].values()).casefold()]
    st.caption('По убыванию рейтинга; при равенстве — по дате создания. Низкий балл не ограничивает отклики.')
    if not filtered:
        st.info('Совпадений нет. Сбросьте фильтры.')
    for t in filtered:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.subheader(t['card'].get('title') or 'Без названия')
            left.caption(f"{t['theme']} · {by_id[t['owner_id']]['name']} · {level(t['score'])}")
            left.write(t['card'].get('result') or t['card'].get('context') or 'Результат нужно уточнить.')
            right.metric('Готовность', f"{t['score']}/100")
            if t['score'] >= 90:
                st.success('★ Приоритетная задача · описание максимально раскрыто по рубрике MVP')
            elif t['score'] < 40:
                st.caption('Требует уточнения. Отклики открыты.')
            with st.expander('Карточка и расшифровка рейтинга'):
                main, side = st.columns([2, 1])
                with main:
                    details(t)
                with side:
                    rating(t['card'], t['confirmed'])
            if role == 'Команда':
                with st.expander('Подать предложение'):
                    with st.form(f"proposal_{t['id']}"):
                        idea = st.text_area('Идея решения', max_chars=6000)
                        plan = st.text_area('План работы', max_chars=6000)
                        deadline = st.text_input('Предлагаемый срок', max_chars=300)
                        link = st.text_input('Ссылка на прототип / репозиторий', placeholder='https://…', max_chars=2000)
                        sent = st.form_submit_button('Отправить предложение', type='primary')
                    if sent:
                        db.propose(t['id'], person, idea, plan, deadline, link)
                        finish('Предложение сохранено. Решение принимает бизнес.')
            else:
                st.caption('Чтобы откликнуться, выберите демо-роль «Команда». Просмотр доступен всем.')


def constructor() -> None:
    if role != 'Бизнес':
        st.info('Для создания и редактирования выберите демо-роль «Бизнес».')
        return
    st.subheader('Конструктор задачи')
    owned = db.tasks(owner_id=person)
    ids = [0] + [t['id'] for t in owned]
    names = {t['id']: t['card'].get('title') or t['original'][:65] for t in owned}
    if 'pending_editor' in st.session_state:
        st.session_state['editor_task'] = st.session_state.pop('pending_editor')
    if st.session_state.get('editor_task', 0) not in ids:
        st.session_state['editor_task'] = 0
    selected = st.selectbox('Новая или существующая задача', ids,
                            format_func=lambda i: '＋ Новая задача' if i == 0 else f'#{i} · {names[i]}', key='editor_task')
    if not selected:
        with st.form('new_task'):
            original = st.text_area('Опишите потребность своими словами', max_chars=12000, height=140,
                                    placeholder='У нас учебный центр. Менеджеры отвечают на одинаковые вопросы. Хотим автоматизировать.')
            theme = st.selectbox('Тема задачи', THEMES)
            live = st.checkbox('Использовать OpenAI API (ключ берётся из .env)')
            consent = st.checkbox('Разрешаю отправить исходное описание внешнему AI; конфиденциальных данных здесь нет')
            submitted = st.form_submit_button('Разобрать потребность', type='primary')
        if submitted:
            if not 10 <= len(original.strip()) <= 12000:
                st.error('Введите от 10 до 12 000 символов.')
                return
            if live and not consent:
                st.error('Для внешнего API нужно согласие. Локальный режим ничего не отправляет.')
                return
            with st.spinner('Разбираем описание…'):
                result, note = interview(original.strip(), theme, live)
            new_id = db.create_draft(person, original, theme, result['card'], result['questions'])
            st.session_state['pending_editor'] = new_id
            finish(note)
        return
    t = db.task(selected)
    st.caption(f"Задача #{t['id']} · {'Опубликована' if t['published'] else 'Не опубликована'} · версия {t['version']}")
    with st.expander('Исходная потребность'):
        st.text(t['original'])
    if not t['published']:
        questions = t['questions'] or local_interview(t['original'], t['theme'])['questions']
        with st.expander('1 · Уточняющие вопросы', expanded=True):
            with st.form(f"answers_{t['id']}_{t['version']}"):
                answers = {q['field']: st.text_area(q['question'], value=t['card'].get(q['field'], ''), max_chars=6000,
                                                   key=f"answer_{t['id']}_{t['version']}_{q['field']}") for q in questions}
                answered = st.form_submit_button('Перенести ответы в карточку')
            if answered:
                updated = {**t['card'], **answers}
                db.save_card(t['id'], person, t['version'], updated, False)
                finish('Ответы перенесены дословно. Проверьте карточку и подтвердите сведения ниже.')
    main, side = st.columns([2, 1], gap='large')
    with main:
        st.markdown('### 2 · Проверьте и дополните карточку')
        with st.form(f"editor_{t['id']}_{t['version']}"):
            card = {'title': st.text_input('Название', value=t['card'].get('title', ''), max_chars=140)}
            for k, label, weight, _, question in FIELDS:
                card[k] = st.text_area(f'{label} · до {weight} баллов', value=t['card'].get(k, ''),
                                       help=question, max_chars=6000, height=85, key=f"field_{t['id']}_{t['version']}_{k}")
            confirm = st.checkbox('Я проверил и подтверждаю заполненные сведения этой версии', key=f"confirm_{t['id']}_{t['version']}")
            publish = st.checkbox('Опубликовать в общем каталоге', value=bool(t['published']), disabled=bool(t['published']))
            st.caption('Все поля, включая рабочий контакт, будут общедоступны после публикации. Не добавляйте секреты или личные данные.')
            preview = st.form_submit_button('Предпросмотр рейтинга')
            saved = st.form_submit_button('Сохранить карточку', type='primary')
        if saved:
            new_score = db.save_card(t['id'], person, t['version'], card, confirm, publish)
            finish(f"Сохранено. Рейтинг {t['score']} → {new_score}/100. " + ('Задача доступна в каталоге.' if publish or t['published'] else 'Публикация пока выключена.'))
        if preview:
            st.info('Предпросмотр не сохраняет поля и не меняет каталог. Для начисления подтвердите и сохраните карточку.')
        with st.expander('История рейтинга'):
            st.dataframe(db.rows('SELECT version AS Версия,score AS Баллы,created AS Дата FROM revisions WHERE task_id=? ORDER BY version', (t['id'],)),
                         hide_index=True, use_container_width=True)
    with side:
        st.markdown('### 3 · Готовность к работе')
        rating(card if preview else t['card'], KEYS if preview else t['confirmed'], preview=preview)


def business_dashboard() -> None:
    if role != 'Бизнес':
        st.info('Выберите демо-роль «Бизнес».')
        return
    st.subheader('Мои задачи и предложения')
    owned = db.tasks(owner_id=person)
    if not owned:
        st.info('Создайте первую задачу в конструкторе.')
        return
    choices = {t['id']: t for t in owned}
    tid = st.selectbox('Задача', list(choices), format_func=lambda i: f"#{i} · {choices[i]['card'].get('title') or 'Без названия'}")
    t = choices[tid]
    st.caption(f"{t['score']}/100 · {level(t['score'])} · {'Опубликована' if t['published'] else 'Не опубликована'}")
    props = db.rows('SELECT * FROM proposals WHERE task_id=? ORDER BY id DESC', (tid,))
    st.info('Можно выбрать одну, несколько или ни одной команды. Выбор одной не отклоняет остальные предложения.')
    if props:
        st.dataframe([{'Команда': by_id[p['team_id']]['name'], 'Идея': p['idea'], 'Срок': p['deadline'],
                       'Решение': STATUS[p['status']]} for p in props], hide_index=True, use_container_width=True)
    else:
        st.caption('Предложений пока нет.')
    for p in props:
        with st.expander(f"Отклик #{p['id']} · {by_id[p['team_id']]['name']} · {STATUS[p['status']]}"):
            st.text(p['idea'])
            st.text(p['plan'])
            st.text('Срок: ' + p['deadline'])
            if db.valid_url(p['link']):
                st.link_button('Прототип / репозиторий', p['link'])
            if p['task_version'] != t['version']:
                st.warning(f"Предложение подано к версии {p['task_version']}; сейчас версия {t['version']}. Согласуйте изменения с командой.")
            a, b = st.columns(2)
            if a.button('Выбрать команду', key=f"select_{p['id']}", disabled=p['status'] == 'selected'):
                db.decide(p['id'], person, 'selected')
                finish('Команда выбрана вами; остальные отклики не изменены.')
            if b.button('Отклонить', key=f"reject_{p['id']}", disabled=p['status'] == 'rejected'):
                db.decide(p['id'], person, 'rejected')
                finish('Отклик отклонён.')
    st.markdown('### Подтверждение результата')
    for m in db.rows('SELECT * FROM milestones WHERE task_id=? ORDER BY id DESC', (tid,)):
        with st.container(border=True):
            st.write(by_id[m['team_id']]['name'])
            st.text(m['description'])
            if db.valid_url(m['link']):
                st.link_button('Посмотреть результат', m['link'])
            if m['approved_at']:
                st.success('Этап подтверждён. Начислено 50 баллов за прогресс.')
            elif st.button('Подтвердить этап и начислить 50 баллов', key=f"approve_{m['id']}"):
                db.approve_milestone(m['id'], person)
                finish('Этап подтверждён. Повторное начисление исключено.')


def team_dashboard() -> None:
    if role != 'Команда':
        st.info('Выберите демо-роль «Команда».')
        return
    st.subheader(by_id[person]['name'])
    st.caption(by_id[person]['details'])
    total = db.rows('SELECT COALESCE(SUM(points),0) AS total FROM milestones WHERE team_id=?', (person,))[0]['total']
    st.metric('Баллы за подтверждённый прогресс', total)
    st.caption('50 баллов за один подтверждённый результат команды по задаче. Не влияет на рейтинг бизнес-задачи.')
    props = db.rows('SELECT * FROM proposals WHERE team_id=? ORDER BY id DESC', (person,))
    if not props:
        st.info('Найдите интересную задачу в каталоге и отправьте предложение.')
    for p in props:
        t = db.task(p['task_id'])
        with st.container(border=True):
            st.subheader(t['card'].get('title') or 'Задача без названия')
            st.write(STATUS[p['status']])
            st.text(p['idea'])
            st.text(p['plan'])
            milestones = db.rows('SELECT * FROM milestones WHERE task_id=? AND team_id=?', (p['task_id'], person))
            if milestones:
                st.info('Результат подтверждён.' if milestones[0]['approved_at'] else 'Результат отправлен на подтверждение бизнесу.')
            elif p['status'] == 'selected':
                with st.form(f"milestone_{p['id']}"):
                    description = st.text_area('Что фактически готово', max_chars=6000)
                    link = st.text_input('Ссылка на результат', max_chars=2000)
                    sent = st.form_submit_button('Отправить этап бизнесу')
                if sent:
                    db.submit_milestone(p['id'], person, description, link)
                    finish('Этап отправлен. Баллы начислит бизнес после проверки.')


def about() -> None:
    st.subheader('TaskUp · сценарий хакатона')
    st.write('Потребность → уточнения → карточка → подтверждение → рейтинг → каталог → предложение → ручной выбор → результат.')
    st.markdown('**Геймификация бизнеса:** 20 + 20 + 15 + 15 + 10 + 10 + 10 = 100. Вес каждого поля показан в редакторе.')
    st.write('Баллы начисляются подтверждённым, непустым и недублирующимся полям: минимум 12 символов и 3 разных слова; контакт проверяется отдельно. Заглушки дают 0. Критерии успеха без числа или упоминания теста, проверки, чек-листа получают 5 из 15.')
    st.write('Это эвристика полноты, а не смысловая экспертиза: формально подходящий бессмысленный текст может получить баллы. Рейтинг не гарантирует достоверность сведений или реализуемость задачи.')
    st.write('0–39: Черновик. 40–69: Рабочая. 70–89: Готовая. 90–100: Приоритетная. Все опубликованные уровни доступны всем командам.')
    st.warning('Локальный демонстрационный MVP: нет настоящей авторизации, модерации и защиты для публичного продакшена. Только синтетические данные.')
    st.write('Без ключа используются явно помеченные шаблонные вопросы. Внешний AI вызывается по выбору и с согласием пользователя; неверный ответ заменяется демо-режимом с предупреждением.')
    with st.expander('Промпт и контракт AI'):
        st.code(PROMPT, language='text')
        st.code(json.dumps({'original': 'Текст потребности', 'theme': 'Образование'}, ensure_ascii=False), language='json')
        st.json(SCHEMA)
    st.caption('Синтетические данные: 5 черновиков, 5 опубликованных карточек, 5 команд и 5 откликов. Ссылки example.com — демонстрационные.')


try:
    {'Каталог': catalogue, 'Конструктор': constructor, 'Кабинет бизнеса': business_dashboard,
     'Кабинет команды': team_dashboard, 'О проекте': about}[page]()
except ValueError as exc:
    st.error(str(exc))
except db.sqlite3.Error:
    st.error('Ошибка базы данных. Проверьте доступ к папке data. Данные не сбрасываются автоматически.')
