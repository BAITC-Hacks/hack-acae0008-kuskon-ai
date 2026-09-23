"""Presentation-only HTML helpers. All task/profile text is escaped here."""
from html import escape

import streamlit as st

from i18n import level_label, theme_label, tr
from scoring import LEVELS, level


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


def task_summary(task: dict, company: str, lang: str, *, compact: bool = True) -> None:
    """Render saved values only; scoring and persistence remain in their modules."""
    title = task['card'].get('title') or tr(lang, 'need_clarify')
    result = task['card'].get('result') or tr(lang, 'need_clarify')
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
