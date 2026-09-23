"""TaskUp by Kuskon AI. Run: python -m streamlit run app.py"""
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import database as db
from ai_service import PROMPT, SCHEMA, build_prompt, interview, local_interview
from i18n import (
    LANGUAGES, LEVEL_TEXT, STATUS_TEXT, THEME_TEXT,
    field_label, field_question, level_label, status_label, theme_label, tr,
)
from scoring import FIELDS, KEYS, THEMES, LEVELS, level, score_card
from seed_data import seed

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

st.set_page_config(
    page_title='TaskUp · Kuskon AI',
    page_icon='✦',
    layout='wide',
    initial_sidebar_state='expanded',
)


def load_streamlit_secrets() -> None:
    """Copy local Streamlit secrets into env without ever displaying them."""
    try:
        for key in ('OPENAI_API_KEY', 'OPENAI_MODEL'):
            value = st.secrets.get(key)
            if value and not os.getenv(key):
                os.environ[key] = str(value)
    except Exception:
        # A missing secrets.toml is valid: the MVP has an explicit local fallback.
        pass


load_streamlit_secrets()

try:
    seed()
except (OSError, db.sqlite3.Error):
    st.error('Не удалось открыть базу / Database unavailable.')
    st.stop()

st.markdown(
    '''<style>
    :root {
        --tu-border: rgba(148,163,184,.22);
        --tu-muted: #9ca3af;
        --tu-panel: rgba(17,24,39,.72);
        --tu-accent: #8b5cf6;
        --tu-accent-2: #22d3ee;
    }
    .block-container {max-width: 1220px; padding-top: 1.4rem; padding-bottom: 3rem;}
    [data-testid="stSidebar"] {border-right:1px solid var(--tu-border);}
    [data-testid="stSidebar"] .block-container {padding-top:1rem;}
    h1,h2,h3 {letter-spacing:-.035em;}
    .tu-hero {
        position:relative; overflow:hidden; padding:34px 36px; margin:4px 0 24px;
        border:1px solid var(--tu-border); border-radius:26px;
        background:
          radial-gradient(circle at 88% 12%, rgba(34,211,238,.18), transparent 28%),
          radial-gradient(circle at 15% 8%, rgba(139,92,246,.24), transparent 31%),
          linear-gradient(145deg, rgba(17,24,39,.96), rgba(30,27,75,.78));
        box-shadow:0 18px 50px rgba(0,0,0,.18);
    }
    .tu-kicker {font-size:.76rem; letter-spacing:.18em; font-weight:800; color:#c4b5fd;}
    .tu-hero h1 {font-size:clamp(2.1rem,5vw,4.3rem); line-height:1.02; max-width:850px; margin:.55rem 0 .8rem;}
    .tu-hero p {font-size:1.08rem; color:#cbd5e1; max-width:800px; margin:0;}
    .tu-role {
        border:1px solid var(--tu-border); border-radius:22px; padding:22px;
        background:linear-gradient(160deg, rgba(30,41,59,.76), rgba(15,23,42,.7));
        min-height:170px;
    }
    .tu-role-icon {font-size:2rem;}
    .tu-role h3 {margin:.45rem 0 .35rem;}
    .tu-role p {color:#aeb8c8; min-height:48px;}
    .tu-pill {
        display:inline-block; padding:5px 10px; border-radius:999px;
        background:rgba(139,92,246,.14); border:1px solid rgba(139,92,246,.28);
        color:#ddd6fe; font-size:.8rem; font-weight:700;
    }
    .tu-brand {font-size:1.4rem;font-weight:900;letter-spacing:-.04em;}
    .tu-brand span {color:#a78bfa;}
    .tu-task-head {display:flex;justify-content:space-between;gap:16px;align-items:flex-start;}
    .tu-empty {color:#94a3b8;}
    [data-testid="stMetric"] {
        border:1px solid var(--tu-border); border-radius:18px; padding:12px 14px;
        background:rgba(15,23,42,.28);
    }
    [data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button {
        border-radius:12px; font-weight:700;
    }
    [data-testid="stExpander"] {border:1px solid var(--tu-border); border-radius:16px;}
    div[data-testid="stVerticalBlockBorderWrapper"] {border-radius:18px;}
    </style>''',
    unsafe_allow_html=True,
)

profiles = db.rows('SELECT * FROM profiles ORDER BY id')
by_id = {p['id']: p for p in profiles}

st.session_state.setdefault('lang', 'ru')
st.session_state.setdefault('user_role', None)
st.session_state.setdefault('active_page', None)


def choose_language(key: str) -> str:
    current = st.session_state.get('lang', 'ru')
    options = list(LANGUAGES)
    idx = options.index(current) if current in options else 0
    selected = st.selectbox(
        tr(current, 'language'),
        options,
        index=idx,
        format_func=lambda code: LANGUAGES[code],
        key=key,
        label_visibility='collapsed',
    )
    if selected != current:
        st.session_state['lang'] = selected
        st.rerun()
    return selected


def switch_role() -> None:
    st.session_state['user_role'] = None
    st.session_state['active_page'] = None
    for key in ('business_profile', 'team_profile', 'editor_task'):
        st.session_state.pop(key, None)
    st.rerun()


def role_landing() -> None:
    lang = st.session_state['lang']
    top_a, top_b = st.columns([5, 1])
    with top_a:
        st.markdown('<div class="tu-brand">Task<span>Up</span> ✦</div>', unsafe_allow_html=True)
    with top_b:
        choose_language('landing_language')

    st.markdown(
        f'''<div class="tu-hero">
            <div class="tu-kicker">{tr(lang, 'brand_kicker')}</div>
            <h1>{tr(lang, 'landing_title')}</h1>
            <p>{tr(lang, 'landing_text')}</p>
        </div>''',
        unsafe_allow_html=True,
    )

    st.subheader(tr(lang, 'role_prompt'))
    st.caption(tr(lang, 'role_prompt_text'))
    business_col, team_col = st.columns(2, gap='large')

    with business_col:
        st.markdown(
            f'''<div class="tu-role">
                <div class="tu-role-icon">🏢</div>
                <h3>{tr(lang, 'business_role')}</h3>
                <p>{tr(lang, 'business_role_desc')}</p>
                <span class="tu-pill">AI → 100</span>
            </div>''',
            unsafe_allow_html=True,
        )
        if st.button(tr(lang, 'enter_business'), type='primary', use_container_width=True):
            st.session_state['user_role'] = 'business'
            st.session_state['active_page'] = 'catalog'
            st.rerun()

    with team_col:
        st.markdown(
            f'''<div class="tu-role">
                <div class="tu-role-icon">🎓</div>
                <h3>{tr(lang, 'team_role')}</h3>
                <p>{tr(lang, 'team_role_desc')}</p>
                <span class="tu-pill">OPEN CATALOGUE</span>
            </div>''',
            unsafe_allow_html=True,
        )
        if st.button(tr(lang, 'enter_team'), type='primary', use_container_width=True):
            st.session_state['user_role'] = 'team'
            st.session_state['active_page'] = 'catalog'
            st.rerun()

    st.divider()
    st.caption('TaskUp · Kuskon AI · AI Sana')


def group_label(lang: str, name: str) -> str:
    maps = {
        'ru': {},
        'kk': {
            'Контекст и потребность': 'Контекст және қажеттілік',
            'Данные и материалы': 'Деректер мен материалдар',
            'Ожидаемый результат': 'Күтілетін нәтиже',
            'Критерии успеха': 'Табыс критерийлері',
            'Ограничения': 'Шектеулер',
            'Пользователи': 'Пайдаланушылар',
            'Связь с бизнесом': 'Бизнеспен байланыс',
        },
        'en': {
            'Контекст и потребность': 'Context and need',
            'Данные и материалы': 'Data and materials',
            'Ожидаемый результат': 'Expected outcome',
            'Критерии успеха': 'Success criteria',
            'Ограничения': 'Constraints',
            'Пользователи': 'Users',
            'Связь с бизнесом': 'Business contact',
        },
    }
    return maps.get(lang, {}).get(name, name)


def finish(message: str) -> None:
    st.session_state['flash'] = message
    st.rerun()


def rating(card: dict, confirmed, preview: bool = False) -> None:
    lang = st.session_state['lang']
    result = score_card(card, confirmed)
    st.metric(
        tr(lang, 'preview_metric') if preview else tr(lang, 'confirmed_metric'),
        f"{result['total']}/100",
    )
    st.progress(result['total'] / 100)
    st.markdown(f"**{level_label(lang, result['level'])}**")

    rows = [
        {
            tr(lang, 'field_col'): group_label(lang, item['Критерий']),
            tr(lang, 'score'): item['Баллы'],
            'Max': item['Максимум'],
        }
        for item in result['groups']
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)

    if result['missing']:
        st.markdown(f"**{tr(lang, 'next_step')}**")
        item = result['missing'][0]
        st.info(
            f"+{item['gain']} · {field_label(lang, item['field'])}. "
            f"{field_question(lang, item['field'])}"
        )
        with st.expander(tr(lang, 'all_missing')):
            st.dataframe(
                [
                    {
                        tr(lang, 'field_col'): field_label(lang, m['field']),
                        tr(lang, 'gain_col'): m['gain'],
                        tr(lang, 'clarify_col'): field_question(lang, m['field']),
                    }
                    for m in result['missing']
                ],
                hide_index=True,
                use_container_width=True,
            )
    else:
        st.success(tr(lang, 'all_filled'))
    st.caption(tr(lang, 'score_disclaimer'))


def details(task: dict) -> None:
    lang = st.session_state['lang']
    for key, *_ in FIELDS:
        st.markdown(f"**{field_label(lang, key)}**")
        st.write(task['card'].get(key) or tr(lang, 'need_clarify'))
    st.caption(f"{tr(lang, 'version')} {task['version']} · #{task['id']}")


def catalogue(role: str, person: int) -> None:
    lang = st.session_state['lang']
    all_tasks = db.tasks(published=True)
    c1, c2, c3 = st.columns(3)
    c1.metric(tr(lang, 'open_tasks'), len(all_tasks))
    c2.metric(tr(lang, 'ready_priority'), sum(t['score'] >= 70 for t in all_tasks))
    c3.metric(tr(lang, 'demo_teams'), sum(p['role'] == 'team' for p in profiles))

    st.subheader(tr(lang, 'catalog_title'))
    a, b, c = st.columns([2, 1, 1])
    query = a.text_input(tr(lang, 'search'), placeholder=tr(lang, 'search_ph'), key='search')
    theme = b.selectbox(
        tr(lang, 'theme'), ['__all__'] + THEMES,
        format_func=lambda x: tr(lang, 'all') if x == '__all__' else theme_label(lang, x),
        key='theme_filter',
    )
    readiness = c.selectbox(
        tr(lang, 'readiness'), ['__all__'] + LEVELS,
        format_func=lambda x: tr(lang, 'all') if x == '__all__' else level_label(lang, x),
        key='readiness_filter',
    )

    filtered = [
        t for t in all_tasks
        if (theme == '__all__' or t['theme'] == theme)
        and (readiness == '__all__' or level(t['score']) == readiness)
        and query.casefold() in ' '.join(t['card'].values()).casefold()
    ]
    st.caption(tr(lang, 'catalog_sort'))

    if not filtered:
        st.info(tr(lang, 'no_results'))

    for task in filtered:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.subheader(task['card'].get('title') or tr(lang, 'need_clarify'))
            left.caption(
                f"{theme_label(lang, task['theme'])} · {by_id[task['owner_id']]['name']} · "
                f"{level_label(lang, level(task['score']))}"
            )
            left.write(task['card'].get('result') or task['card'].get('context') or tr(lang, 'need_clarify'))
            right.metric(tr(lang, 'readiness_metric'), f"{task['score']}/100")

            if task['score'] >= 90:
                st.success(tr(lang, 'priority_task'))
            elif task['score'] < 40:
                st.caption(tr(lang, 'needs_clarification'))

            with st.expander(tr(lang, 'card_rating')):
                main, side = st.columns([2, 1])
                with main:
                    details(task)
                with side:
                    rating(task['card'], task['confirmed'])

            if role == 'team':
                with st.expander(tr(lang, 'submit_proposal')):
                    with st.form(f"proposal_{task['id']}"):
                        idea = st.text_area(tr(lang, 'idea'), max_chars=6000)
                        plan = st.text_area(tr(lang, 'plan'), max_chars=6000)
                        deadline = st.text_input(tr(lang, 'deadline'), max_chars=300)
                        link = st.text_input(
                            tr(lang, 'prototype_link'),
                            placeholder='https://…',
                            max_chars=2000,
                        )
                        sent = st.form_submit_button(tr(lang, 'send_proposal'), type='primary')
                    if sent:
                        db.propose(task['id'], person, idea, plan, deadline, link)
                        finish(tr(lang, 'proposal_saved'))
            else:
                st.caption(tr(lang, 'team_role_hint'))


def constructor(person: int) -> None:
    lang = st.session_state['lang']
    st.subheader(tr(lang, 'constructor_title'))
    owned = db.tasks(owner_id=person)
    ids = [0] + [t['id'] for t in owned]
    names = {t['id']: t['card'].get('title') or t['original'][:65] for t in owned}

    if 'pending_editor' in st.session_state:
        st.session_state['editor_task'] = st.session_state.pop('pending_editor')
    if st.session_state.get('editor_task', 0) not in ids:
        st.session_state['editor_task'] = 0

    selected = st.selectbox(
        tr(lang, 'task_selector'),
        ids,
        format_func=lambda i: tr(lang, 'new_task') if i == 0 else f"#{i} · {names[i]}",
        key='editor_task',
    )

    if not selected:
        with st.form('new_task'):
            original = st.text_area(
                tr(lang, 'describe_need'),
                max_chars=12000,
                height=150,
                placeholder=tr(lang, 'describe_ph'),
            )
            theme = st.selectbox(
                tr(lang, 'task_theme'),
                THEMES,
                format_func=lambda x: theme_label(lang, x),
            )
            live = st.checkbox(tr(lang, 'use_openai'), help=tr(lang, 'ai_key_hint'))
            consent = st.checkbox(tr(lang, 'consent_ai'))
            submitted = st.form_submit_button(tr(lang, 'analyze_need'), type='primary')

        if submitted:
            if not 10 <= len(original.strip()) <= 12000:
                st.error(tr(lang, 'need_10_chars'))
                return
            if live and not consent:
                st.error(tr(lang, 'need_consent'))
                return
            with st.spinner(tr(lang, 'analyzing')):
                result, note = interview(original.strip(), theme, live, lang=lang)
            new_id = db.create_draft(person, original, theme, result['card'], result['questions'])
            st.session_state['pending_editor'] = new_id
            finish(note)
        return

    task = db.task(selected)
    pub = tr(lang, 'published') if task['published'] else tr(lang, 'unpublished')
    st.caption(f"#{task['id']} · {pub} · {tr(lang, 'version')} {task['version']}")

    with st.expander(tr(lang, 'original_need')):
        st.write(task['original'])

    if not task['published']:
        questions = task['questions'] or local_interview(task['original'], task['theme'], lang)['questions']
        with st.expander(tr(lang, 'questions_section'), expanded=True):
            with st.form(f"answers_{task['id']}_{task['version']}"):
                answers = {
                    q['field']: st.text_area(
                        q['question'],
                        value=task['card'].get(q['field'], ''),
                        max_chars=6000,
                        key=f"answer_{task['id']}_{task['version']}_{q['field']}",
                    )
                    for q in questions
                }
                answered = st.form_submit_button(tr(lang, 'answers_to_card'))
            if answered:
                updated = {**task['card'], **answers}
                db.save_card(task['id'], person, task['version'], updated, False)
                finish(tr(lang, 'answers_saved'))

    main, side = st.columns([2, 1], gap='large')
    with main:
        st.markdown(f"### {tr(lang, 'editor_section')}")
        with st.form(f"editor_{task['id']}_{task['version']}"):
            card = {
                'title': st.text_input(
                    tr(lang, 'title'),
                    value=task['card'].get('title', ''),
                    max_chars=140,
                )
            }
            for key, _, weight, _, _ in FIELDS:
                card[key] = st.text_area(
                    f"{field_label(lang, key)} · {weight}",
                    value=task['card'].get(key, ''),
                    help=field_question(lang, key),
                    max_chars=6000,
                    height=85,
                    key=f"field_{task['id']}_{task['version']}_{key}",
                )
            confirm = st.checkbox(
                tr(lang, 'confirm_fields'),
                key=f"confirm_{task['id']}_{task['version']}",
            )
            publish = st.checkbox(
                tr(lang, 'publish_catalog'),
                value=bool(task['published']),
                disabled=bool(task['published']),
            )
            st.caption(tr(lang, 'public_warning'))
            preview = st.form_submit_button(tr(lang, 'preview_score'))
            saved = st.form_submit_button(tr(lang, 'save_card'), type='primary')

        if saved:
            new_score = db.save_card(task['id'], person, task['version'], card, confirm, publish)
            finish(
                tr(lang, 'saved_rating', old=task['score'], new=new_score)
                + ' '
                + (tr(lang, 'published_now') if publish or task['published'] else tr(lang, 'not_published'))
            )

        if preview:
            st.info(tr(lang, 'preview_notice'))

        with st.expander(tr(lang, 'history')):
            history = db.rows(
                'SELECT version,score,created FROM revisions WHERE task_id=? ORDER BY version',
                (task['id'],),
            )
            st.dataframe(
                [
                    {
                        tr(lang, 'version'): r['version'],
                        tr(lang, 'score'): r['score'],
                        tr(lang, 'date'): r['created'],
                    }
                    for r in history
                ],
                hide_index=True,
                use_container_width=True,
            )

    with side:
        st.markdown(f"### {tr(lang, 'readiness_section')}")
        rating(
            card if preview else task['card'],
            KEYS if preview else task['confirmed'],
            preview=preview,
        )


def business_dashboard(person: int) -> None:
    lang = st.session_state['lang']
    st.subheader(tr(lang, 'business_dashboard'))
    owned = db.tasks(owner_id=person)

    if not owned:
        st.info(tr(lang, 'create_first'))
        return

    choices = {t['id']: t for t in owned}
    task_id = st.selectbox(
        tr(lang, 'task'),
        list(choices),
        format_func=lambda i: f"#{i} · {choices[i]['card'].get('title') or tr(lang, 'need_clarify')}",
    )
    task = choices[task_id]
    st.caption(
        f"{task['score']}/100 · {level_label(lang, level(task['score']))} · "
        f"{tr(lang, 'published') if task['published'] else tr(lang, 'unpublished')}"
    )

    props = db.rows('SELECT * FROM proposals WHERE task_id=? ORDER BY id DESC', (task_id,))
    st.info(tr(lang, 'multi_select_info'))

    if props:
        st.dataframe(
            [
                {
                    tr(lang, 'team'): by_id[p['team_id']]['name'],
                    tr(lang, 'idea'): p['idea'],
                    tr(lang, 'deadline'): p['deadline'],
                    tr(lang, 'decision'): status_label(lang, p['status']),
                }
                for p in props
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption(tr(lang, 'no_proposals'))

    for prop in props:
        with st.expander(
            f"{tr(lang, 'response')} #{prop['id']} · "
            f"{by_id[prop['team_id']]['name']} · {status_label(lang, prop['status'])}"
        ):
            st.write(prop['idea'])
            st.write(prop['plan'])
            st.caption(f"{tr(lang, 'deadline')}: {prop['deadline']}")
            if db.valid_url(prop['link']):
                st.link_button(tr(lang, 'repo_button'), prop['link'])
            if prop['task_version'] != task['version']:
                st.warning(
                    tr(
                        lang,
                        'version_warning',
                        proposal=prop['task_version'],
                        current=task['version'],
                    )
                )
            a, b = st.columns(2)
            if a.button(
                tr(lang, 'select_team'),
                key=f"select_{prop['id']}",
                disabled=prop['status'] == 'selected',
                use_container_width=True,
            ):
                db.decide(prop['id'], person, 'selected')
                finish(tr(lang, 'team_selected'))
            if b.button(
                tr(lang, 'reject'),
                key=f"reject_{prop['id']}",
                disabled=prop['status'] == 'rejected',
                use_container_width=True,
            ):
                db.decide(prop['id'], person, 'rejected')
                finish(tr(lang, 'proposal_rejected'))

    st.markdown(f"### {tr(lang, 'result_confirmation')}")
    for milestone in db.rows('SELECT * FROM milestones WHERE task_id=? ORDER BY id DESC', (task_id,)):
        with st.container(border=True):
            st.write(f"**{by_id[milestone['team_id']]['name']}**")
            st.write(milestone['description'])
            if db.valid_url(milestone['link']):
                st.link_button(tr(lang, 'view_result'), milestone['link'])
            if milestone['approved_at']:
                st.success(tr(lang, 'milestone_approved'))
            elif st.button(tr(lang, 'approve_milestone'), key=f"approve_{milestone['id']}"):
                db.approve_milestone(milestone['id'], person)
                finish(tr(lang, 'milestone_approved_msg'))


def team_dashboard(person: int) -> None:
    lang = st.session_state['lang']
    st.subheader(by_id[person]['name'])
    st.caption(by_id[person]['details'])

    total = db.rows(
        'SELECT COALESCE(SUM(points),0) AS total FROM milestones WHERE team_id=?',
        (person,),
    )[0]['total']
    st.metric(tr(lang, 'points_metric'), total)
    st.caption(tr(lang, 'points_caption'))

    props = db.rows('SELECT * FROM proposals WHERE team_id=? ORDER BY id DESC', (person,))
    if not props:
        st.info(tr(lang, 'find_task'))

    for prop in props:
        task = db.task(prop['task_id'])
        with st.container(border=True):
            st.subheader(task['card'].get('title') or tr(lang, 'need_clarify'))
            st.write(status_label(lang, prop['status']))
            st.write(prop['idea'])
            st.write(prop['plan'])

            milestones = db.rows(
                'SELECT * FROM milestones WHERE task_id=? AND team_id=?',
                (prop['task_id'], person),
            )
            if milestones:
                st.info(
                    tr(lang, 'result_approved')
                    if milestones[0]['approved_at']
                    else tr(lang, 'result_pending')
                )
            elif prop['status'] == 'selected':
                with st.form(f"milestone_{prop['id']}"):
                    description = st.text_area(tr(lang, 'actual_ready'), max_chars=6000)
                    link = st.text_input(tr(lang, 'result_link'), max_chars=2000)
                    sent = st.form_submit_button(tr(lang, 'send_stage'))
                if sent:
                    db.submit_milestone(prop['id'], person, description, link)
                    finish(tr(lang, 'stage_sent'))


def about() -> None:
    lang = st.session_state['lang']
    st.subheader(tr(lang, 'about_title'))
    st.write(tr(lang, 'about_flow'))
    st.markdown(f"**{tr(lang, 'about_gamification')}**")
    st.write(tr(lang, 'about_heuristic'))
    st.write(tr(lang, 'about_levels'))
    st.warning(tr(lang, 'about_warning'))
    st.write(tr(lang, 'about_ai'))

    with st.expander(tr(lang, 'prompt_contract')):
        st.code(build_prompt(lang), language='text')
        st.code(
            json.dumps({'original': 'Business need', 'theme': 'Education'}, ensure_ascii=False),
            language='json',
        )
        st.json(SCHEMA)

    st.caption(tr(lang, 'synthetic_caption'))


def app_shell() -> None:
    role = st.session_state['user_role']
    lang = st.session_state['lang']
    role_name = tr(lang, 'business_role') if role == 'business' else tr(lang, 'team_role')
    profile_ids = [p['id'] for p in profiles if p['role'] == role]
    profile_key = 'business_profile' if role == 'business' else 'team_profile'

    with st.sidebar:
        st.markdown('<div class="tu-brand">Task<span>Up</span> ✦</div>', unsafe_allow_html=True)
        st.caption(tr(lang, 'brand_kicker'))
        choose_language('sidebar_language')
        st.divider()

        st.markdown(f"**{role_name}**")
        person = st.selectbox(
            tr(lang, 'profile'),
            profile_ids,
            format_func=lambda i: by_id[i]['name'],
            key=profile_key,
        )
        st.caption(tr(lang, 'demo_notice'))

        if st.button(tr(lang, 'change_role'), use_container_width=True):
            switch_role()

        st.divider()

        nav = [
            ('catalog', tr(lang, 'nav_catalog')),
            *(([('constructor', tr(lang, 'nav_constructor')),
                ('business', tr(lang, 'nav_business'))]) if role == 'business' else []),
            *(([('team', tr(lang, 'nav_team'))]) if role == 'team' else []),
            ('about', tr(lang, 'nav_about')),
        ]
        nav_keys = [key for key, _ in nav]
        labels = dict(nav)
        if st.session_state.get('active_page') not in nav_keys:
            st.session_state['active_page'] = 'catalog'

        page = st.radio(
            'Navigation',
            nav_keys,
            index=nav_keys.index(st.session_state['active_page']),
            format_func=lambda key: labels[key],
            label_visibility='collapsed',
        )
        st.session_state['active_page'] = page
        st.divider()
        st.caption(tr(lang, 'principle'))

    hero_title = tr(lang, 'hero_business_title') if role == 'business' else tr(lang, 'hero_team_title')
    hero_text = tr(lang, 'hero_business_text') if role == 'business' else tr(lang, 'hero_team_text')
    st.markdown(
        f'''<div class="tu-hero">
            <div class="tu-kicker">{role_name.upper()}</div>
            <h1>{hero_title}</h1>
            <p>{hero_text}</p>
        </div>''',
        unsafe_allow_html=True,
    )

    if 'flash' in st.session_state:
        st.success(st.session_state.pop('flash'))

    try:
        if page == 'catalog':
            catalogue(role, person)
        elif page == 'constructor':
            constructor(person)
        elif page == 'business':
            business_dashboard(person)
        elif page == 'team':
            team_dashboard(person)
        else:
            about()
    except ValueError as exc:
        st.error(str(exc))
    except db.sqlite3.Error:
        st.error(tr(lang, 'db_error'))


if st.session_state['user_role'] is None:
    role_landing()
else:
    app_shell()
