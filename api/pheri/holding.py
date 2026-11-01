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
from .words import name_for
from .verify import _MONEY, MAX_MESSAGE_CHARS, Verification, _links, payload_sha

KIND = "holding_reply"
CHANNEL = "whatsapp"

# {name}: the customer's first name in the reply's script with the honorific (words.name_for); the sign-off is the
# shop's own for each language (words.SIGN_OFF).
TEMPLATES = {
    "ne": "नमस्ते {name}, हजुरको सन्देश पाइयो। साहुजीले आज बिहान आफैं जवाफ दिनुहुन्छ। – बिरगंज साडी घर",
    "ne-Latn": "Namaste {name}, hajur ko sandesh paiyo. Sahuji le aaja bihana aafai jawaf dinuhunchha. "
               "– Birgunj Saree Ghar",
    "hi": "नमस्ते {name}, आपका संदेश मिल गया। साहुजी आज सुबह खुद जवाब देंगे। – बिरगंज साड़ी घर",
    "bho": "प्रणाम {name}, रउआ के संदेस मिल गइल। साहुजी आजु भोरे खुदे जवाब दिहें। – बिरगंज साड़ी घर",
    "en": "Hi {name}, we got your message. The owner will reply to you personally this morning. – Birgunj Saree Ghar",
}
# A voice note no model can read: never a word about what it says, only that it came and the owner will listen.
VOICE_TEMPLATES = {
    "ne": "नमस्ते {name}, आवाज सन्देश पाइयो, साहुजीले सुनेर जवाफ दिनुहुन्छ। – बिरगंज साडी घर",
    "ne-Latn": "Namaste {name}, awaj sandesh paiyo, sahuji le sunera jawaf dinuhunchha. – Birgunj Saree Ghar",
    "hi": "नमस्ते {name}, आपका आवाज़ संदेश मिल गया, साहुजी सुनकर जवाब देंगे। – बिरगंज साड़ी घर",
    "bho": "प्रणाम {name}, रउआ के आवाज संदेस मिलल, साहुजी सुन के जवाब दिहें। – बिरगंज साड़ी घर",
    "en": "Hi {name}, we got your voice note. The owner will listen and reply. – Birgunj Saree Ghar",
}
NO_JUDGE = "written by code from a fixed template: it says nothing about the customer, so no judge is asked"


def text_for(business: str, first_name: str, language: str | None, templates: dict | None = None) -> tuple[str, str]:
    """(language used, message). An unknown language gets English."""
    templates = templates or TEMPLATES
    lang = language if language in templates else "en"
    return lang, templates[lang].format(name=name_for(first_name, lang))


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


def send_holding_reply(store, ctx: CheckContext, customer_key: str, first_name: str, language: str | None,
                       templates: dict | None = None, why: str | None = None) -> dict:
    """Store the holding reply and send it (at the end of quiet hours) if every check passes; else it is blocked."""
    lang, message = text_for(ctx.business, first_name, language, templates)
    action = ProposedAction(kind=KIND, channel=CHANNEL, message=message)
    action.send_at = next_send_time(active_rules(store), action, ctx)
    v = verify_template(action, ctx, store, lang)
    payload = {"kind": KIND, "channel": CHANNEL, "discount_pct": None, "message": message, "language": lang,
               "send_at": action.send_at.isoformat() if action.send_at else None, "written_by": "code",
               "verification": {**v.record(), "note": NO_JUDGE}}
    why = why or "Their message looked like an attack: the owner replies in person; this fixed reply says so."
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
