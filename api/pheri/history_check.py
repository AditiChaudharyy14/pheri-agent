"""Does a customer's message match their order history? A message that talks about an item they bought or are
waiting for ("the saree hasn't arrived", "cotton like before") must name a kind of item their orders hold.
Used by a test over every synthetic customer, and by synth to repair the night's histories."""

from __future__ import annotations

import re

CATEGORIES = {
    "saree": ("saree", "sari", "साडी", "साड़ी", "सारी", "dhaka", "banarasi", "बनारसी", "ढाका", "cotton", "कटन",
              "कॉटन", "सूती", "georgette", "जर्जेट"),
    "lehenga": ("lehenga", "लहंगा", "लेहेंगा"), "kurta": ("kurta", "कुर्ता"),
    "shawl": ("shawl", "pashmina", "पश्मिना", "सल"), "blouse": ("blouse", "ब्लाउज"),
}
FABRICS = {"cotton": ("cotton", "कटन", "कॉटन", "सूती", "suti"), "dhaka": ("dhaka", "ढाका"),
           "banarasi": ("banarasi", "बनारसी"), "georgette": ("georgette", "जर्जेट", "जॉर्जेट")}
# Words that tie a message to something they already bought or are waiting for.
OWN_ORDER = ("like before", "last time", "same as", "hasn't arrived", "not arrived", "pohor", "pahile", "पहिलेकै",
             "पिछली बार", "पिछला बेर", "वाली", "वाला", "आएको", "आइपुगेको", "नहीं आया", "ना आइल", "milena", "मिलेन",
             "रङ", "colour", "color", "torn", "च्यातिएको", "फटी", "फाटल", "size", "साइज", "पैसा फिर्ता", "return")


def _words(text: str) -> list[str]:
    return re.findall(r"[\wऀ-ॿ]+", (text or "").casefold())


def named(text: str, table: dict) -> set[str]:
    low, words = (text or "").casefold(), _words(text)
    return {k for k, ws in table.items() if any((w in words) if len(w) <= 3 else (w in low) for w in ws)}


AGAIN = ("like before", "last time", "same as", "pohor", "pahile", "पहिलेकै", "पिछली बार", "पिछला बेर", "वैसी", "ओइसन",
         "testai", "jastai", "जैसा", "जइसन")
PROBLEMS = ("late", "wrong_colour", "return_requested", "damaged")
CHOOSING = ("how do i choose", "कसरी छान्ने", "कैसे चुनें", "कैसे चुने", "kasari chhanne", "first time", "पहिलो पटक",
            "पहली बार")


def about_own_order(text: str) -> bool:
    """Does it talk about something they bought or are waiting for? (Asking how to choose a size does not.)"""
    low, words = (text or "").casefold(), _words(text)
    if any(c in low for c in CHOOSING):
        return False
    return any((w in words) if " " not in w and len(w) <= 5 else (w in low) for w in OWN_ORDER)


def mismatch(text: str, orders: list[dict]) -> str | None:
    """Why this message doesn't fit the customer's orders, or None. Only messages about their own order count."""
    if not about_own_order(text):
        return None
    low, words = (text or "").casefold(), _words(text)
    dated = sorted(orders, key=lambda o: o["date"])
    if any((w in words) if len(w) <= 5 else (w in low) for w in AGAIN):
        orders = dated[-1:]  # "like before", "same as last time": the last order on record
    elif problem := [o for o in dated if o["status"] in PROBLEMS]:
        orders = problem[-1:]  # a complaint is about the order that has the problem
    items = " ".join(o["items"] for o in orders).casefold()
    if not items:
        return "talks about an order, but they have none"
    kinds = named(text, CATEGORIES) - {"blouse"} if "blouse" not in named(text, CATEGORIES) else named(text, CATEGORIES)
    missing = [k for k in kinds if not named(items, {k: CATEGORIES[k]})]
    fabric = [f for f in named(text, FABRICS) if not named(items, {f: FABRICS[f]})]
    if missing or fabric:
        return f"names {', '.join(missing + fabric)}, but their orders hold: {items[:80]}"
    return None
