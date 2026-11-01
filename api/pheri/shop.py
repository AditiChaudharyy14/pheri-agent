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

SHOP_FACTS = ("shop_delivery", "shop_cod", "shop_size_guide", "shop_stock", "shop_collection", "shop_returns",
              "shop_last_order")

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
# Money is "रु" in Devanagari and "Rs" in Roman letters, never "NPR". A retail customer hears "in stock"; only a
# wholesale buyer is told how many. No photo id is ever in a fact: code attaches the photos (photos_for).
DEVANAGARI = ("ne", "hi", "bho")
STOCK_WORDS = {"en": "in stock", "ne-Latn": "stock ma chha", "ne": "स्टकमा छ", "hi": "स्टॉक में है", "bho": "स्टॉक में बा"}
# Counts always carry their unit: pieces for an item, lots for a wholesale lot (a lot holds N pieces), so a reply
# never says "the lot is ready" next to a smaller number that was really pieces.
COUNT_WORDS = {"en": "{n} pieces in stock", "ne-Latn": "stock ma {n} wota", "ne": "स्टकमा {n} वटा",
               "hi": "स्टॉक में {n} पीस", "bho": "स्टॉक में {n} गो"}
LOT_WORDS = {"en": "{n} lots in stock", "ne-Latn": "stock ma {n} lot", "ne": "स्टकमा {n} लट",
             "hi": "स्टॉक में {n} लॉट", "bho": "स्टॉक में {n} लॉट"}
INR_PER_NPR = 1 / 1.6  # the fixed rate for customers in India: रु 2400 (₹1500). Code converts; the model copies.
COLLECTION = {"en": "{f} collection: {items}; from {money}", "ne-Latn": "{f} collection: {items}; {money} dekhi",
              "ne": "{f} कलेक्सन: {items}; {money} देखि", "hi": "{f} कलेक्शन: {items}; {money} से",
              "bho": "{f} कलेक्शन: {items}; {money} से"}
DELIVERY = {"en": ("{t}: {d} day{s}, delivery charge {money}", "{t}: {d} day{s}, free delivery"),
            "ne-Latn": ("{t}: {d} din, delivery charge {money}", "{t}: {d} din, delivery nishulka"),
            "ne": ("{t}: {d} दिन, डेलिभरी शुल्क {money}", "{t}: {d} दिन, डेलिभरी निःशुल्क"),
            "hi": ("{t}: {d} दिन, डिलीवरी चार्ज {money}", "{t}: {d} दिन, डिलीवरी मुफ़्त"),
            "bho": ("{t}: {d} दिन, डिलीवरी चार्ज {money}", "{t}: {d} दिन, डिलीवरी मुफ्त")}
LAST_ORDER = {"en": "Last order on record: {items}, {money}", "ne-Latn": "Pachhillo order: {items}, {money}",
              "ne": "पछिल्लो अर्डर: {items}, {money}", "hi": "पिछला ऑर्डर: {items}, {money}",
              "bho": "पिछला ऑर्डर: {items}, {money}"}


def money(n: int | float, lang: str, india: bool = False) -> str:
    """रु in Devanagari, Rs in Roman letters; for a customer in India the rupee amount too, converted here."""
    npr = f"रु {n:g}" if lang in DEVANAGARI else f"Rs {n:g}"
    return f"{npr} (₹{round(n * INR_PER_NPR)})" if india and n else npr


def _lang(lang: str) -> str:
    return lang if lang in STOCK_WORDS else "en"


def _name(it: dict, lang: str) -> str:
    return (it.get("names") or {}).get(lang) or it["name"]


def _item_line(it: dict, lang: str, wholesale: bool, india: bool = False) -> str:
    lang = _lang(lang)
    lot = it["id"].startswith("BSG-W")  # a wholesale lot: counted in lots
    stock = "" if it["stock"] is None else (
        (LOT_WORDS if lot else COUNT_WORDS)[lang].format(n=it["stock"]) if wholesale else STOCK_WORDS[lang]) + ", "
    return f"{_name(it, lang)}: {stock}{money(it['price_npr'], lang, india)}"


def _lot_for(it: dict, s: dict) -> dict | None:
    """The wholesale lot of this item, if the shop sells one ("Cotton saree" -> "Cotton saree bundle x20")."""
    base = it["name"].casefold()
    names = [n.casefold() for n in (it.get("order_names") or [])] + [base]
    return next((b for b in s.get("bundles", []) if any(b["name"].casefold().startswith(n) for n in names)), None)


def _collection_line(s: dict, fest: str, lang: str, india: bool = False) -> str:
    lang = _lang(lang)
    items = [it for it in s["catalog"] if it["id"] in s["collections"][fest]]
    fest_name = (s.get("festival_names", {}).get(fest) or {}).get(lang) or fest.title()
    return COLLECTION[lang].format(f=fest_name, items=", ".join(_name(it, lang) for it in items),
                                   money=money(min(it["price_npr"] for it in items), lang, india))


def _by_order_name(s: dict, name: str) -> dict | None:
    """The catalogue item or wholesale lot an order line names ("Cotton saree bundle x20", "Banarasi silk saree")."""
    for it in s.get("bundles", []) + s["catalog"]:
        if name.strip().casefold() in [it["name"].casefold(), *(n.casefold() for n in it.get("order_names", []))]:
            return it
    return None


def photos_for(prov: list[str], business: str = "birgunj") -> list[dict]:
    """The shop's own photos of the items a cited fact names (its provenance "shop:catalog:<ids>")."""
    s = shop(business)
    by_id = {it["id"]: it for it in s.get("catalog", []) + s.get("bundles", [])}
    ids = [i for ref in prov if ref.startswith(("shop:catalog:", "shop:collections:", "shop:last_order:"))
           for i in ref.split(":", 2)[2].split(",") if i in by_id]
    out, seen = [], set()
    for i in ids:
        ph = by_id[i]["photo"]
        if ph not in seen:
            seen.add(ph)
            out.append({"photo": ph, "item": by_id[i]["name"], "src": f"/catalog/{ph}.png"})
    return out


def asked_town(text: str) -> str | None:
    t = (text or "").casefold()
    return next((town for town, words in TOWN_WORDS.items() if any(w in t for w in words)), None)


def facts_for(text: str | None, town: str | None, country: str | None, festival: str | None,
              business: str = "birgunj", last_item: str | None = None, wholesale: bool = False,
              last_order: dict | None = None) -> tuple[dict, dict]:
    """The shop facts that answer this message, and their provenance. Nothing when the message asks nothing the file
    holds. `last_order`: their last order on record, for "the same as last time"."""
    from .words import reorder_request

    s = shop(business)
    if not s or not text:
        return {}, {}
    on = topics(text)
    lang = _lang(read_language(text))  # in the language of their message: no English product names
    items = _items(text, s["catalog"])
    if not items and on & {"stock", "price"} and last_item:
        # "Any more like last time?" names no item: their last order does, if it is the kind of thing they named.
        last = _items(last_item, s["catalog"])
        named = _category(text)
        items = [it for it in last if named is None or it["category"] == named]
    facts, prov = {}, {}
    where = asked_town(text) or town
    india = (s["delivery"].get(where, {}).get("country") or country) == "IN"  # prices in ₹ too, converted by code
    if wholesale:  # a wholesale buyer is quoted the lot, counted in lots, not the pieces
        items = [_lot_for(it, s) or it for it in items]
        items = list({it["id"]: it for it in items}.values())
    if ("delivery" in on or asked_town(text)) and where in s["delivery"]:
        d = s["delivery"][where]
        t = s.get("town_names", {}).get(where, where) if lang in DEVANAGARI else where
        paid, free = DELIVERY[lang]
        facts["shop_delivery"] = (paid if d["charge_npr"] else free).format(
            t=t, d=d["days"], s="s" if d["days"] > 1 else "", money=money(d["charge_npr"], lang, india))
        prov["shop_delivery"] = ["shop:delivery"]
    if "cod" in on:
        rule = s["cod"].get(s["delivery"].get(where, {}).get("country", country or "NP"), s["cod"]["NP"])
        facts["shop_cod"], prov["shop_cod"] = rule.get(lang, rule["en"]), ["shop:cod"]
    if "size" in on:
        facts["shop_size_guide"], prov["shop_size_guide"] = s["size_guide"].get(lang, s["size_guide"]["en"]),             ["shop:size_guide"]
    if items and on & {"stock", "price", "photos", "designs", "size"}:
        facts["shop_stock"] = "; ".join(_item_line(it, lang, wholesale, india) for it in items)
        prov["shop_stock"] = ["shop:catalog:" + ",".join(it["id"] for it in items)]
    if on & {"designs", "photos"}:
        fests = s["collections"]
        fest = next((f for f in fests if f in (text or "").casefold() or _alias(text, f)), None) or festival
        if fest in fests:
            facts["shop_collection"] = _collection_line(s, fest, lang, india)
            prov["shop_collection"] = ["shop:collections:" + ",".join(fests[fest])]
    if "returns" in on:
        facts["shop_returns"], prov["shop_returns"] = s["returns"].get(lang, s["returns"]["en"]), ["shop:returns"]
    if last_order and reorder_request(text):  # "the same lot as last time": what the last order on record holds
        lines = [_by_order_name(s, n) for n in last_order["items"].split(";")]
        known = [it for it in lines if it]
        names = ", ".join(_name(it, lang) for it in known) or last_order["items"]
        facts["shop_last_order"] = LAST_ORDER[lang].format(items=names,
                                                           money=money(last_order["total_npr"], lang, india))
        if known:
            facts["shop_last_order"] += "; " + "; ".join(_item_line(it, lang, wholesale, india) for it in known)
        prov["shop_last_order"] = ["shop:last_order:" + ",".join(it["id"] for it in known)]
    return facts, prov


def _alias(text: str | None, festival: str) -> bool:
    from .words import FESTIVAL_ALIASES

    t = (text or "").casefold()
    return any(a.casefold() in t for a in FESTIVAL_ALIASES.get(festival, ()))
