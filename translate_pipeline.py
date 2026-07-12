# ====================================================================
# VERTIMO GRANDINĖ (3 pakopos + deterministinis saugiklis)
#
# 1. ANALIZĖ  – modelis suranda žargoną/ironiją/idiomas, iššifruoja
#               jų PRASMĘ ir atskirai išgryna FAKTUS. Dar nieko nerašo.
# 2. RAŠYMAS  – modelis gauna faktus + iššifruotą žargoną ir rašo postą.
#               Ironiją išlaiko TIK jei ji natūraliai veikia lietuviškai.
# 3. PERŽIŪRA – modelis tikrina savo darbą pagal kontrolinį sąrašą
#               ir, radęs bėdą, perrašo.
# 4. SAUGIKLIS – Python'o regex patikra (juodasis sąrašas, kirilica,
#               nuorodos, hashtag'ai). Jei praslydo – dar vienas
#               bandymas "tik faktai", o jei ir tada blogai –
#               postas be teksto + pranešimas į Telegram.
# ====================================================================

import re
import json
import time
import logging
import requests

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


# --------------------------------------------------------------------
# 1 PAKOPA: ANALIZĖ
# --------------------------------------------------------------------
ANALYZE_PROMPT = """You analyse a single news item from a Ukrainian Telegram war channel (Ukrainian or Russian).
You do NOT translate and you do NOT write anything for publication. You only analyse.

Return STRICT JSON, nothing else, in exactly this shape:

{
  "facts": "A plain, literal, unemotional statement of what actually happened. Who did what to whom, where, with what result. No metaphors, no irony, no jokes. This is the ground truth the post will be built on.",
  "expressions": [
    {
      "original": "the exact slang / idiom / irony / euphemism / abbreviation / wordplay as written in the source",
      "literal": "what it says word-for-word",
      "meaning": "what it ACTUALLY means",
      "lt_natural": "a natural Lithuanian phrase that carries the same meaning AND the same tone, or null if no such phrase exists",
      "safe_in_lt": true or false
    }
  ],
  "tone": "neutral | ironic | mocking | dramatic",
  "risk": "low | medium | high"
}

RULES FOR THE ANALYSIS
- Find EVERY expression whose literal reading is absurd, impossible, ironic, mocking, or would confuse an ordinary Lithuanian reader. Military slang, unit nicknames, euphemisms, abbreviations, deliberate typos, dark jokes.
- "safe_in_lt" is true ONLY if a real, existing, commonly understood Lithuanian phrase carries the same meaning and tone. If you would have to invent a word, calque the image, or the Lithuanian reader would not get the joke — it is false.
- If you are not certain what an expression means, set "meaning" to "NEZINOMA", "safe_in_lt" to false, and "risk" to "high".
- "facts" must stay true even if every expression is thrown away.

Examples of the judgement you must make:
  "навчилися літати" (learned to fly) -> literal absurd; meaning: they were blown up by a strike; lt_natural: "išmoko skraidyti" works in Lithuanian as the same dark joke -> safe_in_lt: true
  "бавовна" (cotton) -> meaning: explosions; Lithuanian has no such joke -> lt_natural: null, safe_in_lt: false
  "прильот" (an arrival) -> meaning: a strike hit the target; "prilytimas" is not a word -> safe_in_lt: false
  "двохсотий" (two-hundredth) -> meaning: killed soldier -> safe_in_lt: false"""


# --------------------------------------------------------------------
# 2 PAKOPA: RAŠYMAS
# --------------------------------------------------------------------
WRITE_PROMPT = """You are a news editor for a Lithuanian-language Facebook news page.

You receive:
  SOURCE  – the original news item from a Ukrainian Telegram channel
  FACTS   – a plain statement of what actually happened (already verified)
  DECODED – slang / irony / wordplay found in the source, already decoded for you

Write ONE ready-to-publish Lithuanian Facebook post.

A. CONTENT
1. Begin with a short notice that this is the latest news from Ukraine.
2. Build the post on FACTS. Never contradict FACTS. Add no facts that are not there.
3. Editorial frame: Russia and its actions are aggression; Ukraine is the defending country, even when it strikes objects inside Russia. Never reproduce the aggressor's framing.
4. Remove every link and URL. Add none. Do not invite readers to follow other channels.
5. Keep emojis that appear in the source and place them naturally.
6. End with 3-5 Lithuanian hashtags.
7. Output ONLY the post text. No preamble, no explanation, no quotation marks, no alternatives.

B. IRONY AND WORDPLAY — the rule that matters
For every entry in DECODED:
  - If "safe_in_lt" is TRUE: you MAY keep the joke, using the "lt_natural" phrase. The tone of the channel is worth preserving when it survives the trip into Lithuanian.
  - If "safe_in_lt" is FALSE: the joke DIES. Write the "meaning" plainly instead. Never carry the literal image across. Never invent a word to save a joke.
  - If "meaning" is "NEZINOMA": leave that expression out entirely, or replace it with a broader word you are certain about ("karinė technika", "smūgis", "įranga"). Never guess.
A correct, slightly duller post always beats a clever, wrong one.

C. LANGUAGE
Only real, commonly used Lithuanian words that exist in a dictionary. No neologisms, no transliterations, no calques. Short, simple sentences. A reader who does not follow the war must understand every word."""


# --------------------------------------------------------------------
# 3 PAKOPA: PERŽIŪRA
# --------------------------------------------------------------------
REVIEW_PROMPT = """You are a strict Lithuanian editor. You receive FACTS and a DRAFT Facebook post.
Check the draft against this list and return STRICT JSON, nothing else:

{
  "ok": true or false,
  "problems": ["short description of each problem found"],
  "final": "the corrected post text, ready to publish (or the unchanged draft if it was already fine)"
}

CHECKLIST — mark ok:false if ANY of these fail:
1. Every single word is a real Lithuanian word that exists in a dictionary. No invented words, no transliterations from Ukrainian or Russian.
2. No literal calque of a foreign image that makes no sense in Lithuanian.
3. A reader who does not follow the war understands the whole post.
4. The post agrees with FACTS and adds nothing that is not in them.
5. No links, no URLs, no "www.", no invitation to follow other channels.
6. The post begins with a notice that this is the latest news from Ukraine.
7. The post ends with 3-5 Lithuanian hashtags.
8. No Cyrillic letters anywhere.
9. If the draft keeps a joke or irony: it must work naturally in Lithuanian. If it is confusing, forced, or absurd — remove the joke and state the fact plainly.

"final" must ALWAYS contain a publishable post — fix the problems yourself. Never return an empty "final"."""


# --------------------------------------------------------------------
# DETERMINISTINIS SAUGIKLIS
# --------------------------------------------------------------------
BANNED_PATTERNS = [
    r"prilytim",                 # прильот -> "prilytimas"
    r"[šs]achid",                # šachidas (turi būti šachedas)
    r"bojepripais",
    r"antipersonines\s+minas",
    r"Pta[čc]i[ųu]\s+Madyaro",
    r"medviln",                  # бавовна pažodžiui
    r"du\s*[šs]imtas\w*\s+kar",  # двохсотий pažodžiui
]

def hard_check(text):
    """Grąžina problemų sąrašą. Tuščias sąrašas = tekstas švarus."""
    problems = []
    if not text or len(text.strip()) < 30:
        problems.append("tekstas tuščias arba per trumpas")
        return problems
    if re.search(r"[Ѐ-ӿ]", text):
        problems.append("likusi kirilica (neišverstas fragmentas)")
    if re.search(r"https?://|www\.", text, re.I):
        problems.append("poste liko nuoroda")
    if len(re.findall(r"#\w+", text)) < 3:
        problems.append("mažiau nei 3 hashtag'ai")
    for pat in BANNED_PATTERNS:
        if re.search(pat, text, re.I):
            problems.append(f"juodojo sąrašo frazė: /{pat}/")
    return problems


# --------------------------------------------------------------------
# DEEPSEEK SKAMBUTIS
# --------------------------------------------------------------------
def _call(api_key, messages, temperature=0.2, max_tokens=1200, force_json=False):
    payload = {
        "model": DEEPSEEK_MODEL,
        "temperature": temperature,
        "top_p": 1,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {api_key}"}

    reason = "nezinoma"
    for attempt in (1, 2):
        try:
            r = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=90)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                if content:
                    return content, True, ""
                reason = "tuščias atsakymas"
            else:
                reason = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
        logger.warning(f"⚠️ DeepSeek bandymas {attempt} nepavyko: {reason}")
        if attempt == 1:
            time.sleep(5)
    return "", False, reason


def _json_or_none(raw):
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


# --------------------------------------------------------------------
# PAGRINDINĖ FUNKCIJA
# Grąžina (tekstas, ok, ataskaita)
# --------------------------------------------------------------------
def translate(api_key, source_text):
    report = []

    if not api_key:
        return "", False, "DEEPSEEK_API_KEY nenustatytas"

    # ---------- 1. ANALIZĖ ----------
    raw, ok, reason = _call(api_key, [
        {"role": "system", "content": ANALYZE_PROMPT},
        {"role": "user", "content": source_text},
    ], temperature=0.0, max_tokens=900, force_json=True)

    if not ok:
        return "", False, f"analizė nepavyko: {reason}"

    analysis = _json_or_none(raw) or {}
    facts = analysis.get("facts") or source_text
    decoded = analysis.get("expressions") or []
    risk = analysis.get("risk", "low")

    if decoded:
        logger.info(f"🔎 Rasta {len(decoded)} žargono/ironijos vietų, rizika: {risk}")
        for e in decoded:
            logger.info(f"   • {e.get('original')} → {e.get('meaning')} "
                        f"(lietuviškai veikia: {e.get('safe_in_lt')})")

    # ---------- 2. RAŠYMAS ----------
    user_block = (
        f"SOURCE:\n{source_text}\n\n"
        f"FACTS:\n{facts}\n\n"
        f"DECODED:\n{json.dumps(decoded, ensure_ascii=False, indent=1)}"
    )
    draft, ok, reason = _call(api_key, [
        {"role": "system", "content": WRITE_PROMPT},
        {"role": "user", "content": user_block},
    ], temperature=0.2, max_tokens=1000)

    if not ok:
        return "", False, f"rašymas nepavyko: {reason}"

    # ---------- 3. PERŽIŪRA ----------
    raw, ok, reason = _call(api_key, [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": f"FACTS:\n{facts}\n\nDRAFT:\n{draft}"},
    ], temperature=0.0, max_tokens=1200, force_json=True)

    final = draft
    if ok:
        rev = _json_or_none(raw)
        if rev and rev.get("final"):
            if not rev.get("ok", True):
                report.append(f"peržiūra taisė: {'; '.join(rev.get('problems', []))}")
                logger.info(f"✏️ Peržiūra taisė: {rev.get('problems')}")
            final = rev["final"].strip()
    else:
        report.append(f"peržiūra praleista: {reason}")

    # ---------- 4. SAUGIKLIS ----------
    problems = hard_check(final)
    if problems:
        logger.warning(f"🛑 Saugiklis rado: {problems}. Perrašom griežtai (tik faktai).")
        report.append(f"saugiklis: {'; '.join(problems)}")

        strict, ok, reason = _call(api_key, [
            {"role": "system", "content": WRITE_PROMPT + (
                "\n\nD. STRICT MODE — the previous attempt failed a safety check. "
                "Throw away ALL irony, jokes and wordplay. Write only the plain facts "
                "in the simplest possible Lithuanian. Nothing clever. Nothing borrowed "
                "from the original's imagery.")},
            {"role": "user", "content": f"FACTS:\n{facts}\n\nSOURCE:\n{source_text}"},
        ], temperature=0.0, max_tokens=900)

        if ok:
            problems2 = hard_check(strict)
            if not problems2:
                logger.info("✅ Griežtas perrašymas praėjo saugiklį.")
                return strict, True, "; ".join(report) + " → perrašyta griežtai"
            report.append(f"griežtas perrašymas irgi krito: {'; '.join(problems2)}")

        return "", False, "; ".join(report)

    return final, True, "; ".join(report) if report else "ok"
