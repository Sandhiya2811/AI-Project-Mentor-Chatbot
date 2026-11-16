"""Builds the message window sent to the LLM from SQLite (the DB is the memory)."""
from __future__ import annotations

from database import repository as repo
from utils.helpers import truncate


def build_history(conversation_id: int, max_messages: int = 8, max_chars: int = 3500) -> list[dict]:
    msgs = repo.list_messages(conversation_id, limit=max_messages)
    out: list[dict] = []
    budget = max_chars
    for m in reversed(msgs):  # newest first so recent turns survive the character budget
        if m["role"] not in ("user", "assistant"):
            continue
        # review reports are long and the latest one is already in the system prompt -> keep only a stub
        content = truncate(m["content"], 400 if m["kind"] == "review" else 1500)
        if budget - len(content) < 0 and out:
            break
        budget -= len(content)
        out.append({"role": m["role"], "content": content})
    out.reverse()
    while out and out[0]["role"] != "user":  # some providers require starting with a user turn
        out.pop(0)
    return out
