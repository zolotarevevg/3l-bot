"""Spotify: поиск трека и черновой плейлист «Сейшнс» на текущий месяц."""
import base64
import datetime as dt
import re
import unicodedata

import requests

from . import config

API = "https://api.spotify.com/v1"
_token = None


def enabled():
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_REFRESH_TOKEN)


def token():
    global _token
    if _token:
        return _token
    auth = base64.b64encode(f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token", timeout=20,
                      headers={"Authorization": f"Basic {auth}"},
                      data={"grant_type": "refresh_token", "refresh_token": config.SPOTIFY_REFRESH_TOKEN})
    r.raise_for_status()
    _token = r.json()["access_token"]
    return _token


def api(method, path, **kw):
    r = requests.request(method, API + path, timeout=20,
                         headers={"Authorization": f"Bearer {token()}"}, **kw)
    return r


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|feat\..*|ft\..*", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _artist_ok(found_artists, artist):
    a = norm(artist)
    return any(a and (a in norm(x) or norm(x) in a) for x in found_artists)


def find(artist, release, kind="single", url_hint=None):
    """Вернуть {'uri','url','name','note'} или None."""
    if url_hint:
        m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(track|album)/([A-Za-z0-9]+)", url_hint)
        if m and m.group(1) == "track":
            tid = m.group(2)
            r = api("GET", f"/tracks/{tid}")
            if r.ok:
                t = r.json()
                return {"uri": t["uri"], "url": t["external_urls"]["spotify"],
                        "name": f"{t['artists'][0]['name']} - {t['name']}", "note": ""}
        if m and m.group(1) == "album":
            return _first_track_of_album(m.group(2))
    if not artist:
        return None
    if kind in ("album", "ep") and release:
        r = api("GET", "/search", params={"q": f"album:{release} artist:{artist}", "type": "album", "limit": 5})
        if r.ok:
            for al in r.json().get("albums", {}).get("items", []):
                if _artist_ok([a["name"] for a in al["artists"]], artist):
                    return _first_track_of_album(al["id"])
    q = f"track:{release} artist:{artist}" if release else f"artist:{artist}"
    r = api("GET", "/search", params={"q": q, "type": "track", "limit": 10})
    if not r.ok:
        return None
    best = None
    for t in r.json().get("tracks", {}).get("items", []):
        if not _artist_ok([a["name"] for a in t["artists"]], artist):
            continue
        if release and norm(release) not in norm(t["name"]) and norm(t["name"]) not in norm(release):
            continue
        best = t
        break
    if not best:
        return None
    return {"uri": best["uri"], "url": best["external_urls"]["spotify"],
            "name": f"{best['artists'][0]['name']} - {best['name']}",
            "note": "" if release else "релиз не указан - взят первый подходящий трек артиста"}


def _first_track_of_album(album_id):
    r = api("GET", f"/albums/{album_id}/tracks", params={"limit": 1})
    if not r.ok or not r.json().get("items"):
        return None
    t = r.json()["items"][0]
    return {"uri": t["uri"], "url": t["external_urls"]["spotify"],
            "name": f"{t['artists'][0]['name']} - {t['name']}",
            "note": "это альбом: добавлен первый трек, поменяй на нужный вручную"}


def month_playlist(state, series="sessions"):
    now = dt.datetime.now()
    key = now.strftime("%Y-%m") + ("" if series == "sessions" else "-" + series)
    if key in state["playlists"]:
        return state["playlists"][key]
    template = config.PLAYLIST_NAME if series == "sessions" else config.PLAYLIST_NAME_LIR
    name = template.format(month=config.MONTHS_RU[now.month - 1], year=now.year)
    # сначала ищем, вдруг уже создан руками
    r = api("GET", "/me/playlists", params={"limit": 50})
    if r.ok:
        for p in r.json().get("items", []):
            if p and p.get("name") == name:
                state["playlists"][key] = {"id": p["id"], "url": p["external_urls"]["spotify"], "name": name}
                return state["playlists"][key]
    body = {"name": name, "public": False, "description": "Черновик «Сейшнс» - треки, отмеченные в боте 3L."}
    r = api("POST", "/me/playlists", json=body)
    if r.status_code == 404:  # старый адрес эндпоинта
        me = api("GET", "/me").json()
        r = api("POST", f"/users/{me['id']}/playlists", json=body)
    r.raise_for_status()
    p = r.json()
    state["playlists"][key] = {"id": p["id"], "url": p["external_urls"]["spotify"], "name": name}
    return state["playlists"][key]


def add_to_playlist(playlist_id, uri):
    # не добавлять дубль
    r = api("GET", f"/playlists/{playlist_id}/items", params={"limit": 100, "fields": "items(track(uri),item(uri))"})
    if r.status_code == 404:
        r = api("GET", f"/playlists/{playlist_id}/tracks", params={"limit": 100, "fields": "items(track(uri))"})
    if r.ok:
        uris = {(i.get("track") or i.get("item") or {}).get("uri") for i in r.json().get("items", [])}
        if uri in uris:
            return "already"
    r = api("POST", f"/playlists/{playlist_id}/items", json={"uris": [uri]})
    if r.status_code == 404:
        r = api("POST", f"/playlists/{playlist_id}/tracks", json={"uris": [uri]})
    r.raise_for_status()
    return "added"
