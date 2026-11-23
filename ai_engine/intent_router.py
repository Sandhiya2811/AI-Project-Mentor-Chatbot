"""Understands WHAT the student wants before any LLM is called.

Why this exists: the old flow asked the LLM to answer "[[OFF_TOPIC]]" whenever it thought a message was unrelated.
Small models do that for perfectly good Tanglish questions ("Libraries ennalam venum?"). Scope control and workflow
control are now decided here, deterministically and with the PROJECT CONTEXT (tool names, task titles, task numbers,
task status), in English, Tamil script and Tanglish/Hinglish. The LLM only gets the off-topic option when this router
is genuinely unsure, and it is never asked to classify obvious project questions.

This is a layered heuristic, not magic: (1) explicit task references, (2) workflow phrases, (3) technical + project
vocabulary, (4) a short list of clearly unrelated topics, (5) "when in doubt, treat it as a project follow-up".
It costs microseconds and no LLM call (important for the response-time target).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# kinds: explain_task | explain_roadmap | advance | whats_next | acknowledge | completion | tools | resources |
#        concept | error | followup | ambiguous | unrelated
RAG_KINDS = {"concept", "error", "followup", "ambiguous"}


@dataclass
class Intent:
    kind: str
    project_related: bool | None          # True / False / None = unsure (LLM may decide)
    tasks: list[int] = field(default_factory=list)   # explicit task numbers (1-based)
    relative: str = ""                    # "", "current", "next", "previous", "last"
    out_of_range: list[int] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)   # project tools named in the message
    signals: list[str] = field(default_factory=list)

    @property
    def needs_rag(self) -> bool:
        return self.kind in RAG_KINDS


# ---- vocabulary (English + Tanglish + Tamil script + a little Hinglish) ----------------------------------------------
ACK = {"ok", "okay", "okk", "k", "kk", "fine", "understood", "clear", "got", "gotcha", "yes", "yeah", "yep", "yup",
       "sure", "right", "alright", "thanks", "thank", "thx", "nice", "great", "good", "cool", "super", "seri", "sari",
       "purinjidhu", "purinjathu", "purinjudhu", "puriyudhu", "puriyuthu", "purinjiduchu", "theliva", "nandri", "ha",
       "haan", "accha", "theek", "ஓகே", "சரி", "புரிந்தது", "புரிஞ்சது", "நன்றி"}
COMPLETE = {"completed", "complete", "finished", "finish", "done", "mudinchuchu", "mudinchutu", "mudinjuthu",
            "mudinjathu", "mudichitten", "mudichuten", "mudichen", "mudichiten", "முடிந்தது", "முடிச்சுட்டேன்", "முடிஞ்சது"}
ADVANCE = {"move", "moving", "proceed", "continue", "polam", "pogalam", "pogalama", "pogalaama", "pannalam", "pannalama",
           "start", "begin", "agalam", "ahead", "switch", "jump", "vaanga", "varalam", "go", "goto", "lets", "let's",
           "போகலாம்", "தொடரலாம்", "ஆரம்பிக்கலாம்", "அடுத்த"}
WHATS_NEXT = {"what", "enna", "ennanu", "yenna", "ippo", "now", "after", "next", "adutha", "aduthu", "அடுத்து", "என்ன"}
ALL_WORDS = {"all", "every", "entire", "whole", "ella", "ellam", "ellaa", "எல்லா", "அனைத்து"}
ROADMAP_WORDS = {"roadmap", "plan", "stages", "phases", "tasks", "steps", "milestones", "workflow", "outline", "overview"}
EXPLAIN_CUES = {"explain", "explanation", "describe", "tell", "show", "detail", "details", "elaborate", "clarify", "again",
                "what", "enna", "ennanu", "yenna", "why", "how", "when", "which", "eppadi", "epdi", "ethuku", "edhuku",
                "yen", "yaen", "sollu", "sollunga", "solluga", "solliruka", "vilakku", "vilakkam", "puriyala", "purila",
                "purilla", "theriyala", "irukku", "iruku", "pannunga", "pannu", "pannuvom", "pannanum", "venum",
                "விளக்கு", "விளக்க", "ஏன்", "எப்படி", "என்ன"}
TOOL_CUES = {"library", "libraries", "librarie", "lib", "libs", "package", "packages", "install", "pip", "framework",
             "frameworks", "tool", "tools", "technology", "technologies", "tech", "stack", "dependency", "dependencies",
             "module", "modules", "requirements", "software", "லைப்ரரி", "கருவி"}
RESOURCE_CUES = {"learn", "learning", "resource", "resources", "documentation", "docs", "doc", "tutorial", "tutorials",
                 "link", "links", "reference", "references", "study", "padikka", "padikanum", "course", "material",
                 "materials", "read", "reading"}
ERROR_RE = re.compile(r"\b\w*(?:error|exception|traceback|warning)\b|not working|doesn'?t work|wont work|won't work|"
                      r"\b(?:bug|crash|crashed|stuck|failed|failing|issue|problem)\b|work aagala|work agala|"
                      r"vara(?:la|villai)|\bfix\b", re.I)
TECH = {
    "code", "coding", "program", "programming", "python", "java", "javascript", "typescript", "c++", "sql", "html", "css",
    "function", "functions", "class", "variable", "loop", "list", "dictionary", "array", "string", "syntax", "script",
    "data", "dataset", "datasets", "csv", "dataframe", "column", "columns", "row", "rows", "feature", "features",
    "label", "target", "preprocessing", "preprocess", "clean", "cleaning", "missing", "null", "outlier", "outliers",
    "scaling", "scale", "scaler", "normalization", "normalisation", "standardization", "encoding", "encode",
    "model", "models", "train", "training", "test", "testing", "split", "predict", "prediction", "predictor",
    "algorithm", "algorithms", "regression", "classification", "classifier", "clustering", "forest", "tree", "svm",
    "knn", "boosting", "neural", "network", "deep", "learning", "machine", "ml", "ai", "nlp", "llm", "rag", "gpt",
    "embedding", "embeddings", "token", "tokenization", "vector", "transformer", "accuracy", "precision", "recall", "f1",
    "rmse", "mae", "mse", "r2", "metric", "metrics", "evaluation", "evaluate", "validation", "cross", "overfitting",
    "underfitting", "bias", "variance", "hyperparameter", "confusion", "matrix", "plot", "chart", "graph", "visualize",
    "visualization", "histogram", "heatmap", "correlation", "pandas", "numpy", "matplotlib", "seaborn", "sklearn",
    "scikit", "scikit-learn", "nltk", "spacy", "tensorflow", "keras", "pytorch", "streamlit", "flask", "django",
    "fastapi", "react", "node", "npm", "api", "database", "db", "sqlite", "mysql", "postgres", "query", "git", "github",
    "commit", "branch", "repository", "repo", "readme", "documentation", "deploy", "deployment", "server", "docker",
    "debug", "debugging", "bug", "test", "unit", "pytest", "junit", "file", "files", "upload", "submit", "submission",
    "review", "validate", "validation", "project", "task", "tasks", "stage", "roadmap", "architecture", "module",
    "requirements", "dataset", "jupyter", "notebook", "ide", "vscode", "terminal", "venv", "environment", "import",
    "install", "version", "attendance", "grades", "marks", "performance", "student", "students", "objective",
}
UNRELATED = {
    "weather", "rain", "cricket", "football", "soccer", "ipl", "match", "score", "movie", "movies", "film", "cinema",
    "actor", "actress", "song", "songs", "lyrics", "singer", "recipe", "cook", "cooking", "biryani", "restaurant",
    "joke", "jokes", "funny", "riddle", "horoscope", "astrology", "zodiac", "president", "minister", "election",
    "politics", "politician", "celebrity", "gossip", "lottery", "girlfriend", "boyfriend", "dating", "love", "crush",
    "marriage", "wedding", "diet", "workout", "gym", "travel", "hotel", "flight", "tourist", "shopping", "fashion",
    "movie", "padam", "paatu", "saapadu", "mazhai", "kadhal", "vaanilai", "capital", "population", "poem", "story",
    "bitcoin", "stocks", "horror", "game", "games", "gaming", "memes", "meme", "religion", "god", "birthday", "festival",
    "நடிகர்", "படம்", "பாட்டு", "மழை", "கிரிக்கெட்", "சாப்பாடு", "வானிலை", "சினிமா", "சமையல்", "நகைச்சுவை",
    # Hindi, Malayalam, Telugu, Kannada (script) and their romanised forms
    "मौसम", "क्रिकेट", "फिल्म", "फ़िल्म", "गाना", "गाने", "खाना", "रेसिपी", "चुटकुला", "राशिफल", "चुनाव",
    "കാലാവസ്ഥ", "സിനിമ", "പാട്ട്", "ക്രിക്കറ്റ്", "പാചകം", "തമാശ",
    "వాతావరణం", "సినిమా", "పాట", "క్రికెట్", "వంట", "జోక్",
    "ಹವಾಮಾನ", "ಸಿನಿಮಾ", "ಹಾಡು", "ಕ್ರಿಕೆಟ್", "ಅಡುಗೆ",
    "mausam", "mazha", "kaalavastha", "vathavaranam", "havamana", "chitti", "gaana",
}
STOP = {"this", "that", "with", "from", "your", "have", "will", "would", "could", "should", "about", "into", "which",
        "their", "there", "where", "what", "when", "then", "than", "them", "they", "these", "those", "been", "being",
        "make", "made", "more", "some", "such", "using", "used", "also", "each", "other", "only", "very", "both",
        "project", "predict", "build", "create"}

_WORD = re.compile(r"[a-z0-9+#'\-]+", re.I)
_NUM_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
              "ninth": 9, "mudhal": 1, "modhal": 1}
_TASK_NUM = re.compile(r"(?:\b(?:task|step|stage|phase|module|part)s?|டாஸ்க்|பணி)\s*[-#:.]?\s*(\d{1,2})\b"
                       r"|\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:task|step|stage|phase)\b", re.I)
_ORDINAL_TASK = re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|mudhal|modhal)\s+"
                           r"(?:task|step|stage|phase)\b", re.I)
_RELATIVE = [("previous", re.compile(r"\b(?:previous|prev|last\s+(?:one|task)|munna|munnadi)\b", re.I)),
             ("last", re.compile(r"\b(?:final|last)\s+(?:task|stage|step|validation)\b", re.I)),
             ("current", re.compile(r"\b(?:current|this|indha|intha|ippo\s+irukkira)\s+(?:task|stage|step)\b", re.I)),
             ("next", re.compile(r"\b(?:next|adutha|aduthu|upcoming)\s+(?:task|stage|step|one)?\b|அடுத்த", re.I))]


def _words(text: str) -> list[str]:
    return [w.lower().strip("'-") for w in _WORD.findall(text)]


def _has(text: str, words: list[str], vocab: set[str]) -> bool:
    ws = set(words)
    return any((v in ws) if v.isascii() else (v in text) for v in vocab)


def _project_vocab(project: dict | None, tasks: list[dict], tools: list[str]) -> set[str]:
    vocab: set[str] = set()
    sources = [(project or {}).get("title", ""), (project or {}).get("objective", ""), " ".join(tools),
               " ".join(t["title"] for t in tasks)]
    for src in sources:
        vocab.update(w for w in _words(src) if len(w) >= 4 and w not in STOP)
    return vocab


def task_numbers(text: str, n_tasks: int) -> tuple[list[int], list[int]]:
    """(valid numbers, out-of-range numbers) of tasks explicitly named in the message."""
    found: list[int] = []
    for m in _TASK_NUM.finditer(text):
        found.append(int(m.group(1) or m.group(2)))
    for m in _ORDINAL_TASK.finditer(text):
        found.append(_NUM_WORDS[m.group(1).lower()])
    seen, ok, bad = set(), [], []
    for n in found:
        if n in seen:
            continue
        seen.add(n)
        (ok if 1 <= n <= n_tasks else bad).append(n)
    return ok, bad


def classify(text: str, project: dict | None = None, tasks: list[dict] | None = None,
             tools: list[str] | None = None) -> Intent:
    tasks, tools = tasks or [], tools or []
    low = " ".join(text.lower().split())
    words = _words(low)
    nums, bad = task_numbers(low, len(tasks))
    relative = next((name for name, rx in _RELATIVE if rx.search(low)), "")
    mentioned = [t for t in tools if t.lower() in low or any(w == t.lower() for w in words)]
    pvocab = _project_vocab(project, tasks, tools)
    tech = [w for w in words if w in TECH]
    pv = [w for w in words if w in pvocab]
    q = "?" in text
    sig = []
    done_cue = _has(low, words, COMPLETE)
    adv_cue = _has(low, words, ADVANCE)
    next_cue = _has(low, words, {"next", "adutha", "aduthu", "அடுத்த", "அடுத்து"})
    what_cue = _has(low, words, {"what", "enna", "ennanu", "yenna", "ippo", "now", "after", "அடுத்து", "என்ன"})
    all_cue = _has(low, words, ALL_WORDS)
    roadmap_cue = _has(low, words, ROADMAP_WORDS)
    explain_cue = _has(low, words, EXPLAIN_CUES)

    def make(kind: str, related: bool | None = True) -> Intent:
        return Intent(kind, related, nums, relative, bad, mentioned, sig)

    # 1. whole roadmap
    if (all_cue and (roadmap_cue or "task" in low or "stage" in low or "step" in low or "ella" in words)) or \
            re.search(r"\b(?:roadmap|complete (?:plan|roadmap)|full (?:plan|roadmap)|project plan|project flow)\b", low) or \
            (roadmap_cue and explain_cue and not nums and "task" in low and ("tasks" in words or "stages" in words)):
        sig.append("roadmap")
        return make("explain_roadmap")
    # 2. explicit task number(s) or out-of-range reference
    if nums or bad:
        sig.append("task-number")
        if done_cue:
            return make("completion")
        if adv_cue and not _has(low, words, {"explain", "describe", "details"}):
            return make("advance")
        return make("explain_task")
    # 3. relative task references: "previous task", "next task polam", "current task"
    if relative and (explain_cue or adv_cue or next_cue or q or done_cue):
        sig.append(f"relative:{relative}")
        if done_cue:
            return make("completion")
        if relative == "next" and adv_cue:
            return make("advance")
        if relative == "next" and what_cue and not adv_cue:
            return make("whats_next")
        if relative == "next":
            return make("explain_task") if _has(low, words, {"explain", "describe", "details", "sollu", "sollunga"}) else make("advance")
        return make("explain_task")
    # 4. workflow without a number
    if (next_cue or what_cue) and (len(words) <= 9 or q) and not (tech and not next_cue):
        if re.search(r"\b(?:next|adutha|aduthu)\b|அடுத்த|\bwhat now\b|\bnow what\b|\bwhat should i do\b|ippo enna", low):
            sig.append("next")
            return make("advance") if adv_cue else make("whats_next")
    if adv_cue and len(words) <= 8 and re.search(r"\b(?:shall we|can we|lets|let's|move on|go on|go ahead|continue|proceed)\b", low):
        sig.append("continue")
        return make("advance")
    if done_cue and len(words) <= 12 and not tech and not mentioned:
        sig.append("completion")
        return make("completion")
    # 5. acknowledgement ("okay", "I understand", "seri purinjidhu")
    if words and len(words) <= 7 and not q and not tech and not mentioned and \
            (all(w in ACK or w in {"i", "i'm", "im", "it", "is", "was", "that", "thanks", "very", "much", "so", "a", "the",
                                    "understand", "understood", "got", "it", "task", "clear", "now", "all", "good", "to",
                                    "me", "thank", "you", "alright", "ok"} for w in words) and any(w in ACK or w.startswith("understand") for w in words)):
        sig.append("ack")
        return make("acknowledge")
    # 6. tools / resources / technical concepts / errors
    if ERROR_RE.search(low):
        sig.append("error")
        return make("error")
    if _has(low, words, TOOL_CUES) and not mentioned:
        sig.append("tools")
        return make("tools")
    if _has(low, words, RESOURCE_CUES) and (tech or mentioned or pv or len(words) <= 8):
        sig.append("resources")
        return make("resources")
    if mentioned or tech or pv:
        sig.append("technical")
        return make("concept")
    # 7. clearly unrelated?
    if _has(low, words, UNRELATED):
        sig.append("unrelated-topic")
        return make("unrelated", False)
    # 8. doubt -> a short message is a follow-up; a longer one is left to the LLM with an escape hatch
    if len(words) <= 6:
        sig.append("short")
        return make("followup")
    return make("ambiguous", None)
