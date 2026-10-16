"""Минимальный клиент Telegram Bot API без фреймворков."""
import html
import requests

from . import config

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def call(method, **params):
    r = requests.post(API.format(token=config.TG_TOKEN, method=method), json=params, timeout=30)
    data = r.json()
    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('error_code')} {data.get('description')}")
    return data["result"]


def esc(text):
    return html.escape(text or "", quote=False)


def send(text, buttons=None, preview_url=None, reply_to=None):
    params = {"chat_id": config.TG_CHAT_ID, "text": text[:4096], "parse_mode": "HTML"}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    if preview_url:
        params["link_preview_options"] = {"url": preview_url, "prefer_small_media": True}
    else:
        params["link_preview_options"] = {"is_disabled": True}
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    return call("sendMessage", **params)


def edit(message_id, text, buttons=None, preview_url=None):
    params = {"chat_id": config.TG_CHAT_ID, "message_id": message_id,
              "text": text[:4096], "parse_mode": "HTML",
              "reply_markup": {"inline_keyboard": buttons or []}}
    params["link_preview_options"] = ({"url": preview_url, "prefer_small_media": True}
                                      if preview_url else {"is_disabled": True})
    try:
        return call("editMessageText", **params)
    except TelegramError as e:
        if "not modified" in str(e):
            return None
        raise


def answer_callback(callback_id, text=""):
    try:
        call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except TelegramError:
        pass  # кнопку нажали давно - Telegram уже не принимает ответ, это нормально


def get_updates(offset):
    return call("getUpdates", offset=offset, timeout=0,
                allowed_updates=["callback_query", "message"])


def send_long(text, reply_to=None):
    """Длинный текст частями по 4000 символов."""
    chunks, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > 4000:
            chunks.append(buf)
            buf = ""
        buf += para + "\n"
    if buf.strip():
        chunks.append(buf)
    for i, ch in enumerate(chunks):
        send(ch, reply_to=reply_to if i == 0 else None)
