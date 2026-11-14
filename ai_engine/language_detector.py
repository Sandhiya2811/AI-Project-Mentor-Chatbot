"""Cheap, offline language hints. The LLM does the real multilingual work; this tells it what to expect."""
from __future__ import annotations

import re
from dataclasses import dataclass

SCRIPTS = [
    ("Tamil", 0x0B80, 0x0BFF), ("Hindi (Devanagari)", 0x0900, 0x097F), ("Telugu", 0x0C00, 0x0C7F),
    ("Kannada", 0x0C80, 0x0CFF), ("Malayalam", 0x0D00, 0x0D7F), ("Bengali", 0x0980, 0x09FF),
    ("Gujarati", 0x0A80, 0x0AFF), ("Punjabi", 0x0A00, 0x0A7F), ("Arabic", 0x0600, 0x06FF),
    ("Chinese", 0x4E00, 0x9FFF), ("Japanese", 0x3040, 0x30FF), ("Korean", 0xAC00, 0xD7AF),
    ("Russian (Cyrillic)", 0x0400, 0x04FF), ("Thai", 0x0E00, 0x0E7F),
]
TANGLISH = {"enakku", "puriyala", "puriyudhu", "purila", "pannunga", "panna", "pannanum", "pannu", "illa", "illai",
            "seri", "epdi", "eppadi", "enna", "venum", "vendam", "theriyala", "theriyum", "vanakkam", "nandri",
            "sollunga", "sollu", "ennoda", "unga", "ungalukku", "naan", "nan", "irukku", "iruku", "aachu", "aagala",
            "mudiyala", "mudiyum", "evlo", "yenna", "enga", "inga", "romba", "konjam", "oru", "panren", "pannren",
            "kudunga", "kodunga", "paarunga", "ippo", "appuram", "ean", "edhuku", "ethuku", "sema", "da", "machan"}
HINGLISH = {"mujhe", "kaise", "samajh", "samjhao", "nahi", "nahin", "karna", "kya", "batao", "bataiye", "hai", "hain",
            "mera", "meri", "karo", "kijiye", "chahiye", "aap", "tum", "kaun", "kyun", "kyu", "accha", "theek", "abhi",
            "wala", "wali", "bhai", "yaar"}


@dataclass
class LangInfo:
    name: str
    script: str
    mixed: bool

    def hint(self) -> str:
        extra = " The message mixes English with that language." if self.mixed else ""
        return f"Detected: {self.name} (script: {self.script}).{extra}"


def detect(text: str) -> LangInfo:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return LangInfo("unknown", "none", False)
    counts: dict[str, int] = {}
    latin = 0
    for ch in letters:
        cp = ord(ch)
        if cp < 0x250:
            latin += 1
            continue
        for name, lo, hi in SCRIPTS:
            if lo <= cp <= hi:
                counts[name] = counts.get(name, 0) + 1
                break
    total = len(letters)
    if counts:
        top, n = max(counts.items(), key=lambda kv: kv[1])
        if n / total > 0.15:
            return LangInfo(top.split(" (")[0], top, mixed=latin / total > 0.25)
    words = re.findall(r"[a-z']+", text.lower())
    if words:
        ta = sum(w in TANGLISH for w in words)
        hi = sum(w in HINGLISH for w in words)
        if ta >= 2 and ta / len(words) >= 0.12 and ta >= hi:
            return LangInfo("Tanglish", "Latin (Tamil written in English letters)", True)
        if hi >= 2 and hi / len(words) >= 0.12:
            return LangInfo("Hinglish", "Latin (Hindi written in English letters)", True)
    return LangInfo("English or another Latin-script language", "Latin", False)


def reply_language_instruction(info: LangInfo, preferred: str) -> str:
    if preferred and preferred != "Auto-detect":
        return (f"The student's preferred language is {preferred}. Reply in {preferred} unless they clearly "
                f"switch language. {info.hint()}")
    return ("Reply in the same language and style the student used in their latest message (including Tanglish / "
            f"Hinglish / mixed language). {info.hint()}")
