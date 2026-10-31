"""The holding reply: what a customer hears when their message looked like an attack.

No model writes a word to them. The owner gets the escalation (autonomy.escalate); the customer gets a fixed
reply, written here in code, in their language: their message came in, and the owner replies in person. It still
passes the code checks that apply (the owner's rules, quiet hours and do-not-contact included, language, length,
links, money), goes out at the end of the customer's quiet hours like everything else, and only through the send
step's gate (a passed verification for exactly this text). The judge is not asked: the text makes no claim about the
customer, so there is nothing for it to check, and the stored verification says so.

The Nepali, Roman Nepali, Hindi and Bhojpuri lines wait for a native speaker's review (Aditi).
"""

from __future__ import annotations

from .actions import ProposedAction
from .autonomy import _execute
from .rules import CheckContext, active_rules, check, next_send_time
from .synth import BUSINESS_NAMES
from .verify import _MONEY, MAX_MESSAGE_CHARS, Verification, _links, payload_sha

KIND = "holding_reply"
CHANNEL = "whatsapp"

TEMPLATES = {
    "ne": "नमस्ते {first}, हजुरको सन्देश पाइयो। साहुजीले आज बिहान आफैं जवाफ दिनुहुन्छ। - {shop} टिम",
    "ne-Latn": "Namaste {first}, hajur ko sandesh paiyo. Sahuji le aaja bihana aafai jawaf dinuhunchha. - {shop} team",
    "hi": "नमस्ते {first}, आपका संदेश मिल गया। साहुजी आज सुबह खुद जवाब देंगे। - {shop} टीम",
    "bho": "प्रणाम {first}, रउआ के संदेस मिल गइल। साहुजी आज भोरे खुदे जवाब दिहें। - {shop} टीम",
    "en": "Hi {first}, we got your message. The owner will reply to you personally this morning. - {shop} team",
}
NO_JUDGE = "written by code from a fixed template: it says nothing about the customer, so no judge is asked"


def text_for(business: str, first_name: str, language: str | None) -> tuple[str, str]:
    """(language used, message). An unknown language gets English."""
    lang = language if language in TEMPLATES else "en"
    return lang, TEMPLATES[lang].format(first=first_name, shop=BUSINESS_NAMES[business])


def verify_template(action: ProposedAction, ctx: CheckContext, store, language: str) -> Verification:
    """The code checks that apply to a fixed text. Nothing here is a model."""
    from .guard import _mock_language as detect

    rules = active_rules(store)
    rule = check(rules, action, ctx)
    msg = action.message
    lang_problems = []
    if language in ("ne", "hi", "en") and (got := detect(msg)) != language:
        lang_problems = [f"the message reads as {got!r}, but the customer writes in {language!r}"]
    plan = [
        ("rules", rule.violations),
        ("template", []),
        ("language", lang_problems),
        ("length", [f"the message is {len(msg)} characters"] if len(msg) > MAX_MESSAGE_CHARS else []),
        ("links", _links(ctx.business, msg)),
        ("money", ["a holding reply never offers money"] if _MONEY.search(msg) else []),
    ]
    checks = [{"name": n, "applies": True, "passed": not r, "reasons": r} for n, r in plan]
    checks[1]["note"] = NO_JUDGE
    v = Verification(False, checks, rule_check=rule.as_dict(),
                     sha=payload_sha(action.kind, action.channel, action.discount_pct, msg))
    v.reasons = [f"{c['name']}: {r}" for c in checks for r in c["reasons"]]
    v.passed = not v.reasons
    v.caught_by = None if v.passed else "code"
    return v


def send_holding_reply(store, ctx: CheckContext, customer_key: str, first_name: str, language: str | None) -> dict:
    """Store the holding reply and send it (at the end of quiet hours) if every check passes; else it is blocked."""
    lang, message = text_for(ctx.business, first_name, language)
    action = ProposedAction(kind=KIND, channel=CHANNEL, message=message)
    action.send_at = next_send_time(active_rules(store), action, ctx)
    v = verify_template(action, ctx, store, lang)
    payload = {"kind": KIND, "channel": CHANNEL, "discount_pct": None, "message": message, "language": lang,
               "send_at": action.send_at.isoformat() if action.send_at else None, "written_by": "code",
               "verification": {**v.record(), "note": NO_JUDGE}}
    why = "Their message looked like an attack: the owner replies in person; this fixed reply says so."
    with store.tx():
        status = "approved" if v.passed else "blocked"
        aid = store.add_action(customer_key, KIND, payload, why, [], "act_alone", v.rule_check, status)
        store.audit("pheri", "holding_reply", "action", aid,
                    {"customer": customer_key, "language": lang, "passed": v.passed, "reasons": v.reasons})
        if v.passed:
            _execute(store, aid, ctx.now, "pheri")
    return store.get_action(aid)


def holding_reply_for(store, customer_key: str) -> dict | None:
    return next((a for a in store.actions(customer_key) if a["kind"] == KIND), None)
