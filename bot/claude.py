"""Вызовы Claude API: разбор новости (быстрая модель) и черновик поста (сильная модель)."""
import json
import re

import requests

from . import config

URL = "https://api.anthropic.com/v1/messages"


def ask(model, system, user, max_tokens=1500):
    r = requests.post(URL, timeout=120, headers={
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json={
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    })
    if r.status_code != 200:
        raise RuntimeError(f"Claude {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json()["content"])


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Claude вернул не JSON: " + text[:200])
    return json.loads(m.group(0))


def prompt(name):
    return (config.PROMPTS / name).read_text("utf-8")


ANALYZE_SYSTEM = """Ты помощник музыкального куратора паблика 3L / Look Listen Love.
Тебе дают одну запись из RSS музыкального издания. Верни ТОЛЬКО JSON без пояснений:
{
 "is_music": true/false,          // музыкальная новость/релиз/рецензия (не игры, не кино, не мерч, не гайды)
 "kind": "single|album|ep|video|tour|news|review|interview|other",
 "artist": "основной артист или группа, как в оригинале",
 "release": "название трека/альбома без кавычек, иначе пусто",
 "summary_ru": "1-2 предложения по-русски: только факты из записи (что вышло, когда, на каком лейбле, кто участвует). Сольных артистов писать кириллицей, группы - латиницей. Дефис с пробелами вместо длинного тире.",
 "fit": 1-5,                      // насколько под вкус 3L (описание ниже)
 "major": true/false,             // крупная новость: воссоединение известной группы, большое возвращение, распад, смерть значимого музыканта, громкий анонс
 "russian": true/false,           // русскоязычный / российский или белорусский артист (для рубрики Lost In Russia)
 "why": "до 8 слов, почему такая оценка"
}
Если запись из Telegram-канала содержит несколько релизов (дайджест) - возьми главный и упомяни остальные в summary_ru.
Вкус 3L:
""" + "{taste}"


def analyze(entry):
    system = ANALYZE_SYSTEM.replace("{taste}", prompt("taste_3l.md"))
    user = (f"Издание: {entry['source']}\nЗаголовок: {entry['title']}\n"
            f"Рубрики: {', '.join(entry.get('tags', []))}\n"
            f"Текст: {entry['summary'][:1800]}")
    return parse_json(ask(config.MODEL_FAST, system, user, max_tokens=500))


def write_draft(item, article_text):
    system = prompt("style_3l.md")
    user = f"""Напиши черновик поста 3L по этой новости.

Факты:
- Артист: {item.get('artist')}
- Релиз: {item.get('release') or '-'} ({item.get('kind')})
- Источник: {item.get('source')} {item.get('link')}
- Российская сцена (Lost In Russia): {'да' if item.get('russian') else 'нет'}
- Также писали: {', '.join(a['source'] for a in item.get('also', [])) or '-'}

Оригинальный текст статьи (английский):
\"\"\"
{article_text[:9000]}
\"\"\"

Верни ТОЛЬКО JSON:
{{
 "format": "Короткий пост|Новость о сингле|Альбом недели|Личный пост",
 "vk": "текст для ВК",
 "telegram": "текст для Telegram-канала - своя первая строка, чуть короче",
 "threads": "реплика для Threads до 400 знаков: одна мысль, разговорнее, без ссылок",
 "check": ["факты, которые надо проверить, если есть сомнения"]
}}"""
    return parse_json(ask(config.MODEL_WRITER, system, user, max_tokens=2500))
