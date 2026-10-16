"""Настройки бота. Секреты берутся из переменных окружения (GitHub Secrets)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "state.json"
SOURCES_FILE = ROOT / "sources.json"
PROMPTS = ROOT / "prompts"


def env(name, default=""):
    return os.environ.get(name, "").strip() or default


# Telegram
TG_TOKEN = env("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = env("TELEGRAM_CHAT_ID")  # твой личный chat id

# Claude
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
MODEL_FAST = env("CLAUDE_MODEL_FAST", "claude-haiku-5-5")      # разбор новостей
MODEL_WRITER = env("CLAUDE_MODEL_WRITER", "claude-sonnet-5-5")  # черновики постов

# Spotify
SPOTIFY_CLIENT_ID = env("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = env("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REFRESH_TOKEN = env("SPOTIFY_REFRESH_TOKEN")
PLAYLIST_NAME = env("PLAYLIST_NAME", "Сейшнс · черновик · {month} {year}")
PLAYLIST_NAME_LIR = env("PLAYLIST_NAME_LIR", "Lost In Russia · черновик · {month} {year}")

# Notion
NOTION_TOKEN = env("NOTION_TOKEN")
NOTION_DATABASE_ID = env("NOTION_DATABASE_ID", "dcbec872f3894046a43507262fc11f66")

# Поведение
MIN_FIT = int(env("MIN_FIT", "2"))                 # порог «под вкус 3L», 1-5 (2 = по максимуму)
MAX_CARDS_PER_RUN = int(env("MAX_CARDS_PER_RUN", "25"))
MAX_NEW_PER_SOURCE = int(env("MAX_NEW_PER_SOURCE", "15"))
DEDUP_DAYS = int(env("DEDUP_DAYS", "30"))
KEEP_DAYS = int(env("KEEP_DAYS", "45"))
TIMEZONE = env("BOT_TZ", "Europe/Lisbon")

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
             "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
