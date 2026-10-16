"""Память бота между запусками: data/state.json (коммитится в репозиторий)."""
import json
import time

from . import config

EMPTY = {"tg_offset": 0, "heartbeat": "", "seen": {}, "items": {}, "playlists": {}, "sources_init": []}


def load():
    if config.STATE_FILE.exists():
        data = json.loads(config.STATE_FILE.read_text("utf-8"))
        for k, v in EMPTY.items():
            data.setdefault(k, v if not isinstance(v, (dict, list)) else type(v)())
        return data
    return json.loads(json.dumps(EMPTY))


def save(state):
    prune(state)
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


def prune(state):
    cutoff = time.time() - config.KEEP_DAYS * 86400
    state["seen"] = {k: t for k, t in state["seen"].items() if t > cutoff}
    state["items"] = {k: v for k, v in state["items"].items()
                      if v.get("ts", 0) > cutoff or v.get("status") == "processing"}
