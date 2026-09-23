"""Presentation-only HTML helpers. All task/profile text is escaped here."""
from html import escape
from dataclasses import dataclass

import streamlit as st

from i18n import field_label, level_label, theme_label, tr
from scoring import LEVELS, level
import translation_service


def catalog_rank_label(position: int, total: int, lang: str) -> str:
    templates = {
        'ru': '#{position} из {total} по рейтингу',
        'en': '#{position} of {total} by score',
        'kk': 'Рейтинг бойынша #{position} / {total}',
    }
    return templates.get(lang, templates['ru']).format(position=position, total=total)


def score_gain_label(old: int, new: int, lang: str) -> str:
    if new <= old:
        return ''
    labels = {'ru': 'Прирост', 'en': 'Increase', 'kk': 'Өсім'}
    return f"{labels.get(lang, labels['ru'])} +{new - old}."


@dataclass(frozen=True)
class CardView:
    """An independent display copy, never a card to save or score."""
    card: dict
    translated_fields: tuple = ()
    unavailable_fields: tuple = ()


def display_card_views(tasks, lang: str, *, fields=None, protected_terms=()) -> dict:
    tasks = list(tasks)
    requested = translation_service.TRANSLATABLE_FIELDS if fields is None else fields
    allowed = tuple(key for key in requested if key in translation_service.TRANSLATABLE_FIELDS)
    if st.session_state.get('show_original_content', False):
        return {task['id']: CardView(dict(task['card'])) for task in tasks}
    texts = [task['card'][key] for task in tasks for key in allowed
             if isinstance(task['card'].get(key), str) and task['card'][key].strip()]
    # One batch for the visible fields; subsequent views reuse individual texts.
    if texts:
        with st.spinner(tr(lang, 'translation_loading')):
            translated = translation_service.translate_texts(texts, lang, protected_terms=protected_terms)
    else:
        translated = {}
    views = {}
    for task in tasks:
        card = dict(task['card'])
        changed, unavailable = [], []
        for key in allowed:
            original = card.get(key, '')
            result = translated.get(original)
            if result is not None:
                card[key] = result.text
                if result.translated:
                    changed.append(key)
                if result.unavailable:
                    unavailable.append(key)
        views[task['id']] = CardView(card, tuple(changed), tuple(unavailable))
    return views


def translation_notice(view: CardView, original: dict, lang: str, *, show_original=True) -> None:
    if view.translated_fields:
        st.caption(tr(lang, 'auto_translation'))
        if show_original:
            with st.expander(tr(lang, 'show_original')):
                for key in view.translated_fields:
                    label = tr(lang, 'title') if key == 'title' else field_label(lang, key)
                    st.markdown(f'**{label}**')
                    st.text(original.get(key, ''))
    if view.unavailable_fields:
        st.caption(tr(lang, 'translation_unavailable'))


def translation_list_notice(views: dict, lang: str) -> None:
    """Selectors have a shared original switch in the sidebar."""
    if any(view.translated_fields for view in views.values()):
        st.caption(tr(lang, 'auto_translation'))
    if any(view.unavailable_fields for view in views.values()):
        st.caption(tr(lang, 'translation_unavailable'))


def icon(name: str) -> str:
    paths = {
        'logo': '<path d="M5 18 18 5M7 5h11v11"/>',
        'business': '<rect x="4" y="7" width="16" height="14" rx="2"/><path d="M9 7V3h6v4M9 11v2m6-2v2M9 16v2m6-2v2"/>',
        'team': '<path d="m2 8 10-5 10 5-10 5L2 8Zm4 3v6c4 3 8 3 12 0v-6M22 8v8"/>',
    }
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{paths[name]}</svg>')


def brand() -> None:
    st.markdown(
        f'<div class="tu-brand"><span class="tu-logo">{icon("logo")}</span>'
        '<div>Task<span>Up</span><div class="tu-brand-note">KUSKON AI</div></div></div>',
        unsafe_allow_html=True,
    )


def page_heading(title: str, description: str, eyebrow: str = '') -> None:
    st.markdown(
        '<div class="tu-page-heading">'
        f'<div class="tu-page-eyebrow">{escape(eyebrow)}</div>'
        f'<h1>{escape(title)}</h1><p>{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def readiness_badge(lang: str, score: int) -> str:
    readiness = level(score)
    style = ('draft', 'working', 'ready', 'priority')[LEVELS.index(readiness)]
    return f'<span class="tu-badge {style}">{escape(level_label(lang, readiness))}</span>'


def task_summary(task: dict, company: str, lang: str, *, compact: bool = True,
                 display_card: dict | None = None) -> None:
    """Translate copy only; score and identity always come from the saved task."""
    card = task['card'] if display_card is None else display_card
    title = card.get('title') or tr(lang, 'need_clarify')
    result = card.get('result') or tr(lang, 'need_clarify')
    score = task['score']
    initials = ''.join(word[0] for word in company.split()[:2])
    st.markdown(
        '<div class="tu-task-summary">'
        '<div class="tu-task-head">'
        f'<span class="tu-theme">{escape(theme_label(lang, task["theme"]))}</span>'
        f'{readiness_badge(lang, score)}</div>'
        f'<div class="tu-company"><span class="tu-avatar">{escape(initials)}</span>'
        f'{escape(company)}</div>'
        f'<h3 class="tu-task-title" title="{escape(title)}">{escape(title)}</h3>'
        f'<div class="tu-outcome-label">{escape(tr(lang, "expected_result"))}</div>'
        f'<p class="{"tu-outcome" if compact else "tu-detail-outcome"}">{escape(result)}</p>'
        '<div class="tu-card-score">'
        f'<span>{escape(tr(lang, "readiness_metric"))}</span>'
        f'<div><strong>{score}</strong><span> / 100</span></div></div>'
        f'<div class="tu-score-track" aria-hidden="true"><span style="width:{score}%"></span></div>'
        f'<div class="tu-card-meta">#{task["id"]} · {escape(tr(lang, "version"))} {task["version"]}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
