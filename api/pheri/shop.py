"""The shop's own knowledge, as facts Pheri can cite: data/synth/<business>/shop.json (synthetic).

facts_for(text, town, country) reads what a customer's newest message is about (delivery, size, stock, price, new
designs, photos, cash on delivery, an exchange) and returns only the shop facts that answer it, each with its
provenance ("shop:<section>"), so a receipt says "shop file". An answer may say only what these facts say; the
verify checks (facts, promises, the judge) hold it to them. What the file can't settle (a money decision, a refund, a
complaint) still goes to the owner.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from .synth import OUT
from .words import read_language

SHOP_FACTS = ("shop_delivery", "shop_cod", "shop_size_guide", "shop_stock", "shop_collection", "shop_returns")

TOWN_WORDS = {
    "Birgunj": ("birgunj", "बीरगंज", "वीरगञ्ज", "बिरगंज"), "Parwanipur": ("parwanipur", "परवानीपुर"),
    "Simara": ("simara", "सिमरा"), "Kalaiya": ("kalaiya", "कलैया"), "Hetauda": ("hetauda", "हेटौंडा", "हेटौडा"),
    "Janakpur": ("janakpur", "जनकपुर"), "Kathmandu": ("kathmandu", "काठमाडौं", "काठमांडू"),
    "Raxaul": ("raxaul", "रक्सौल"), "Motihari": ("motihari", "मोतिहारी"), "Bettiah": ("bettiah", "बेतिया"),
    "Sitamarhi": ("sitamarhi", "सीतामढ़ी", "सीतामढी"),
}
TOPICS = {
    "delivery": ("deliver", "delivery", "arrive", "reach", "ship", "डेलिभरी", "डिलीवरी", "पुग", "आइपुग", "पहुँच", "पहुंच",
                 "aaipug", "pug", "kahile", "कहिले", "कब", "कति दिन", "kati din", "कितने दिन", "ले आई", "आएगा"),
    "size": ("size", "साइज", "नाप", "naap", "measure"),
    "stock": ("stock", "स्टक", "स्टॉक", "available", "अझै", "ajhai", "still", "वैसी", "ओइसन", "testai", "same",
              "चाहियो", "चाहिए", "चाहीं", "chahiyo", "chahiye", "want", "need"),
    "price": ("price", "दाम", "daam", "कति पर्छ", "kati parchha", "कितना", "केतना", "how much", "मूल्य"),
    "designs": ("design", "डिजाइन", "डिज़ाइन", "collection", "कलेक्शन", "नयाँ", "नया", "नए", "naya", "new"),
    "photos": ("photo", "फोटो", "फ़ोटो", "picture", "pic"),
    "cod": ("cash on delivery", "क्यास अन डेलिभरी", "कैश ऑन डिलीवरी", "कैश ऑन", "cod", "cash"),
    "returns": ("exchange", "return", "साट", "साटेर", "satera", "बदल", "बदली", "दोसर"),
}


@lru_cache(maxsize=4)
def shop(business: str = "birgunj") -> dict:
    path = OUT / business / "shop.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _has(text: str, word: str) -> bool:
    """A single word matches whole words only (so "सल", a shawl, never matches inside "सलमा"); a phrase, anywhere."""
    if " " in word:
        return word in text
    return word in re.findall(r"[\wऀ-ॿ]+", text)


def topics(text: str) -> set[str]:
    t = (text or "").casefold()
    return {k for k, words in TOPICS.items() if any(_has(t, w) or (len(w) > 4 and w in t) for w in words)}


def _items(text: str, catalog: list[dict]) -> list[dict]:
    t = (text or "").casefold()
    scored = [(sum(_has(t, w) or (len(w) > 4 and w in t) for w in it["match"]), i, it) for i, it in enumerate(catalog)]
    return [it for n, _, it in sorted(scored, key=lambda x: (-x[0], x[1])) if n > 0][:3]


CATEGORY_WORDS = {"saree": ("saree", "sari", "साडी", "साड़ी", "सारी"), "lehenga": ("lehenga", "लहंगा", "लेहेंगा"),
                  "kurta": ("kurta", "कुर्ता"), "shawl": ("shawl", "pashmina", "पश्मिना"), "blouse": ("blouse", "ब्लाउज")}


def _category(text: str | None) -> str | None:
    t = (text or "").casefold()
    return next((c for c, words in CATEGORY_WORDS.items() if any(w in t for w in words)), None)


# Facts in the language the customer wrote: a Nepali, Hindi or Bhojpuri reply copies these names, never English ones.
LABELS = {"en": ("in stock", "photo", "collection", "from NPR {n}", "photos"),
          "ne-Latn": ("in stock", "photo", "collection", "from NPR {n}", "photos"),
          "ne": ("स्टकमा", "फोटो", "कलेक्सन", "NPR {n} देखि", "फोटो"),
          "hi": ("स्टॉक में", "फोटो", "कलेक्शन", "NPR {n} से", "फोटो"),
          "bho": ("स्टॉक में", "फोटो", "कलेक्शन", "NPR {n} से", "फोटो")}


def _name(it: dict, lang: str) -> str:
    return (it.get("names") or {}).get(lang) or it["name"]


def _item_line(it: dict, lang: str) -> str:
    stock_w, photo_w = LABELS.get(lang, LABELS["en"])[:2]
    count = "" if it["stock"] is None else (f"{it['stock']} {stock_w}, " if lang in ("en", "ne-Latn")
                                            else f"{stock_w} {it['stock']}, ")
    return f"{_name(it, lang)}: {count}NPR {it['price_npr']}, {photo_w} {it['photo']}"


def _collection_line(s: dict, fest: str, lang: str) -> str:
    items = [it for it in s["catalog"] if it["id"] in s["collections"][fest]]
    _, _, coll_w, from_w, photos_w = LABELS.get(lang, LABELS["en"])
    fest_name = (s.get("festival_names", {}).get(fest) or {}).get(lang) or fest.title()
    low = min(it["price_npr"] for it in items)
    return (f"{fest_name} {coll_w}: " + ", ".join(_name(it, lang) for it in items) + f"; {from_w.format(n=low)}; "
            f"{photos_w} " + ", ".join(it["photo"] for it in items) + ".")


def asked_town(text: str) -> str | None:
    t = (text or "").casefold()
    return next((town for town, words in TOWN_WORDS.items() if any(w in t for w in words)), None)


def facts_for(text: str | None, town: str | None, country: str | None, festival: str | None,
              business: str = "birgunj", last_item: str | None = None) -> tuple[dict, dict]:
    """The shop facts that answer this message, and their provenance. Nothing when the message asks nothing the file
    holds."""
    s = shop(business)
    if not s or not text:
        return {}, {}
    on = topics(text)
    lang = read_language(text)  # names and labels in the language of their message: no English product names
    items = _items(text, s["catalog"])
    if not items and on & {"stock", "price"} and last_item:
        # "Any more like last time?" names no item: their last order does, if it is the kind of thing they named.
        last = _items(last_item, s["catalog"])
        named = _category(text)
        items = [it for it in last if named is None or it["category"] == named]
    facts, prov = {}, {}
    where = asked_town(text) or town
    if ("delivery" in on or asked_town(text)) and where in s["delivery"]:
        d = s["delivery"][where]
        facts["shop_delivery"] = (f"{where}: {d['days']} day{'s' if d['days'] > 1 else ''}, "
                                  + ("free delivery" if not d["charge_npr"] else f"delivery charge NPR {d['charge_npr']}"))
        prov["shop_delivery"] = ["shop:delivery"]
    if "cod" in on:
        facts["shop_cod"], prov["shop_cod"] = s["cod"].get(s["delivery"].get(where, {}).get("country", country or "NP"),
                                                           s["cod"]["NP"]), ["shop:cod"]
    if "size" in on:
        facts["shop_size_guide"], prov["shop_size_guide"] = s["size_guide"], ["shop:size_guide"]
    if items and on & {"stock", "price", "photos", "designs", "size"}:
        facts["shop_stock"] = "; ".join(_item_line(it, lang) for it in items)
        prov["shop_stock"] = ["shop:catalog"]
    if on & {"designs", "photos"}:
        fests = s["collections"]
        fest = next((f for f in fests if f in (text or "").casefold() or _alias(text, f)), None) or festival
        if fest in fests:
            facts["shop_collection"] = _collection_line(s, fest, lang)
            prov["shop_collection"] = ["shop:collections"]
    if "returns" in on:
        facts["shop_returns"], prov["shop_returns"] = s["returns"], ["shop:returns"]
    return facts, prov


def _alias(text: str | None, festival: str) -> bool:
    from .words import FESTIVAL_ALIASES

    t = (text or "").casefold()
    return any(a.casefold() in t for a in FESTIVAL_ALIASES.get(festival, ()))
