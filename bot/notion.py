"""Notion: запись в базу «Входящие из бота» (хаб 3L)."""
import datetime as dt

import requests

from . import config

API = "https://api.notion.com/v1"


def enabled():
    return bool(config.NOTION_TOKEN)


def _headers():
    return {"Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Notion-Version": "2022-06-28", "Content-Type": "application/json"}


def _rt(text):
    text = text or ""
    return [{"type": "text", "text": {"content": text[i:i + 2000]}} for i in range(0, min(len(text), 6000), 2000)] or []


def _paragraphs(text):
    blocks = []
    for para in (text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        for i in range(0, len(para), 1900):
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[i:i + 1900]}}]}})
    return blocks


def _h2(text):
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def _link(label, url):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        {"type": "text", "text": {"content": label + ": "}},
        {"type": "text", "text": {"content": url, "link": {"url": url}}}]}}


def create_entry(item, draft, original, spotify_track, playlist):
    title = item.get("artist") or ""
    if item.get("release"):
        title += f" - {item['release']}"
    title = title or item["title"]

    links = [("Оригинал", item["link"])] + [(f"{a['source']}", a["link"]) for a in item.get("also", []) if a.get("link")]
    links += [(k, v) for k, v in item.get("listen", {}).items()]
    if spotify_track:
        links.append(("Spotify (трек)", spotify_track["url"]))
    if playlist:
        links.append((playlist["name"], playlist["url"]))

    props = {
        "Название": {"title": _rt(title)},
        "Статус": {"select": {"name": "Черновик"}},
        "Артист": {"rich_text": _rt(item.get("artist"))},
        "Трек": {"rich_text": _rt(item.get("release"))},
        "Источник": {"select": {"name": item["source"][:100]}},
        "Ещё пишут": {"rich_text": _rt(", ".join(a["source"] for a in item.get("also", [])))},
        "Ссылка на оригинал": {"url": item["link"] or None},
        "Слушать": {"rich_text": _rt(" · ".join(f"{k}: {v}" for k, v in item.get("listen", {}).items()))},
        "Получено": {"date": {"start": dt.datetime.fromtimestamp(item["ts"]).strftime("%Y-%m-%d")}},
    }
    if draft.get("format") in ("Короткий пост", "Новость о сингле", "Альбом недели", "Личный пост"):
        props["Формат"] = {"select": {"name": draft["format"]}}
    if spotify_track:
        props["Spotify"] = {"url": spotify_track["url"]}
    if playlist:
        props["Сейшнс"] = {"rich_text": _rt(f"{playlist['name']} - {spotify_track['name'] if spotify_track else 'трек не найден'}")}
    props["Рубрика"] = {"select": {"name": "Lost In Russia" if item.get("russian") else "Сейшнс"}}

    children = [_h2("Черновик - ВК")] + _paragraphs(draft.get("vk"))
    children += [_h2("Черновик - Telegram")] + _paragraphs(draft.get("telegram"))
    if draft.get("threads"):
        children += [_h2("Черновик - Threads")] + _paragraphs(draft.get("threads"))
    if draft.get("check"):
        children += [_h2("Проверить")] + _paragraphs("\n".join(draft["check"]))
    children += [_h2("Ссылки")] + [_link(l, u) for l, u in links if u]
    children += [_h2("Оригинал (EN)")] + _paragraphs(original)

    r = requests.post(f"{API}/pages", headers=_headers(), timeout=30, json={
        "parent": {"database_id": config.NOTION_DATABASE_ID},
        "properties": props,
        "children": children[:100],
    })
    if not r.ok:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")
    page = r.json()
    rest = children[100:]
    while rest:  # Notion принимает не больше 100 блоков за запрос
        requests.patch(f"{API}/blocks/{page['id']}/children", headers=_headers(), timeout=30,
                       json={"children": rest[:100]})
        rest = rest[100:]
    return page["url"]
