"""Slop vs Pheri: what a plain AI follow-up says, and which of Pheri's checks it fails, sentence by sentence.

    out = compare(ds, key, store, llm, now)

The plain draft is a real model reply (Muse Spark 1.3, recorded like every other call), written the way a shop
would ask any chatbot: the customer's own messages and "write a friendly WhatsApp follow-up". No rules, no facts by
id, no reasons. Then the same verify_draft Pheri's own drafts go through reads it, and each failed check is pinned
to the sentence that broke it, with the reason in the owner's words. Nothing here is hand-written to fail.
"""

from __future__ import annotations

import re
from datetime import datetime

from .actions import CHANNELS, ProposedAction
from .journey import stage
from .llm import LLM, register_mock
from .profile import CUSTOMER_WRITTEN, build_profile
from .rules import CheckContext
from .synth import BUSINESS_NAMES
from .verify import Draft, context, verify_draft

PURPOSE = "plain_draft"
MAX_OUTPUT_TOKENS = 1500
SYSTEM = "You write WhatsApp messages for a small shop's customers. Be warm, persuasive and helpful."
SENTENCE_END = re.compile(r"(?<=[.!?।])\s+|\n+")  # a dot inside a link or a price does not end a sentence
MONEY = re.compile(r"\d+\s*%|\bdiscount|\boff\b|\bfree\b|\brefund|छुट|छूट|मुफ्त|फ्री|निःशुल्क|chhut", re.I)
URL = re.compile(r"https?://\S+|www\.\S+|\b\S+\.(com|np|in|net|org)\b", re.I)
GENDERED = re.compile(r"\b(he|him|his|she|her|hers|sir|madam|ma'am|didi|bhaiya|dai|bahini)\b", re.I)

# Each check, in the owner's words: what the plain draft did that Pheri never may.
PLAIN = {
    "evidence": "Gives no reason from the customer's record: nothing it says is tied to an order or a message.",
    "facts": "Says {what}, which nothing in the shop's records backs.",
    "money": "Offers money off. Only an owner-approved discount may, and this one wasn't.",
    "rules": "Breaks one of your rules: {why}.",
    "links": "Sends a link that isn't the shop's own.",
    "pronouns": "Guesses how the customer wants to be addressed.",
    "address": "Talks about the customer instead of to them, or names them outside the greeting.",
    "one_problem": "Brings up something other than the reason Pheri is writing.",
    "language": "Writes in a different language from the one the customer writes in.",
    "length": "Too long for a WhatsApp message.",
    "schema": "Gives you no reason: why this, why now.",
    "middle_step": "Picks a step that doesn't fit this kind of customer.",
    "tools": "Tries to use a tool Pheri doesn't have.",
}


def plain_draft(ds, key: str, llm: LLM) -> tuple[str, dict]:
    c = ds.customers[key]
    said = [s.text for s in sorted(c.sources, key=lambda s: s.at or "") if s.kind in CUSTOMER_WRITTEN and s.text]
    ask = (f"Shop: {BUSINESS_NAMES[ds.business]}. Customer: {c.name}.\n"
           f"Their recent messages:\n" + "\n".join(f"- {t}" for t in said[-5:]) +
           "\n\nWrite a short, friendly WhatsApp follow-up to this customer that gets them to buy again.")
    r = llm.complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": ask}], purpose=PURPOSE,
                     effort="low", max_tokens=MAX_OUTPUT_TOKENS, data_class=ds.data_class)
    return (r.text or "").strip(), {"model": r.model, "recorded": r.recorded, "cost_usd": r.cost_usd}


def _offending(check: dict, sentences: list[str]) -> list[int]:
    """Which sentences broke this check; [] means the whole draft did (no single sentence to strike)."""
    name, reason = check["name"], " ".join(check.get("reasons") or [check.get("reason") or ""])
    if name == "facts":
        nums = re.findall(r"writes ([^,]+?),", reason)
        return [i for i, s in enumerate(sentences) if any(n.strip() in s for n in nums)]
    if name in ("money", "rules") and any(MONEY.search(s) for s in sentences):
        return [i for i, s in enumerate(sentences) if MONEY.search(s)]
    if name == "links":
        return [i for i, s in enumerate(sentences) if URL.search(s)]
    if name == "pronouns":
        return [i for i, s in enumerate(sentences) if GENDERED.search(s)]
    return []


def compare(ds, key: str, store, llm: LLM, now: datetime) -> dict:
    """The plain draft, checked exactly as Pheri's drafts are, with each failure pinned to its sentence."""
    text, meta = plain_draft(ds, key, llm)
    p = build_profile(ds, key, llm, now.date())
    j = stage(ds.business, p.facts, p.provenance.get("facts"))
    d = Draft(ProposedAction(kind="send_checkin", channel=CHANNELS[ds.business][0], message=text, send_at=now),
              "", "", [], [])
    v = verify_draft(d, context(p, j, CheckContext(ds.business, p.facts, now), store, llm))
    sentences = [x.strip() for x in SENTENCE_END.split(text) if x.strip()]
    struck: dict[int, list[str]] = {}
    whole: list[str] = []
    failed = []
    for c in v.checks:
        if not c["applies"] or c["passed"]:
            continue
        reason = " ".join(c.get("reasons") or [c.get("reason") or ""])
        nums = ", ".join(n.strip() for n in re.findall(r"writes ([^,]+?),", reason)) or "things"
        plain = PLAIN.get(c["name"], reason).format(what=nums, why=reason)
        failed.append({"check": c["name"], "hard": c["name"] not in ("address", "one_problem", "length", "language",
                                                                      "middle_step"), "plain": plain, "detail": reason})
        hits = _offending(c, sentences)
        for i in hits:
            struck.setdefault(i, []).append(plain)
        if not hits:
            whole.append(plain)
    return {"customer": {"key": key, "name": ds.customers[key].name, "stage": j.stage},
            "plain": {"text": text, **meta,
                      "sentences": [{"text": s, "struck": i in struck, "reasons": struck.get(i, [])}
                                    for i, s in enumerate(sentences)],
                      "whole_draft": whole, "failed": failed, "passed": v.passed,
                      "could_send": not failed}}


def _mock_plain(messages, schema) -> str:
    first = messages[-1]["content"].split("Customer: ", 1)[1].split()[0]
    return (f"Hi {first} didi! We miss you at the shop. Come back this week and get 20% off everything, "
            f"plus free delivery on orders over Rs 3000. Shop now at www.sareedeals.com")


register_mock(PURPOSE, _mock_plain)
