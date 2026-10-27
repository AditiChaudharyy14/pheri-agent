"""Private mode: which of a business's model steps run on Muse Spark Open instead of the Meta Model API.

Muse Spark Open is Meta's open-weight model, served by a partner (Baseten), self-hostable. Steps:
  guard    reading inbound replies          (guard.py)
  profile  reading a customer's messages    (profile.py)
  decide   choosing the next best action    (decide.py)
  rules    compiling the owner's rules      (rules.py)

    set_private_mode(store, full=True, by="owner:aditi")   # every step: nothing goes to the Meta Model API
    with private_fence(store, llm):                        # code refuses any Meta call inside, before sending
        decide_customer(ds, key, store, llm)

Partial modes (say, only the guard) are allowed; only full private mode fences the Meta API off.
On Baseten every step runs at reasoning_effort "low", as the private-mode brief says: Muse Spark Open
always reasons, and at medium it used up 8000 output tokens before answering a decision.
"""

from __future__ import annotations

from contextlib import nullcontext

PRIVATE_MODE = "private_mode"  # the business setting
STEPS = ("guard", "profile", "decide", "rules")
PRIVATE_PROVIDER = "baseten"
PRIVATE_EFFORT = "low"


def private_mode(store) -> dict[str, bool]:
    """Which steps run privately. Off by default: the Meta Model API."""
    saved = store.get_setting(PRIVATE_MODE, {}) or {}
    return {step: bool(saved.get(step)) for step in STEPS}


def set_private_mode(store, *, by: str, full: bool = False, **steps: bool) -> dict[str, bool]:
    """Set every step at once: steps not named are off, unless full=True turns them all on."""
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise ValueError(f"unknown private-mode steps {sorted(unknown)}; the steps are {STEPS}")
    after = {step: bool(full or steps.get(step)) for step in STEPS}
    with store.tx():
        before = private_mode(store)
        store.set_setting(PRIVATE_MODE, after, by)
        store.audit(by, "private_mode_changed", "setting", PRIVATE_MODE, {"from": before, "to": after})
    return after


def fully_private(store) -> bool:
    return all(private_mode(store).values())


def provider_for(store, step: str) -> str:
    return PRIVATE_PROVIDER if private_mode(store)[step] else "meta"


def private_fence(store, llm):
    """Full private mode: inside this block, any model call that is not to Baseten is refused before it is sent."""
    return llm.only(PRIVATE_PROVIDER) if fully_private(store) else nullcontext()

