"""Plain words, and code's own readers of what a customer wrote.

- plain(): internal ids (send_help, gone_quiet, days_since_last_order, 'ne') become words an owner reads. Nothing an
  owner or a customer sees may carry an id (verify's plain_words check, and tests that scan every page).
- read_language(): the language and script of a message, read by code: Roman Nepali in Latin letters and Bhojpuri in
  Devanagari included, which the guard model reads as Nepali or Hindi.
- open_question(): did the customer ask something?
- promises(): claims and promises about stock, delivery times, photos, prices and discounts, in the five languages
  the shop's customers write. Pheri holds no fact about stock, delivery dates or photos, so it may not claim them; a
  sentence that hands the matter to the owner ("the owner will confirm") is not a promise.
The marker lists are code, not a model; they wait for a native speaker's review like every Birgunj string.
"""

from __future__ import annotations

import re

LANGUAGE_NAMES = {"en": "English", "ne": "Nepali", "ne-Latn": "Roman Nepali", "hi": "Hindi", "bho": "Bhojpuri",
                  "es": "Spanish", "pt": "Portuguese"}

ACTION_WORDS = {
    "send_help": "send help", "book_call": "offer a call", "send_checkin": "a check-in",
    "offer_upgrade": "suggest an upgrade", "offer_discount": "offer a discount",
    "send_reminder": "follow up on their question", "recommend_product": "recommend a product",
    "offer_subscription": "offer a subscription", "offer_reorder": "time to reorder",
    "answer_question": "answer their question", "task_for_owner": "a task for you", "no_action": "nothing for now",
    "escalate_to_human": "escalated to you", "holding_reply": "a fixed holding reply",
}
STAGE_WORDS = {
    "at_risk_renewal": "at risk before renewal", "asked_no_order": "asked but did not order",
    "gone_quiet": "gone quiet",
}
FACT_WORDS = {
    "journey_stage": "journey stage", "days_since_signup": "days since they joined", "days_quiet": "days quiet",
    "failed_exports": "failed exports", "failed_exports_30d": "failed exports this month",
    "seat_limit_hits_30d": "seat-limit hits this month", "active_days_30d": "active days this month",
    "active_days_prev_60d": "active days in the 60 days before", "usage_change_pct": "usage against usual",
    "open_tickets": "open tickets", "price_complaints": "price complaints", "renewal_in_days": "days to renewal",
    "mrr_usd": "monthly revenue", "days_since_last_order": "days since their last order",
    "total_spend_npr": "total spent", "last_order_items": "last order", "usual_payment": "usual payment",
    "open_complaints": "orders with a problem", "complaint_kind": "the problem", "days_late": "days late",
    "cod_refusals": "cash on delivery refused", "reorder_every_days": "how often they reorder",
    "festival_only": "only buys for festivals", "days_since_enquiry": "days since they asked",
    "next_festival": "next festival", "days_to_next_festival": "days to the festival",
    "asks_about_money": "asked about money", "open_question": "asked a question",
    "return_requested": "asked to return it", "wrong_colour": "wrong colour", "wrong_size": "wrong size",
}
CHECK_WORDS = {
    "one_problem": "one problem", "middle_step": "the plan check", "plain_words": "plain words",
    "private_stats": "private numbers",
}
PLAIN = {**ACTION_WORDS, **STAGE_WORDS, **FACT_WORDS, **CHECK_WORDS}

# An internal id: snake_case, or a language code in quotes.
_ID = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
_CODE = re.compile(r"""(['"])(en|ne|hi|bho|ne-Latn|es|pt)\1""")


def internal_ids(text: str) -> list[str]:
    """The ids in a text, in order, once each."""
    found = [m.group(0) for m in _ID.finditer(text or "")] + [m.group(0) for m in _CODE.finditer(text or "")]
    return list(dict.fromkeys(found))


def plain(text: str | None) -> str | None:
    """The same text with every internal id in plain words (an unknown snake_case id loses its underscores)."""
    if not text:
        return text
    out = _CODE.sub(lambda m: LANGUAGE_NAMES.get(m.group(2), m.group(2)), text)
    return _ID.sub(lambda m: PLAIN.get(m.group(0), m.group(0).replace("_", " ")), out)


CHECK_NAMES = {"rules": "Your rules", "schema": "Form", "evidence": "Evidence", "facts": "Facts",
               "promises": "Promises", "pronouns": "Pronouns", "address": "How it talks to them",
               "one_problem": "One problem", "language": "Language", "length": "Length", "links": "Links",
               "money": "Money", "plain_words": "Plain words", "private_stats": "Private numbers",
               "middle_step": "The plan", "tools": "Tools", "judge": "The judge"}


def plain_reason(reason: str) -> str:
    """A verification reason ("address: says ...", "judge: ...") for the owner: the check's name in words, then the
    reason in plain words."""
    name, sep, rest = (reason or "").partition(": ")
    if sep and name in CHECK_NAMES:
        return f"{CHECK_NAMES[name]}: {plain(rest)}"
    return plain(reason)


# ---- reading a message ------------------------------------------------------------------
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
ROMAN_NEPALI = {
    "chha", "cha", "chhan", "chhaina", "chaina", "ho", "hajur", "tapai", "tapain", "garnu", "garnus", "garnuhos",
    "dinus", "dinuhos", "huncha", "hunchha", "hola", "ko", "lai", "le", "pani", "aba", "ani", "kati", "kaha", "kahile",
    "kasari", "pathaunu", "pathaunus", "pathaidinu", "pathaidinuhunchha", "ramro", "naya", "ajhai", "testai",
    "dhanyabad", "namaste", "lagi", "sakinchha", "parchha", "malai", "yo", "tyo", "hamro", "hamile", "thiyo", "aayo",
    "milena", "satera", "arko", "linchhu", "chhut", "pugyo", "bhannu", "bhako", "sabai", "sandesh", "paiyo",
    "sahuji", "aaja", "bihana", "jawaf", "dinuhunchha", "hunu", "gareko", "garera", "pathaidinuhos", "ma",
    "mero", "aaipugchha", "bhayo", "agadi", "ajhai", "aayena", "wata", "garne", "maa", "dherai", "chahiyo", "samma",
    "najikai", "bata", "thik", "bujhe", "shubhakamana", "chyatieko", "hataidinus", "din", "ta", "pugchha", "lagchha",
    "parchha", "cha", "hunuhunchha", "bhaneko",
}
ROMAN_NEPALI_STEMS = ("pathau", "pathai", "napathau", "garnu", "dinu", "hunchh", "chhain", "garera", "sakin")
BHOJPURI = {"बा", "बाड़े", "बाड़न", "रउआ", "रउरा", "हमरा", "हमार", "आइल", "गइल", "कइल", "बानी", "भेजीं", "खातिर",
            "ओइसन", "अउर", "दिहें", "नइखे", "दोसर", "देब", "अगिला", "गो", "चाहीं", "उहे", "रही", "बदल", "हमनी", "होई", "ई", "जाई", "जाईं", "जादा", "करीं", "दीं", "केतना", "त", "भुला", "पिछला", "पहुँची",
            "होखी", "बाटे", "रहल", "लागी", "कहाँ", "कइसे", "बताईं", "चाहत", "कबो", "मंगाइब", "हईं", "बेर", "अबहीं", "मिलल", "देब", "भेजब", "कहले", "संदेस"}


NEPALI = {"छ", "छन्", "छैन", "हो", "हुन्छ", "पहिलो", "गर्दैछु", "कसरी", "छान्ने", "लागि", "नयाँ", "आयो", "पठाउनुस्",
          "अर्को", "चाहियो", "जस्तो", "हजुर", "पनि", "अनि", "गर्नुहोस्", "दिनुहोस्", "भयो", "थियो", "मेरो", "तपाईं",
          "हामी", "हुनुहुन्छ", "पाइयो", "न", "यो", "त्यो", "अझै"}
NEPALI_ENDINGS = ("को", "मा", "ले", "लाई", "हरू", "बाट", "सँग", "वटा", "कै", "दैछु", "नुस्", "नुहोस्")
HINDI = {"है", "हैं", "के", "की", "का", "में", "से", "और", "नहीं", "था", "थी", "थे", "दीजिए", "भेजिए", "चाहिए", "लिए",
         "आए", "वाली", "वाला", "बहुत", "अच्छी", "जैसा", "मेरा", "आपका", "मिल", "गया", "गई", "कर", "कब", "तक", "हफ्ते"}


def read_language(text: str) -> str:
    """Code's reading of a message's language and script: ne-Latn (Nepali in Latin letters), bho, ne, hi, en, es,
    pt. Script first, then marker words."""
    from .guard import _mock_language  # code's reader of en, es, pt, hi, ne

    t = text or ""
    if _DEVANAGARI.search(t):
        words = re.findall(r"[ऀ-ॣ०-ॿ]+", t)
        bho = len(set(words) & BHOJPURI)
        ne = sum(w in NEPALI or (len(w) > 3 and w.endswith(NEPALI_ENDINGS)) for w in words)
        hi = sum(w in HINDI for w in words)
        if bho >= 2 or (bho == 1 and hi == 0 and ne == 0):  # a short Bhojpuri line has one marker and no other
            return "bho"
        return "ne" if ne > hi else "hi" if hi > ne else _mock_language(t)
    words = set(re.findall(r"[a-z]+", t.casefold()))
    stems = sum(w.startswith(ROMAN_NEPALI_STEMS) for w in words)
    if len(words & ROMAN_NEPALI) + stems >= 2:
        return "ne-Latn"
    return _mock_language(t) if _LATIN.search(t) else "en"


QUESTION_WORDS = re.compile(
    r"\?|\b(kati|kaha|kahile|kasari|kina|ke\s+(cha|chha|ho))\b|"
    r"(कति|कहाँ|कहिले|कसरी|किन|कब|कितना|कितने|कैसे|कहाँ|क्या|केतना|कइसे|कहिया)",
    re.I)


def open_question(text: str | None) -> bool:
    """Did the message ask something? A question mark, or a question word in Nepali, Roman Nepali, Hindi or
    Bhojpuri."""
    return bool(text and QUESTION_WORDS.search(text))


# ---- promises ------------------------------------------------------------------------------
_OWNER = re.compile(r"\bowner\b|\bsahuji\b|\bmalik\b|साहुजी|साहु जी|मालिक|साहुजीले", re.I)
_WEEKDAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
PROMISES: dict[str, tuple[str, re.Pattern]] = {
    "delivery": ("promises a delivery time", re.compile(
        rf"\b(tomorrow|next[- ]day|same[- ]day|by ({_WEEKDAYS})|within \d+ (hours?|days?))\b|"
        r"\b(bholi|parsi)\b|भोलि|पर्सि|कल तक|कल ही|परसों|काल्ह", re.I)),
    "photos": ("says photos were or will be sent", re.compile(
        r"\b(sent|shared|attached|will send|we'll send|i'll send|sending)\b.{0,25}\b(photos?|pictures?|pics?|images?)\b|"
        r"\b(photos?|pictures?|pics?)\b.{0,25}\b(sent|attached|on (the|their) way|coming)\b|"
        r"photo.{0,25}(pathaeko|pathaisake|pathaunchhau|pathaidinchhau|pathaunechhau)|"
        r"फोटो.{0,25}(पठाएको|पठाइदिएको|पठाइदिएँ|पठाइसक|पठाउँछौं|पठाउनेछौं|पठाउँदैछौं|पठाइदिन्छौं|भेज दी|भेज दिए|भेजी है|भेजे हैं|भेजेंगे|"
        r"भेज रहे|भेज देंगे|भेज देले|भेजले|भेज देब|भेजब)", re.I)),
    "stock": ("claims something is in stock or running out", re.compile(
        r"\b(in stock|out of stock|available (now|today)|only \d+ (left|pieces?)|last (one|few|pieces?)|"
        r"selling (out|fast)|few left|limited stock|just arrived|new arrivals?)\b|"
        r"\b(we have|we've got)\b.{0,30}\b(designs?|collection|sarees?|stock|pieces?|lehengas?|kurtas?|shawls?)\b|"
        r"stock ma (chha|cha)|available (chha|cha)|baki (chha|cha)|rakheko chhau|"
        r"छिटो सकिन्छ|चाँडै सकिन्छ|selling fast|sakinchha chhito|chhito sakinchha|स्टकमा\s*(छ|छन्)|उपलब्ध\s*(छ|छन्|है|हैं|बा)|बाँकी\s*(छ|छन्)|मात्र बाँकी|सकिन लाग्यो|राखेका छौं|"
        r"स्टॉक में (है|हैं|बा)|बचे (हैं|है)|(ख़त्म|खत्म) होने वाल|आ गए हैं|आ गइल बा|बाचल बा", re.I)),
    "price": ("states a price", re.compile(
        r"(\brs\.?|\bnpr\b|रु\.?|₹)\s*[\d०-९][\d०-९,]*|[\d०-९][\d०-९,]*\s*(rupees|रुपैयाँ|रुपये|रुपया|\brupaiya\b)",
        re.I)),
    "discount": ("offers money off", re.compile(
        r"\bdiscount\w*|\b\d+\s*%\s*(off|chhut)|percent off|छुट|छूट|डिस्काउंट|\bchhut\b", re.I)),
}
_SENTENCES = re.compile(r"(?<=[.!?।])\s+")


def promises(message: str, backed: str, action_kind: str) -> list[tuple[str, str, str]]:
    """(kind, what it does, the words) for each claim or promise no fact or action backs. `backed`: the cited facts'
    values, lowercased. A discount is backed by an offer_discount (the money check and the owner's rules do the
    rest); a price by a cited fact holding that amount; stock, delivery times and photos by nothing Pheri has."""
    out = []
    for sentence in _SENTENCES.split(message or ""):
        if _OWNER.search(sentence):  # handed to the owner: "the owner will confirm the date" promises nothing
            continue
        for kind, (does, pattern) in PROMISES.items():
            m = pattern.search(sentence)
            if not m:
                continue
            if kind == "discount" and action_kind == "offer_discount":
                continue
            if kind == "price" and re.sub(r"\D", "", m.group(0)) and re.sub(r"\D", "", m.group(0)) in backed:
                continue
            out.append((kind, does, m.group(0).strip()))
    return list(dict.fromkeys(out))
