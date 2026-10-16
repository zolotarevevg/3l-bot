"""Забор RSS: загрузка, разбор, ссылки «послушать», полный текст статьи."""
import hashlib
import html
import json
import re
import time

import feedparser
import requests

from . import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 3L-bot/1.0")

LISTEN_PATTERNS = {
    "Spotify": r"https?://open\.spotify\.com/(?:intl-\w+/)?(?:track|album)/[A-Za-z0-9]+",
    "YouTube": r"https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)[\w-]{11}",
    "Bandcamp": r"https?://[\w-]+\.bandcamp\.com/(?:track|album)/[\w-]+",
    "SoundCloud": r"https?://soundcloud\.com/[\w-]+/[\w-]+",
    "song.link": r"https?://(?:song|album)\.link/[\w/-]+",
    "band.link": r"https?://band\.link/[\w-]+",
    "Яндекс Музыка": r"https?://music\.yandex\.(?:ru|com)/(?:album|track)/[\d/a-z]+",
    "VK Музыка": r"https?://(?:vk\.com|vk\.ru)/(?:music/(?:album|playlist)/[\w-]+|audio[-\d_]+)",
}


def load_sources():
    data = json.loads(config.SOURCES_FILE.read_text("utf-8"))
    return [s for s in data["sources"] if s.get("enabled")]


def uid(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def strip_html(text):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch(source):
    if source.get("type") == "telegram":
        return fetch_telegram(source)
    r = requests.get(source["url"], headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"},
                     timeout=25)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if not feed.entries and feed.bozo:
        raise ValueError(f"не разобрать ленту: {feed.bozo_exception}")
    entries = []
    for e in feed.entries:
        link = e.get("link") or ""
        raw_html = ""
        if e.get("content"):
            raw_html = " ".join(c.get("value", "") for c in e.content)
        raw_html = raw_html or e.get("summary", "")
        published = e.get("published_parsed") or e.get("updated_parsed")
        entries.append({
            "id": uid(e.get("id") or link or e.get("title", "")),
            "source": source["name"],
            "title": strip_html(e.get("title", "")),
            "link": link,
            "summary": strip_html(raw_html),
            "html": raw_html,
            "tags": [t.get("term", "") for t in e.get("tags", []) if t.get("term")],
            "ts": time.mktime(published) if published else time.time(),
        })
    return entries


def fetch_telegram(source):
    """Публичный Telegram-канал через веб-превью t.me/s/<канал>."""
    channel = source["channel"].lstrip("@")
    r = requests.get(f"https://t.me/s/{channel}", headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    entries = []
    for chunk in r.text.split('data-post="')[1:]:
        post_id = chunk.split('"', 1)[0]
        body = chunk.split('data-post="', 1)[0]
        m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', body, re.S)
        if not m:
            continue
        raw = m.group(1)
        text = strip_html(raw.replace("<br/>", "\n").replace("<br>", "\n"))
        if len(text) < 25:
            continue
        lines = [l.strip() for l in re.sub(r"<br\s*/?>", "\n", raw).split("\n")]
        first = strip_html(next((l for l in lines if strip_html(l)), text))[:140]
        t = re.search(r'<time datetime="([^"]+)"', body)
        ts = time.time()
        if t:
            try:
                ts = __import__("datetime").datetime.fromisoformat(t.group(1)).timestamp()
            except ValueError:
                pass
        hrefs = " ".join(re.findall(r'href="([^"]+)"', raw))
        entries.append({
            "id": uid(post_id), "source": source["name"], "title": first,
            "link": f"https://t.me/{post_id}", "summary": text, "html": hrefs + " " + raw,
            "tags": ["telegram"], "ts": ts,
        })
    return entries


def passes_filters(entry, source):
    hay = (entry["title"] + " " + " ".join(entry["tags"])).lower()
    for word in source.get("exclude", []):
        if re.search(r"\b" + re.escape(word.lower()) + r"\b", hay):
            return False
    inc = [c.lower() for c in source.get("include_categories", [])]
    if inc and not any(t.lower() in inc for t in entry["tags"]):
        return False
    return True


def listen_links(html_text):
    found = {}
    for name, pat in LISTEN_PATTERNS.items():
        m = re.search(pat, html_text or "")
        if m:
            found[name] = m.group(0)
    return found


def article_text(url, fallback=""):
    """Полный текст статьи (английский оригинал). Если сайт не отдал - текст из RSS."""
    try:
        import trafilatura
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False,
                                   favor_precision=True)
        if text and len(text) > len(fallback):
            return text
    except Exception:
        pass
    return fallback
