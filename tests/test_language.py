"""Automatic language detection and language-matching replies.

Proves: every message is analysed on its own (no setting), the 5 required examples plus Telugu/Kannada/Hinglish/Manglish/
Tenglish/Kanglish are recognised, explicit requests win, tiny follow-ups keep the conversation's language, the model is
told to answer in that exact language/script/style, and the fixed off-topic reply exists in every supported language.
Not proven here: the wording a real model produces (needs a live provider; see the README).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["MENTOR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="mentor_lang_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from ai_engine import llm_provider, prompts  # noqa: E402
from ai_engine.assistant import Mentor  # noqa: E402
from ai_engine.language_detector import STYLE, detect, reply_language_instruction, resolve  # noqa: E402
from database import db, repository as repo  # noqa: E402

REQUIRED = [   # the examples from the requirement text
    ("I want to build a house price prediction project.", "English"),
    ("Enaku house price prediction project panna venum.", "Tanglish"),
    ("Ippo namma next task ku polam.", "Tanglish"),
    ("मुझे एक हाउस प्राइस प्रेडिक्शन प्रोजेक्ट बनाना है।", "Hindi"),
    ("എനിക്ക് ഒരു ഹൗസ് പ്രൈസ് പ്രെഡിക്ഷൻ പ്രോജക്റ്റ് ചെയ്യണം.", "Malayalam"),
]
MORE = [
    ("నాకు ఒక హౌస్ ప్రైస్ ప్రెడిక్షన్ ప్రాజెక్ట్ చేయాలి.", "Telugu"),
    ("ನನಗೆ ಒಂದು ಹೌಸ್ ಪ್ರೈಸ್ ಪ್ರಿಡಿಕ್ಷನ್ ಪ್ರಾಜೆಕ್ಟ್ ಮಾಡಬೇಕು.", "Kannada"),
    ("எனக்கு ஒரு house price prediction project பண்ணனும்.", "Tamil"),                         # Tamil script + English words
    ("Mujhe house price prediction project banana hai.", "Hinglish"),
    ("Enikku oru house price prediction project cheyyanam.", "Manglish"),
    ("Naaku oka house price prediction project cheyali.", "Tenglish"),
    ("Nanage house price prediction project madbeku.", "Kanglish"),
    ("Libraries ennalam venum?", "Tanglish"),
    ("Task 2 ku move pannalam", "Tanglish"),
    ("Enakku Task 2 puriyala. Konjam explain pannunga.", "Tanglish"),
]


@pytest.mark.parametrize("text,expected", REQUIRED + MORE)
def test_language_is_detected_for_every_message(text, expected):
    info = detect(text)
    assert info.name.startswith(expected), (text, info.name)


def test_english_is_not_mistaken_for_an_indian_language():
    for t in ("How do I read a CSV file with pandas?", "Explain feature scaling in simple words", "Which algorithm should I use?"):
        assert detect(t).name.startswith("English")


def test_explicit_language_request_wins():
    for text, lang in (("Can you explain this error in Tamil?", "Tamil"), ("Explain in Hindi please", "Hindi"),
                       ("tamil la explain pannunga", "Tamil"), ("Please answer in English", "English"),
                       ("malayalam il parayu", "Malayalam")):
        assert detect(text).requested == lang, text
    rule = reply_language_instruction(detect("Can you explain this error in Tamil?"))
    assert "explicitly asked for Tamil" in rule


def test_tiny_followups_keep_the_conversation_language_but_real_switches_are_followed():
    assert resolve("ok", "Tanglish").name == "Tanglish"
    assert resolve("next task", "Tanglish").name == "Tanglish"
    assert resolve("Why pandas?", "Malayalam").name == "Malayalam"
    assert resolve("Please explain how feature scaling works in this project", "Tanglish").name.startswith("English")   # clear switch
    assert resolve("ok", "").name.startswith("English")                                                             # nothing to inherit
    assert resolve("ippo enna pannanum", "English or another Latin-script language").name == "Tanglish"


def test_the_model_is_told_to_mirror_language_script_and_style():
    for text, name in (("Enaku house price prediction project panna venum.", "Tanglish"), (REQUIRED[3][0], "Hindi"),
                       (REQUIRED[4][0], "Malayalam"), (MORE[0][0], "Telugu"), (MORE[1][0], "Kannada"), (MORE[3][0], "Hinglish"),
                       (MORE[4][0], "Manglish"), (MORE[5][0], "Tenglish"), (MORE[6][0], "Kanglish")):
        rule = reply_language_instruction(detect(text))
        assert "exactly that language and style" in rule and "word-by-word" in rule and STYLE[name] in rule
    assert "Do NOT use Tamil script" in STYLE["Tanglish"] and "Tamil script" in STYLE["Tamil"]


def test_language_is_never_a_setting():
    rule_auto = reply_language_instruction(detect("Why Pandas?"), "Auto-detect")
    rule_forced = reply_language_instruction(detect("Why Pandas?"), "Tamil")          # an old 'preferred language' value
    assert rule_auto == rule_forced and "Tamil" not in rule_forced.split("Hint")[0].split("STYLE")[0].replace("Tamil, Tanglish", "")


def test_off_topic_reply_exists_in_every_supported_language():
    for lang in ("Tamil", "Tanglish", "Hindi", "Hinglish", "Telugu", "Tenglish", "Malayalam", "Manglish", "Kannada", "Kanglish"):
        text = prompts.off_topic_reply(lang)
        assert text != prompts.OFF_TOPIC_REPLY and "AI Project Mentor" in text
    assert prompts.off_topic_reply("Spanish") == prompts.OFF_TOPIC_REPLY        # unknown language -> the English text
    assert "ந" in prompts.off_topic_reply("Tamil") and "म" in prompts.off_topic_reply("Hindi") and "ഞ" in prompts.off_topic_reply("Malayalam")


# ---- end to end with a recording fake model: what the Mentor actually sends ----------------------
@pytest.fixture(scope="module")
def env():
    import test_conversation as tc
    db.init_db()
    fake = tc.Recorder()
    llm_provider.set_provider_override(fake)
    yield Mentor(), fake, tc
    llm_provider.set_provider_override(None)


def test_each_message_gets_its_own_language_instruction(env):
    mentor, fake, tc = env
    pid, cid = tc.make_project()
    seen = []
    for text in ("Why Pandas?", REQUIRED[4][0].replace("ഒരു ഹൗസ് പ്രൈസ് പ്രെഡിക്ഷൻ പ്രോജക്റ്റ്", "pandas") if False else "പാണ്ടാസ് എന്തിനാണ്?",
                 "Libraries ennalam venum?", "ok", "Can you explain this in Hindi? Why pandas?"):
        before = len(fake.calls)
        mentor.chat(cid, text)
        if len(fake.calls) > before:
            seen.append(fake.calls[-1][0]["content"])
    assert len(seen) == 5
    assert "Detected: English" in seen[0]
    assert "Detected: Malayalam" in seen[1] and STYLE["Malayalam"] in seen[1]
    assert "Detected: Tanglish" in seen[2] and STYLE["Tanglish"] in seen[2]
    assert "Detected: Tanglish" in seen[3]                      # 'ok' stays in the conversation's language
    assert "explicitly asked for Hindi" in seen[4]


def test_unrelated_message_is_refused_in_the_students_language(env):
    mentor, fake, tc = env
    pid, cid = tc.make_project()
    r = mentor.chat(cid, "enaku biryani recipe sollu")[0]
    assert r["content"] == prompts.off_topic_reply("Tanglish")
    r = mentor.chat(cid, "मौसम कैसा है आज?")[0]
    assert r["content"] == prompts.off_topic_reply("Hindi")
