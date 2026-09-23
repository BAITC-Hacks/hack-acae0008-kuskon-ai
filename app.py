"""TaskUp by Kuskon AI. Run: python -m streamlit run app.py"""
import json
import os
from html import escape
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
from ui import (
    brand, catalog_rank_label, display_card_views, icon, page_heading, readiness_badge,
    score_gain_label, task_summary,
    translation_list_notice, translation_notice,
)

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

st.markdown(f'<style>{(ROOT / "assets" / "taskup.css").read_text(encoding="utf-8")}</style>',
            unsafe_allow_html=True)

profiles = db.rows('SELECT * FROM profiles ORDER BY id')
by_id = {p['id']: p for p in profiles}

st.session_state.setdefault('lang', 'ru')
st.session_state.setdefault('user_role', None)
st.session_state.setdefault('active_page', None)


def choose_language(key: str) -> str:
    current = st.session_state.get('lang', 'ru')
    with st.container(key=f'language_{key}'):
        for col, (code, name) in zip(st.columns(3, gap='small'), LANGUAGES.items()):
            col.button(name, key=f'{key}_{code}', use_container_width=True,
                       type='primary' if code == current else 'secondary',
                       on_click=set_language, args=(code,))
    return current


def set_language(code: str) -> None:
    st.session_state['lang'] = code


def navigate(page: str) -> None:
    st.session_state['active_page'] = page
    st.session_state.pop('selected_catalog_task', None)


def enter_role(role: str) -> None:
    st.session_state['user_role'] = role
    navigate('business' if role == 'business' else 'catalog')


def switch_role() -> None:
    st.session_state['user_role'] = None
    st.session_state['active_page'] = None
    for key in ('business_profile', 'team_profile', 'editor_task',
                'selected_catalog_task', 'dashboard_task', 'pending_editor'):
        st.session_state.pop(key, None)


def role_landing() -> None:
    lang = st.session_state['lang']
    with st.container(key='landing_topbar'):
        top_a, top_b = st.columns([3, 2])
        with top_a:
            brand()
        with top_b:
            choose_language('landing_language')
    st.markdown(
        f'''<div class="tu-hero landing">
            <div class="tu-kicker">{tr(lang, 'landing_eyebrow')}</div>
            <h1>{tr(lang, 'landing_title')}</h1>
            <p>{tr(lang, 'landing_text')}</p>
        </div>''',
        unsafe_allow_html=True,
    )
    steps = ''.join(
        f'<div class="tu-flow-step"><span>0{i}</span><div>'
        f'<strong>{tr(lang, f"landing_step_{step}")}</strong>'
        f'<p>{tr(lang, f"landing_step_{step}_text")}</p></div></div>'
        for i, step in enumerate(('brief', 'match', 'build'), 1)
    )
    st.markdown(f'<div class="tu-hero-flow">{steps}</div>', unsafe_allow_html=True)
    st.subheader(tr(lang, 'role_prompt'))
    business_col, team_col = st.columns(2, gap='large')
    for col, role in ((business_col, 'business'), (team_col, 'team')):
        with col, st.container(border=False, key=f'role_{role}'):
            tools_markup = ''.join(f'<span>{escape(item.strip())}</span>'
                                   for item in tr(lang, f'{role}_tools').split('·'))
            st.markdown(
                f'<div class="tu-role"><div class="tu-role-icon">{icon(role)}</div>'
                f'<h3>{tr(lang, f"{role}_role")}</h3>'
                f'<p>{tr(lang, f"{role}_role_desc")}</p>'
                f'<div class="tu-role-points">{tools_markup}</div></div>',
                unsafe_allow_html=True,
            )
            st.button(tr(lang, f'enter_{role}') + ' →', key=f'enter_{role}',
                      type='primary' if role == 'business' else 'secondary',
                      use_container_width=True, on_click=enter_role, args=(role,))
    st.markdown(
        f'<div class="tu-footer"><span>TaskUp · Kuskon AI · AI Sana</span>'
        f'<span>{tr(lang, "role_prompt_text")}</span></div>', unsafe_allow_html=True,
    )


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


def card_views(tasks, *, fields=None) -> dict:
    return display_card_views(
        tasks, st.session_state['lang'], fields=fields,
        protected_terms=tuple(profile['name'] for profile in profiles),
    )


def details(task: dict, display_card: dict | None = None) -> None:
    lang = st.session_state['lang']
    card = task['card'] if display_card is None else display_card
    for key, *_ in FIELDS:
        st.markdown(f"**{field_label(lang, key)}**")
        st.write(card.get(key) or tr(lang, 'need_clarify'))
    st.caption(f"{tr(lang, 'version')} {task['version']} · #{task['id']}")


def catalogue(role: str, person: int) -> None:
    lang = st.session_state['lang']
    all_tasks = db.tasks(published=True)
    selected = st.session_state.get('selected_catalog_task')
    selected_task = next((task for task in all_tasks if task['id'] == selected), None)
    if selected_task:
        catalogue_detail(selected_task, role, person)
        return

    # Streamlit removes widget state when detail view hides the filter controls.
    # Restore the last filter values when returning to the marketplace.
    for key, value in st.session_state.get('catalog_filters', {}).items():
        st.session_state.setdefault(key, value)

    c1, c2, c3 = st.columns(3)
    c1.metric(tr(lang, 'open_tasks'), len(all_tasks))
    c2.metric(tr(lang, 'ready_priority'), sum(t['score'] >= 70 for t in all_tasks))
    c3.metric(tr(lang, 'demo_teams'), sum(p['role'] == 'team' for p in profiles))

    with st.container(border=False, key='catalog_filters'):
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
    ]
    views = card_views(filtered, fields=('title', 'result'))
    # A visible translated title/result should also be discoverable by search.
    # The original fields remain searchable, with the same ordering and levels.
    filtered = [
        task for task in filtered
        if query.casefold() in ' '.join(
            [*task['card'].values(), *views[task['id']].card.values()]
        ).casefold()
    ]
    st.markdown(f'**{tr(lang, "results_count", count=len(filtered))}**')
    st.caption(tr(lang, 'catalog_sort'))
    if not filtered:
        with st.container(border=True):
            st.markdown(f'<div class="tu-empty">{tr(lang, "no_results")}</div>', unsafe_allow_html=True)
            st.button(tr(lang, 'reset_filters'), key='reset_filters', on_click=reset_catalog_filters)

    for start in range(0, len(filtered), 2):
        for position, (column, task) in enumerate(
            zip(st.columns(2, gap='medium'), filtered[start:start + 2]), start=start + 1,
        ):
            with column, st.container(border=False, key=f'market_card_{task["id"]}'):
                st.caption(catalog_rank_label(position, len(filtered), lang))
                view = views[task['id']]
                task_summary(task, by_id[task['owner_id']]['name'], lang, display_card=view.card)
                translation_notice(view, task['card'], lang)
                st.button(
                    tr(lang, 'open_apply' if role == 'team' else 'open_task') + ' →',
                    key=f'open_task_{task["id"]}', use_container_width=True,
                    on_click=open_catalog_task, args=(task['id'],),
                )


def reset_catalog_filters() -> None:
    st.session_state.update(search='', theme_filter='__all__', readiness_filter='__all__')
    st.session_state.pop('catalog_filters', None)


def open_catalog_task(task_id: int) -> None:
    st.session_state['catalog_filters'] = {
        key: st.session_state.get(key, default)
        for key, default in (('search', ''), ('theme_filter', '__all__'), ('readiness_filter', '__all__'))
    }
    st.session_state['selected_catalog_task'] = task_id


def catalogue_detail(task: dict, role: str, person: int) -> None:
    lang = st.session_state['lang']
    st.button('← ' + tr(lang, 'back_catalog'), key='back_catalog',
              on_click=navigate, args=('catalog',))
    view = card_views([task])[task['id']]
    main, side = st.columns([1.4, 1], gap='large')
    with main:
        with st.container(border=True):
            task_summary(task, by_id[task['owner_id']]['name'], lang,
                         compact=False, display_card=view.card)
            translation_notice(view, task['card'], lang)
        if task['score'] >= 90:
            st.caption(tr(lang, 'priority_task'))
        elif task['score'] < 40:
            st.caption(tr(lang, 'needs_clarification'))
        with st.expander(tr(lang, 'task_details'), expanded=True):
            details(task, view.card)
    with side:
        if role == 'team':
            st.subheader(tr(lang, 'submit_proposal'))
            st.caption(tr(lang, 'proposal_intro'))
            with st.form(f"proposal_{task['id']}"):
                idea = st.text_area(tr(lang, 'idea'), max_chars=6000)
                plan = st.text_area(tr(lang, 'plan'), max_chars=6000)
                deadline = st.text_input(tr(lang, 'deadline'), max_chars=300)
                link = st.text_input(tr(lang, 'prototype_link'), placeholder='https://…', max_chars=2000)
                sent = st.form_submit_button(tr(lang, 'send_proposal'), type='primary', use_container_width=True)
            if sent:
                db.propose(task['id'], person, idea, plan, deadline, link)
                finish(tr(lang, 'proposal_saved'))
        else:
            st.info(tr(lang, 'team_role_hint'))
        with st.expander(tr(lang, 'score_breakdown'), expanded=role == 'business'):
            rating(task['card'], task['confirmed'])


def constructor(person: int) -> None:
    lang = st.session_state['lang']
    owned = db.tasks(owner_id=person)
    ids = [0] + [t['id'] for t in owned]
    title_views = card_views(owned, fields=('title',))
    names = {t['id']: title_views[t['id']].card.get('title') or t['original'][:65] for t in owned}

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
    translation_list_notice(title_views, lang)

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

    # Only this read-only preview receives a translated copy. Editable values,
    # confirmation, persistence, and scoring below always use the original card.
    view = card_views([task])[task['id']]
    st.caption(tr(lang, 'editor_original_notice'))
    if not st.session_state.get('show_original_content', False):
        with st.expander(tr(lang, 'translated_preview')):
            st.subheader(view.card.get('title') or tr(lang, 'need_clarify'))
            translation_notice(view, task['card'], lang, show_original=False)
            details(task, view.card)

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
            gain = score_gain_label(task['score'], new_score, lang) if confirm else ''
            finish(
                tr(lang, 'saved_rating', old=task['score'], new=new_score)
                + (f' {gain}' if gain else '')
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
    owned = db.tasks(owner_id=person)
    all_props = db.rows(
        'SELECT p.* FROM proposals p JOIN tasks t ON t.id=p.task_id WHERE t.owner_id=?',
        (person,),
    )
    awaiting = db.rows(
        'SELECT m.id FROM milestones m JOIN tasks t ON t.id=m.task_id '
        'WHERE t.owner_id=? AND m.approved_at IS NULL', (person,),
    )
    for col, label, value in zip(
        st.columns(4),
        ('all_my_tasks', 'published_tasks', 'incoming_proposals', 'awaiting_review'),
        (len(owned), sum(bool(t['published']) for t in owned), len(all_props), len(awaiting)),
    ):
        col.metric(tr(lang, label), value)

    title_col, action_col = st.columns([3, 1])
    title_col.subheader(tr(lang, 'tasks_overview'))
    action_col.button(tr(lang, 'new_task'), type='primary', use_container_width=True,
                      key='dashboard_new_task', on_click=edit_task, args=(0,))

    if not owned:
        st.info(tr(lang, 'create_first'))
        return

    choices = {t['id']: t for t in owned}
    views = card_views(owned, fields=('title',))
    if st.session_state.get('dashboard_task') not in choices:
        st.session_state['dashboard_task'] = owned[0]['id']
    with st.container(key='dashboard_overview'):
        for item in owned:
            with st.container(border=True):
                info, action = st.columns([4, 1])
                count = sum(p['task_id'] == item['id'] for p in all_props)
                pub_label = tr(lang, 'published' if item['published'] else 'unpublished')
                info.markdown(
                    '<div class="tu-dashboard-task">'
                    f'<h3>{escape(views[item["id"]].card.get("title") or tr(lang, "need_clarify"))}</h3>'
                    f'<div class="tu-dashboard-meta"><span>#{item["id"]} · {escape(pub_label)}</span>'
                    f'<span>{item["score"]}/100</span>{readiness_badge(lang, item["score"])}'
                    f'<span>{tr(lang, "incoming_proposals")}: {count}</span></div></div>',
                    unsafe_allow_html=True,
                )
                with info:
                    translation_notice(views[item['id']], item['card'], lang)
                action.button(tr(lang, 'manage_task'), key=f'manage_{item["id"]}',
                              use_container_width=True, on_click=select_dashboard_task, args=(item['id'],))
                action.button(tr(lang, 'edit_task'), key=f'edit_{item["id"]}',
                              use_container_width=True, on_click=edit_task, args=(item['id'],))

    task_id = st.selectbox(
        tr(lang, 'dashboard_task_label'),
        list(choices),
        format_func=lambda i: f"#{i} · {views[i].card.get('title') or tr(lang, 'need_clarify')}",
        key='dashboard_task',
    )
    translation_list_notice(views, lang)
    task = choices[task_id]
    st.caption(
        f"{task['score']}/100 · {level_label(lang, level(task['score']))} · "
        f"{tr(lang, 'published') if task['published'] else tr(lang, 'unpublished')}"
    )

    props = db.rows('SELECT * FROM proposals WHERE task_id=? ORDER BY id DESC', (task_id,))
    st.subheader(tr(lang, 'proposals_section'))
    st.info(tr(lang, 'multi_select_info'))

    if not props:
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
    milestones = db.rows('SELECT * FROM milestones WHERE task_id=? ORDER BY id DESC', (task_id,))
    if not milestones:
        st.caption(tr(lang, 'no_milestones'))
    for milestone in milestones:
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


def select_dashboard_task(task_id: int) -> None:
    st.session_state['dashboard_task'] = task_id


def edit_task(task_id: int) -> None:
    st.session_state['pending_editor'] = task_id
    navigate('constructor')


def team_dashboard(person: int) -> None:
    lang = st.session_state['lang']
    st.caption(by_id[person]['details'])

    total = db.rows(
        'SELECT COALESCE(SUM(points),0) AS total FROM milestones WHERE team_id=?',
        (person,),
    )[0]['total']
    props = db.rows('SELECT * FROM proposals WHERE team_id=? ORDER BY id DESC', (person,))
    a, b, c = st.columns(3)
    a.metric(tr(lang, 'incoming_proposals'), len(props))
    b.metric(status_label(lang, 'selected'), sum(p['status'] == 'selected' for p in props))
    c.metric(tr(lang, 'points_metric'), total)
    st.caption(tr(lang, 'points_caption'))
    st.subheader(tr(lang, 'portfolio'))
    if not props:
        st.info(tr(lang, 'find_task'))

    tasks = {prop['task_id']: db.task(prop['task_id']) for prop in props}
    views = card_views(tasks.values(), fields=('title',))
    for prop in props:
        task = tasks[prop['task_id']]
        with st.container(border=True):
            st.subheader(views[task['id']].card.get('title') or tr(lang, 'need_clarify'))
            translation_notice(views[task['id']], task['card'], lang)
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

    nav = [
        *(([('business', tr(lang, 'nav_business'))]) if role == 'business' else []),
        *(([('team', tr(lang, 'nav_team'))]) if role == 'team' else []),
        ('catalog', tr(lang, 'nav_catalog')),
        *(([('constructor', tr(lang, 'nav_constructor'))]) if role == 'business' else []),
        ('about', tr(lang, 'nav_about')),
    ]
    if st.session_state.get('active_page') not in dict(nav):
        st.session_state['active_page'] = 'catalog'
    page = st.session_state['active_page']
    nav_icons = {'business': ':material/space_dashboard:', 'team': ':material/workspaces:',
                 'catalog': ':material/grid_view:', 'constructor': ':material/add_circle:',
                 'about': ':material/info:'}

    with st.sidebar:
        brand()
        st.divider()
        st.caption(tr(lang, 'workspace'))
        with st.container(key='navigation'):
            for key, label in nav:
                st.button(label, key=f'nav_{key}', icon=nav_icons[key],
                          type='primary' if page == key else 'secondary',
                          use_container_width=True, on_click=navigate, args=(key,))
        st.divider()
        st.markdown(f'**{role_name}**')
        person = st.selectbox(
            tr(lang, 'profile'), profile_ids,
            format_func=lambda i: by_id[i]['name'], key=profile_key,
        )
        choose_language('sidebar_language')
        st.checkbox(tr(lang, 'show_original'), key='show_original_content')
        st.caption(tr(lang, 'demo_notice'))
        st.divider()
        st.caption(tr(lang, 'principle'))

    with st.container(key='workspace_topbar'):
        identity, switch = st.columns([3, 1])
        identity.caption(f'TaskUp / {by_id[person]["name"]}')
        switch.button('← ' + tr(lang, 'change_role'), key='change_role',
                      use_container_width=True, on_click=switch_role)

    headings = {
        'catalog': ('catalog_title', 'catalog_description'),
        'business': ('business_dashboard', 'dashboard_description'),
        'constructor': ('constructor_title', 'builder_description'),
        'team': ('nav_team', 'team_description'),
        'about': ('about_title', 'brand_kicker'),
    }
    title, description = headings[page]
    page_heading(tr(lang, title), tr(lang, description), role_name)

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
