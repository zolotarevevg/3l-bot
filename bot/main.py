"""Один проход бота: 1) разобрать нажатия кнопок, 2) забрать новые новости и прислать карточки.

Запуск: python -m bot.main            - обычный проход
        python -m bot.main check      - проверить все ленты и прислать отчёт (этап 0)
"""
import datetime as dt
import difflib
import json
import os
import sys
import time
import traceback
import urllib.parse

from . import claude, config, feeds, notion, spotify, state as st, telegram as tg
from .telegram import esc

KIND_RU = {"single": "новый трек", "album": "альбом", "ep": "EP", "video": "клип", "tour": "тур",
           "news": "новость", "review": "рецензия", "interview": "интервью", "other": "разное"}
RELEASE_KINDS = {"single", "album", "ep", "video", "review"}


# ---------- карточки ----------

def listen_line(item):
    links = dict(item.get("listen", {}))
    if not any(k in links for k in ("YouTube",)):
        q = " ".join(x for x in (item.get("artist"), item.get("release")) if x) or item["title"]
        links["YouTube (поиск)"] = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)
    return " · ".join(f'<a href="{esc(u)}">{esc(k)}</a>' for k, u in links.items())


def card_text(item):
    artist, release = item.get("artist"), item.get("release")
    if artist:
        head = f"<b>{esc(artist)}</b>" + (f" - «{esc(release)}»" if release else "")
    else:
        head = f"<b>{esc(item['title'])}</b>"
    tags = [esc(item["source"]), KIND_RU.get(item.get("kind"), "новость")]
    if item.get("russian"):
        tags.append("Lost In Russia")
    if item.get("major"):
        tags.append("важное")
    lines = [head, f"<i>{' · '.join(tags)}</i>", ""]
    if item.get("summary_ru"):
        lines += [esc(item["summary_ru"]), ""]
    if artist:
        lines.append(f"<i>{esc(item['title'])}</i>")
    if item.get("also"):
        lines.append("Ещё пишут: " + ", ".join(f'<a href="{esc(a["link"])}">{esc(a["source"])}</a>' for a in item["also"]))
    lines.append("Слушать: " + listen_line(item))
    lines.append(f'<a href="{esc(item["link"])}">Оригинал</a> · под 3L: {item.get("fit", "?")}/5')
    if item.get("status_line"):
        lines += ["", item["status_line"]]
    return "\n".join(lines)


def card_buttons(item):
    if item.get("status") in ("new", None):
        return [[{"text": "Нужна", "callback_data": f"y:{item['id']}"},
                 {"text": "Мимо", "callback_data": f"n:{item['id']}"}]]
    if item.get("status") == "error":
        return [[{"text": "Повторить", "callback_data": f"y:{item['id']}"}]]
    return []


def preview_for(item):
    return item.get("listen", {}).get("YouTube") or item.get("listen", {}).get("Spotify")


def refresh_card(item):
    if item.get("msg_id"):
        tg.edit(item["msg_id"], card_text(item), card_buttons(item), preview_for(item))


# ---------- дубли ----------

def find_duplicate(state, item):
    now = time.time()
    a, r = spotify.norm(item.get("artist")), spotify.norm(item.get("release"))
    t = spotify.norm(item["title"])
    for other in state["items"].values():
        age = now - other.get("ts", 0)
        if age > config.DEDUP_DAYS * 86400 or other["id"] == item["id"]:
            continue
        oa, orl = spotify.norm(other.get("artist")), spotify.norm(other.get("release"))
        if a and a == oa:
            if r and r == orl:
                return other
            if not r and not orl and other.get("kind") == item.get("kind") and age < 3 * 86400:
                return other
        if age < 7 * 86400 and difflib.SequenceMatcher(None, t, spotify.norm(other["title"])).ratio() > 0.85:
            return other
    return None


# ---------- новые новости ----------

def poll_feeds(state):
    sent = 0
    health = state.setdefault("health", {})
    for source in feeds.load_sources():
        name = source["name"]
        try:
            entries = feeds.fetch(source)
            health[name] = {"ok": int(time.time()), "err": "", "count": len(entries)}
        except Exception as e:
            h = health.setdefault(name, {})
            h["err"] = f"{type(e).__name__}: {e}"[:200]
            h["err_ts"] = int(time.time())
            print(f"[feed] {name}: {h['err']}")
            continue

        if name not in state["sources_init"]:   # первый раз: всё текущее считаем увиденным, не спамим
            for e in entries:
                state["seen"][e["id"]] = time.time()
            state["sources_init"].append(name)
            print(f"[feed] {name}: подключён, {len(entries)} записей помечено как увиденные")
            continue

        fresh = [e for e in entries if e["id"] not in state["seen"]]
        fresh.sort(key=lambda e: e["ts"])
        for e in fresh[-config.MAX_NEW_PER_SOURCE:]:
            if sent >= config.MAX_CARDS_PER_RUN:
                return sent  # остальное заберём в следующий проход
            state["seen"][e["id"]] = time.time()
            if not feeds.passes_filters(e, source):
                continue
            sent += handle_entry(state, e)
        for e in fresh[:-config.MAX_NEW_PER_SOURCE]:
            state["seen"][e["id"]] = time.time()
    return sent


def handle_entry(state, e):
    try:
        info = claude.analyze(e)
    except Exception as ex:
        print(f"[claude] разбор не удался: {ex}")
        info = {"is_music": True, "kind": "news", "artist": "", "release": "",
                "summary_ru": "", "fit": config.MIN_FIT, "why": "без разбора"}
    fit = int(info.get("fit", 0) or 0)
    if not info.get("is_music", True) or fit < config.MIN_FIT:
        return 0
    # синглы, альбомы, клипы и рецензии - всегда; прочие новости - только крупные
    if info.get("kind") not in RELEASE_KINDS and not (info.get("major") and fit >= 3):
        return 0

    item = {"id": e["id"], "source": e["source"], "title": e["title"], "link": e["link"],
            "summary_en": e["summary"][:3000], "ts": time.time(), "status": "new",
            "kind": info.get("kind", "news"), "artist": info.get("artist", ""),
            "release": info.get("release", ""), "summary_ru": info.get("summary_ru", ""),
            "fit": info.get("fit"), "why": info.get("why", ""), "also": [],
            "major": bool(info.get("major")), "russian": bool(info.get("russian")),
            "listen": feeds.listen_links(e["html"])}

    dup = find_duplicate(state, item)
    if dup:
        if all(a["source"] != item["source"] for a in dup["also"]) and dup["source"] != item["source"]:
            dup["also"].append({"source": item["source"], "link": item["link"]})
            for k, v in item["listen"].items():
                dup.setdefault("listen", {}).setdefault(k, v)
            try:
                refresh_card(dup)
            except Exception as ex:
                print(f"[tg] не обновил карточку: {ex}")
        return 0

    if "Spotify" not in item["listen"] and spotify.enabled() and item["artist"]:
        try:
            t = spotify.find(item["artist"], item["release"], item["kind"])
            if t:
                item["listen"]["Spotify"] = t["url"]
        except Exception as ex:
            print(f"[spotify] поиск: {ex}")

    msg = tg.send(card_text(item), card_buttons(item), preview_for(item))
    item["msg_id"] = msg["message_id"]
    state["items"][item["id"]] = item
    return 1


# ---------- кнопки и команды ----------

def process_updates(state):
    updates = []
    payload = event_payload()
    if payload:
        updates.append(payload)
    try:
        updates += tg.get_updates(state["tg_offset"] + 1 if state["tg_offset"] else 0)
    except tg.TelegramError as e:
        if "409" not in str(e):  # 409 = включён вебхук (вариант с реле), тогда апдейты приходят через payload
            raise
    seen_ids = set()
    for u in updates:
        uid_ = u.get("update_id", 0)
        if uid_ in seen_ids or (uid_ and uid_ <= state.get("tg_done", 0)):
            continue
        seen_ids.add(uid_)
        state["tg_offset"] = max(state["tg_offset"], uid_)
        try:
            handle_update(state, u)
        except Exception:
            traceback.print_exc()
        state["tg_done"] = max(state.get("tg_done", 0), uid_)


def event_payload():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or os.environ.get("GITHUB_EVENT_NAME") != "repository_dispatch":
        return None
    try:
        return json.load(open(path)).get("client_payload", {}).get("update")
    except Exception:
        return None


def handle_update(state, u):
    if "message" in u:
        m = u["message"]
        chat = str(m["chat"]["id"])
        if not config.TG_CHAT_ID:
            print(f"[setup] chat id: {chat}")
            return
        if chat != str(config.TG_CHAT_ID):
            return
        text = (m.get("text") or "").strip()
        if text.startswith("/start"):
            tg.send(f"Бот 3L на связи. Твой chat id: <code>{chat}</code>")
        elif text.startswith("/stats"):
            tg.send(stats_text(state))
        elif text.startswith("/sources"):
            tg.send(sources_text(state))
        return

    q = u.get("callback_query")
    if not q or str(q["from"]["id"]) != str(config.TG_CHAT_ID):
        return
    action, _, item_id = (q.get("data") or "").partition(":")
    item = state["items"].get(item_id)
    if not item:
        tg.answer_callback(q["id"], "Эта новость уже вышла из памяти бота")
        return
    if action == "n":
        tg.answer_callback(q["id"], "Мимо")
        item["status"] = "skipped"
        item["status_line"] = "Мимо"
        refresh_card(item)
    elif action == "y" and item.get("status") in ("new", "error"):
        tg.answer_callback(q["id"], "Принято, готовлю черновик")
        like(state, item)


def like(state, item):
    item["status"] = "processing"
    item["status_line"] = "Нужна · готовлю черновик…"
    refresh_card(item)
    report, problems = [], []

    # 1. Spotify
    track = playlist = None
    if spotify.enabled():
        try:
            track = spotify.find(item.get("artist"), item.get("release"), item.get("kind"),
                                 url_hint=item.get("listen", {}).get("Spotify"))
            if track:
                playlist = spotify.month_playlist(state, series="lir" if item.get("russian") else "sessions")
                res = spotify.add_to_playlist(playlist["id"], track["uri"])
                report.append(f'«{esc(playlist["name"])}»: {esc(track["name"])}'
                              + (" (уже был)" if res == "already" else "") + (f" - {esc(track['note'])}" if track["note"] else ""))
            else:
                problems.append("трек в Spotify не нашёлся - добавь руками")
        except Exception as e:
            problems.append(f"Spotify: {esc(str(e)[:150])}")

    # 2. Оригинал и черновик
    original = feeds.article_text(item["link"], item.get("summary_en", ""))
    try:
        draft = claude.write_draft(item, original)
    except Exception as e:
        draft = {"format": "", "vk": "", "telegram": "", "check": []}
        problems.append(f"черновик не написан: {esc(str(e)[:150])}")

    # 3. Notion
    page_url = None
    if notion.enabled():
        try:
            page_url = notion.create_entry(item, draft, original, track, playlist)
        except Exception as e:
            problems.append(f"Notion: {esc(str(e)[:150])}")

    # 4. Ответ в чат
    parts = []
    if draft.get("vk"):
        parts += [f"<b>Черновик · {esc(draft.get('format') or 'пост')} · ВК</b>", esc(draft["vk"]), ""]
    if draft.get("telegram"):
        parts += ["<b>Telegram</b>", esc(draft["telegram"]), ""]
    if draft.get("threads"):
        parts += ["<b>Threads</b>", esc(draft["threads"]), ""]
    if draft.get("check"):
        parts += ["<b>Проверить:</b> " + esc("; ".join(draft["check"])), ""]
    if report:
        parts.append("Плейлист: " + "; ".join(report))
    if page_url:
        parts.append(f'<a href="{esc(page_url)}">Открыть в Notion</a> (там же английский оригинал и все ссылки)')
    if problems:
        parts.append("Не получилось: " + "; ".join(problems))
    tg.send_long("\n".join(parts), reply_to=item.get("msg_id"))

    ok = bool(draft.get("vk")) and (page_url or not notion.enabled())
    item["status"] = "done" if ok else "error"
    item["status_line"] = "Нужна · черновик готов" if ok else "Нужна · с ошибками, можно повторить"
    refresh_card(item)


def stats_text(state):
    week = time.time() - 7 * 86400
    items = [i for i in state["items"].values() if i.get("ts", 0) > week]
    by = lambda s: sum(1 for i in items if i.get("status") == s)
    src = {}
    for i in items:
        if i.get("status") == "done":
            src[i["source"]] = src.get(i["source"], 0) + 1
    top = ", ".join(f"{k} ({v})" for k, v in sorted(src.items(), key=lambda x: -x[1])[:5]) or "-"
    return (f"<b>За 7 дней</b>\nКарточек: {len(items)}\nНужна: {by('done')}\nМимо: {by('skipped')}\n"
            f"Без ответа: {by('new')}\nЧаще берёшь из: {esc(top)}")


def sources_text(state):
    lines = ["<b>Источники</b>"]
    for s in feeds.load_sources():
        h = state.get("health", {}).get(s["name"], {})
        if h.get("err") and h.get("err_ts", 0) >= h.get("ok", 0):
            lines.append(f"✗ {esc(s['name'])}: {esc(h['err'][:80])}")
        elif h.get("ok"):
            lines.append(f"✓ {esc(s['name'])}")
        else:
            lines.append(f"· {esc(s['name'])}: ещё не проверялся")
    return "\n".join(lines)


# ---------- этап 0: проверка лент ----------

def check_feeds():
    lines = []
    for s in json.loads(config.SOURCES_FILE.read_text("utf-8"))["sources"]:
        try:
            entries = feeds.fetch(s)
            newest = max((e["ts"] for e in entries), default=0)
            age = (time.time() - newest) / 86400 if newest else None
            lines.append(f"✓ {s['name']}: {len(entries)} записей, свежая {age:.1f} дн. назад" if age is not None
                         else f"? {s['name']}: {len(entries)} записей без дат")
        except Exception as e:
            lines.append(f"✗ {s['name']}: {type(e).__name__}: {str(e)[:100]}")
    text = "Проверка лент с сервера GitHub:\n" + "\n".join(lines)
    print(text)
    if config.TG_TOKEN and config.TG_CHAT_ID:
        tg.send_long(esc(text))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check_feeds()
        return
    state = st.load()
    try:
        process_updates(state)
        if config.TG_CHAT_ID:
            n = poll_feeds(state)
            print(f"[run] карточек отправлено: {n}")
    finally:
        state["heartbeat"] = dt.date.today().isoformat()
        st.save(state)


if __name__ == "__main__":
    main()
