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
TANGLISH |= {"enaku", "namma", "nama", "nammaku", "pannuvom", "panlam", "pannitu", "pannitten", "panniten", "pannunga", "irukka",
             "irukkum", "idhu", "idhula", "adhu", "adhula", "ithu", "athu", "enga", "yaaru", "yeppadi", "eppo", "epo", "ippadi",
             "appadi", "thaan", "dhaan", "than", "naa", "naama", "avanga", "ungaluku", "unakku", "vandhu", "poi", "paaru",
             "paarkalam", "seiyalam", "seyyalam", "seiyanum", "venuma", "vendama", "puriyum", "puriyuthu", "purinjidhu",
             "purinjathu", "purinjiduchu", "theliva", "theliva", "thelivaa", "sollunga", "sollitharen", "solren", "mudinjuthu",
             "mudinjidhu", "mudichiduchu", "mudinchuchu", "irundha", "iruntha", "aana", "aanaa", "illaina", "adhan", "edhukku"}
HINGLISH |= {"mujhe", "mereko", "samjha", "samajhna", "banana", "banao", "karte", "karenge", "karni", "hoga", "hogi", "kaisa",
             "kaisi", "kitna", "kahan", "kab", "sabse", "pehle", "phir", "uske", "iska", "isme", "usme", "lekin", "aur", "toh",
             "chahta", "chahti", "dekho", "dikhao", "bolo", "samajh", "aaya", "gaya", "wahi", "sirf", "bilkul", "zaroor"}
TELUGLISH = {"naaku", "naku", "ardham", "ardhamayyindi", "ayyindi", "cheppu", "cheppandi", "ela", "enti", "emiti", "kavali",
             "kaavali", "ledu", "undi", "chesanu", "cheyali", "cheyyali", "cheddam", "chestanu", "mana", "meeru", "nenu", "idi",
             "adi", "ikkada", "akkada", "tarvata", "taruvata", "modati", "modata", "telusu", "teliyadu", "avunu", "ante", "kani",
             "vachindi", "ravatledu", "cheyochu", "ekkada", "enduku", "yela", "baagundi"}
MALAYALISH = {"enikku", "enik", "manasilayilla", "manassilaayilla", "manasilayi", "parayu", "parayoo", "engane", "entha",
              "enthaanu", "venam", "venamo", "illa", "cheyyam", "cheyyanam", "cheyyaam", "athu", "ithu", "njan", "njaan",
              "ningal", "nammal", "nammude", "aanu", "alle", "aano", "ariyilla", "ariyam", "sheri", "shari", "kollam", "pinne",
              "ippo", "ippol", "pattum", "pattilla", "undu", "ondu", "ente", "ningalude", "enthu", "evide", "ennal"}
KANNADIGLISH = {"nanage", "nange", "artha", "gottilla", "gotthilla", "heli", "helu", "hege", "enu", "beku", "illa", "madi",
                "maadi", "maadona", "madona", "namma", "nimma", "nanu", "naanu", "idu", "adu", "alli", "illi", "yaake", "yavaga",
                "sari", "chennagide", "gottu", "aagide", "aaytu", "maadbeku", "madbeku", "ide"}
LATIN_VARIANTS = [("Tanglish", "Latin (Tamil written in English letters)", TANGLISH),
                  ("Hinglish", "Latin (Hindi written in English letters)", HINGLISH),
                  ("Tenglish", "Latin (Telugu written in English letters)", TELUGLISH),
                  ("Manglish", "Latin (Malayalam written in English letters)", MALAYALISH),
                  ("Kanglish", "Latin (Kannada written in English letters)", KANNADIGLISH)]

# How the reply must LOOK for each language: script and register matter, not only the language name.
STYLE = {
    "Tanglish": "Write in Tanglish: Tamil in English (Latin) letters, naturally mixed with English technical words, the way a "
                "Tamil friend would type. Example: 'Super! Ippo namma Task 2 ku move pannalam.' Do NOT use Tamil script.",
    "Tamil": "Write in Tamil script (தமிழ்) in simple spoken-style Tamil, keeping programming terms in English letters. "
             "Example: 'சூப்பர்! முதலில் project-ன் நோக்கத்தையும் planning-ஐயும் புரிந்துகொள்வோம்.'",
    "Hinglish": "Write in Hinglish: Hindi in English (Latin) letters mixed with English technical words. Example: 'Bilkul! "
                "Sabse pehle hum project ka objective samjhenge.' Do NOT use Devanagari.",
    "Hindi": "Write in Hindi using Devanagari, keeping programming terms in English. Example: 'बिल्कुल! सबसे पहले हम "
             "प्रोजेक्ट का उद्देश्य और उसकी योजना समझेंगे।'",
    "Manglish": "Write in Manglish: Malayalam in English (Latin) letters mixed with English technical words. Example: "
                "'Sheri! Aadyam nammal project-inte objective manassilaakkaam.' Do NOT use Malayalam script.",
    "Malayalam": "Write in Malayalam script, keeping programming terms in English. Example: 'തീർച്ചയായും! ആദ്യം "
                 "നമുക്ക് പ്രോജക്റ്റിന്റെ ലക്ഷ്യവും പ്ലാനിംഗും മനസ്സിലാക്കാം.'",
    "Tenglish": "Write in Tenglish: Telugu in English (Latin) letters mixed with English technical words. Example: 'Sare! "
                "Mundu manam project objective ni ardham chesukundam.' Do NOT use Telugu script.",
    "Telugu": "Write in Telugu script, keeping programming terms in English. Example: 'తప్పకుండా! ముందుగా మనం ప్రాజెక్ట్ "
              "లక్ష్యాన్ని, ప్లానింగ్‌ను అర్థం చేసుకుందాం.'",
    "Kanglish": "Write in Kanglish: Kannada in English (Latin) letters mixed with English technical words. Example: 'Sari! "
                "Modalu namma project objective artha madkolona.' Do NOT use Kannada script.",
    "Kannada": "Write in Kannada script, keeping programming terms in English.",
}

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

    @property
    def reply_name(self) -> str:
        """The language the reply must be in: an explicit request wins over what the message looks like."""
        return self.requested or self.name

    def style(self) -> str:
        return STYLE.get(self.reply_name, "")


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


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", text)


def resolve(text: str, recent: str = "") -> LangInfo:
    """Language of THIS message, keeping the conversation's language for tiny follow-ups.

    "ok", "next task", "why pandas?" carry too little information to prove the student switched language, so in an
    ongoing Tamil/Tanglish/Hindi... conversation they keep that language. A clear sentence in another language switches.
    """
    info = detect(text)
    plain = recent and not recent.lower().startswith(("english", "unknown"))
    if plain and not info.requested and info.name.startswith(("English", "unknown")) and len(_words(text)) <= 3:
        return LangInfo(recent, "inherited from the previous messages", True, "")
    return info


def reply_language_instruction(info: LangInfo, preferred: str = "", recent: str = "") -> str:
    """Rule for THIS reply. `preferred` is accepted for backwards compatibility and ignored: language is never a setting."""
    rule = ("LANGUAGE: work out the language, script and register of the student's LATEST message (English, Tamil, Tanglish, "
            "Hindi, Hinglish, Telugu, Malayalam, Kannada, Manglish, Tenglish, mixed, or any other language) and answer in "
            "exactly that language and style, like a native speaker chatting - never a word-by-word translation. Understand "
            "the MEANING first (informal spelling and code-mixing are normal). If they write mixed English + another language, "
            "answer in the dominant language and keep the mix natural. If they switch language, switch immediately; if "
            "their message is too short to tell, stay in the language of the previous messages. Keep programming terms, "
            "library names and error names in English. Explain in simple, beginner-friendly words.")
    if info.requested:
        rule = (f"The student explicitly asked for {info.requested}: reply in {info.requested} (keep technical terms in "
                f"English) until they ask for another language. ") + rule
    elif recent and info.name.startswith(("English", "unknown")):
        rule += f" Language used just before: {recent}."
    style = info.style()
    return f"{rule}{(' STYLE: ' + style) if style else ''} Hint (heuristic, may be wrong): {info.hint()}"
