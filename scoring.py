"""Disclosed completeness rubric. Points are not a truth or feasibility guarantee."""
import re
from collections import Counter

# key, label, points, group, clarification. Group weights match the brief.
FIELDS = [
    ('context', 'Контекст', 10, 'Контекст и потребность', 'Что происходит сейчас и в чём проблема?'),
    ('need', 'Потребность', 10, 'Контекст и потребность', 'Что именно необходимо изменить?'),
    ('data', 'Данные и материалы', 10, 'Данные и материалы', 'Какие данные, примеры или источники доступны?'),
    ('access', 'Доступ к материалам', 10, 'Данные и материалы', 'Как команда получит материалы? Если они не нужны — объясните почему.'),
    ('result', 'Ожидаемый результат', 15, 'Ожидаемый результат', 'Что конкретно команда должна передать бизнесу?'),
    ('success', 'Критерии успеха', 15, 'Критерии успеха', 'Какие измеримые проверки покажут, что результат принят?'),
    ('constraints', 'Ограничения', 10, 'Ограничения', 'Каковы сроки, технологии и границы работы?'),
    ('users', 'Пользователи', 10, 'Пользователи', 'Кто будет пользоваться решением и в какой ситуации?'),
    ('contact', 'Контакт бизнеса', 4, 'Связь с бизнесом', 'Как связаться с ответственным? Укажите публичный рабочий контакт.'),
    ('interaction', 'Формат консультаций', 3, 'Связь с бизнесом', 'Как и когда бизнес сможет консультировать команду?'),
    ('feedback', 'Порядок обратной связи', 3, 'Связь с бизнесом', 'Кто и в каком порядке проверяет промежуточный результат?'),
]
KEYS = [f[0] for f in FIELDS]
LEVELS = ['Черновик', 'Рабочая', 'Готовая', 'Приоритетная']
THEMES = ['Образование', 'Торговля', 'Логистика', 'Сервисы', 'Аналитика', 'Другое']
PLACEHOLDERS = {'не знаю', 'потом', 'потом уточним', 'нужно уточнить', 'уточнить',
                'нет', 'нет данных', 'не указано', 'тест', 'test', 'todo', 'tbd', 'n a'}


def normalize(value: str) -> str:
    return ' '.join(re.findall(r'\w+', str(value).casefold()))


def informative(value: str, contact: bool = False) -> bool:
    text, norm = str(value).strip(), normalize(value)
    if not norm or norm in PLACEHOLDERS or len(set(norm.replace(' ', ''))) < 3:
        return False
    if contact:
        return bool(re.search(r'@\w{3,}|\S+@\S+\.\S+|\+?\d[\d ()-]{8,}\d|https?://\S+', text))
    return len(text) >= 12 and len(set(norm.split())) >= 3


def level(score: int) -> str:
    if not 0 <= score <= 100:
        raise ValueError('Рейтинг должен быть от 0 до 100.')
    return LEVELS[0 if score < 40 else 1 if score < 70 else 2 if score < 90 else 3]


def score_card(card: dict, confirmed=()) -> dict:
    confirmed = set(confirmed)
    counts = Counter(normalize(card.get(k, '')) for k in KEYS if card.get(k, '').strip())
    groups, missing = {}, []
    for key, label, weight, group, question in FIELDS:
        value = card.get(key, '')
        valid = informative(value, key == 'contact') and counts[normalize(value)] == 1
        points = weight if key in confirmed and valid else 0
        # A formal marker of a check is only an MVP heuristic, not semantic validation.
        if points and key == 'success' and not re.search(r'\d|тест|провер|чек.?лист', value, re.I):
            points = 5
        bucket = groups.setdefault(group, {'Критерий': group, 'Баллы': 0, 'Максимум': 0})
        bucket['Баллы'] += points
        bucket['Максимум'] += weight
        if points < weight:
            reason = ('Нужно подтверждение' if valid and key not in confirmed else
                      'Добавьте проверяемый критерий' if points else 'Уточните поле; не используйте заглушку или дубль')
            missing.append({'field': key, 'label': label, 'gain': weight - points,
                            'question': question, 'reason': reason})
    total = sum(g['Баллы'] for g in groups.values())
    return {'total': total, 'level': level(total), 'groups': list(groups.values()),
            'missing': sorted(missing, key=lambda x: -x['gain'])}
