"""Per-message language detection. Nothing here is a setting: every student message is analysed on its own.

The LLM does the real multilingual understanding; this module gives it a reliable hint (script, Tanglish/Hinglish,
an explicit "explain in Tamil" request, and the language used just before for very short messages like "ok").
"""
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
TANGLISH = {"enakku", "puriyala", "puriyudhu", "purila", "puriyuthu", "pannunga", "panna", "pannanum", "pannu", "pannunga",
            "illa", "illai", "seri", "epdi", "eppadi", "enna", "venum", "vendam", "theriyala", "theriyum", "vanakkam",
            "nandri", "sollunga", "sollu", "solli", "soliruka", "solliruka", "ennoda", "unga", "ungalukku", "naan", "nan",
            "irukku", "iruku", "aachu", "aagala", "mudiyala", "mudiyum", "evlo", "yenna", "enga", "inga", "romba", "konjam",
            "oru", "panren", "pannren", "kudunga", "kodunga", "paarunga", "ippo", "appuram", "edhuku", "ethuku", "sema",
            "machan", "polam", "pogalam", "pogalama", "ku", "kku", "pannalam", "pannalama", "pannuvom", "pannuvoma", "ennalam", "ennenna", "podhum", "pothum", "vaanga", "ponga", "theriyuma", "puriyum",
            "ellam", "ella", "adutha", "aduthu", "mela", "kela", "enakkum", "nalla", "sariya", "thappa", "vandhuchu"}
HINGLISH = {"mujhe", "kaise", "samajh", "samjhao", "nahi", "nahin", "karna", "kya", "batao", "bataiye", "hai", "hain",
            "mera", "meri", "karo", "kijiye", "chahiye", "aap", "tum", "kaun", "kyun", "kyu", "accha", "theek", "abhi",
            "wala", "wali", "bhai", "yaar", "agla", "pichla", "kaam"}
TELUGLISH = {"naaku", "ardham", "ayyindi", "cheppu", "cheppandi", "ela", "enti", "kavali", "ledu", "undi", "chesanu"}
MALAYALISH = {"enikku", "manasilayilla", "parayu", "engane", "entha", "venam", "illa", "cheyyam", "athu"}
KANNADIGLISH = {"nanage", "artha", "gottilla", "heli", "hege", "enu", "beku", "illa", "madi"}
LATIN_VARIANTS = [("Tanglish", "Latin (Tamil written in English letters)", TANGLISH),
                  ("Hinglish", "Latin (Hindi written in English letters)", HINGLISH),
                  ("Telugu (romanised)", "Latin (Telugu written in English letters)", TELUGLISH),
                  ("Malayalam (romanised)", "Latin (Malayalam written in English letters)", MALAYALISH),
                  ("Kannada (romanised)", "Latin (Kannada written in English letters)", KANNADIGLISH)]

_NAMES = ("tamil|hindi|telugu|malayalam|kannada|english|tanglish|hinglish|bengali|marathi|gujarati|punjabi|urdu|"
          "spanish|french|german|arabic|chinese|japanese|korean|russian|portuguese|italian")
_NATIVE = {"தமிழ": "Tamil", "हिंदी": "Hindi", "हिन्दी": "Hindi", "తెలుగు": "Telugu", "മലയാളം": "Malayalam",
           "ಕನ್ನಡ": "Kannada", "ইংরেজি": "English", "English": "English"}
EXPLICIT = re.compile(rf"(?:\b(?:in|into|to|using)\s+({_NAMES})\b|\b({_NAMES})\s*(?:la|il|le|mein|me|lo|ilo|alli|ല്‍|ൽ)\b|"
                      rf"\b({_NAMES})\s+(?:ah|a)?\s*(?:solu|sollu|explain|vilakkam|batao|cheppu))", re.I)


@dataclass
class LangInfo:
    name: str
    script: str
    mixed: bool
    requested: str = ""   # language the student explicitly asked for ("explain in Tamil")

    def hint(self) -> str:
        extra = " The message mixes English with that language." if self.mixed else ""
        return f"Detected: {self.name} (script: {self.script}).{extra}"


def _explicit_request(text: str) -> str:
    m = EXPLICIT.search(text)
    if m:
        return next(g for g in m.groups() if g).capitalize()
    for native, name in _NATIVE.items():
        if native in text and len(text.split()) >= 2 and native != "English":
            return name
    return ""


def detect(text: str) -> LangInfo:
    requested = _explicit_request(text)
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return LangInfo("unknown", "none", False, requested)
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
            return LangInfo(top.split(" (")[0], top, latin / total > 0.25, requested)
    words = re.findall(r"[a-z']+", text.lower())
    if words:
        best = max(((sum(w in vocab for w in words), name, script) for name, script, vocab in LATIN_VARIANTS),
                   key=lambda t: t[0])
        hits, name, script = best
        ratio = hits / len(words)
        if (hits >= 2 and ratio >= 0.12) or (hits >= 1 and ratio >= 0.30):
            return LangInfo(name, script, True, requested)
    return LangInfo("English or another Latin-script language", "Latin", False, requested)


def reply_language_instruction(info: LangInfo, preferred: str = "", recent: str = "") -> str:
    """Rule for THIS reply. `preferred` is accepted for backwards compatibility and ignored: language is never a setting."""
    rule = ("Reply in the language and style of the student's LATEST message (Tamil, Tanglish, Hindi, Telugu, Malayalam, "
            "Kannada, English, mixed - whatever they wrote), switching immediately if they switch. Keep programming terms, "
            "library names and error names in English. Explain in simple beginner-friendly words.")
    if info.requested:
        rule = (f"The student explicitly asked for {info.requested}: reply in {info.requested} (keep technical terms in "
                f"English) until they ask for another language. ") + rule
    elif recent and info.name.startswith(("English", "unknown")):
        rule += (f" If the latest message is too short to tell (e.g. 'ok'), continue in the language used just before: {recent}.")
    return f"{rule} Hint (heuristic, may be wrong): {info.hint()}"
