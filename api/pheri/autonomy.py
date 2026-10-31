"""The autonomy dial and the approval queue. What happens to an action after Pheri decides it.

Per action type the owner picks one mode:
  suggest    Pheri shows the action; the owner does it, or not. Pheri never carries it out.
  ask_owner  Pheri queues it for approval and carries it out only once approved.
  act_alone  Pheri carries it out straight away.

Before any of that, submit() verifies the draft (verify.verify_draft: code checks, then the judge) and
runs the rule check; a blocked action goes nowhere, and a draft that failed verification goes to the
owner's queue with the reasons, never out. The send step, _execute(), refuses any customer-facing action
whose stored verification did not pass for exactly the payload being sent, so no path (acting alone,
an owner's approval) can send an unverified message. The one exception is an owner's override, and only
of soft checks (verify.SOFT_CHECKS): the owner read the draft and sends it anyway; the audit log records
who, when, which checks, and the exact text. Hard checks (rules, invented numbers, money, unknown tools,
...) cannot be overridden by anyone, and that holds for every action Pheri drafted, an owner task included:
a task with an invented number is not carried out either.
Approving re-runs the rule check, because rules, limits and the clock may have moved since Pheri asked.
Every step is written to the audit log. Delivery is simulated for now: "executed" means recorded
as done, and nothing is sent to anyone yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .actions import BUSINESS_ACTIONS, CATALOG, ESCALATE, ProposedAction
from .rules import CheckContext, active_rules, check, next_send_time
from .verify import Draft, VerifyContext, override_line, payload_sha, verify_draft

MODES = ("suggest", "ask_owner", "act_alone")  # from least to most autonomous
DEFAULT_MODE = "ask_owner"
DEFAULT_MODES = {"task_for_owner": "act_alone"}  # internal: it only puts a task on the owner's list
# Human sign-off by stakes, per business: the night shift sends safe nudges on its own (still verified, still inside
# the rules, still after quiet hours), and anything that changes what a customer pays waits for the owner.
BUSINESS_MODES = {"birgunj": {"send_reminder": "act_alone", "recommend_product": "act_alone", "offer_reorder": "act_alone",
                              "send_help": "act_alone", "send_checkin": "act_alone", "offer_discount": "ask_owner"}}


LATE_FOR_OWNER_DAYS = 7  # an order this late: the customer hears from the owner, not from Pheri alone


def owner_reason(facts: dict) -> str | None:
    """Why this customer waits for the owner whatever the action: money talk, or an order very late. Counted in
    code from the facts; None when Pheri may act as the dial says."""
    if facts.get("asks_about_money"):
        return "They asked about money (a rate, a refund or money off): yours to decide."
    if (facts.get("days_late") or 0) >= LATE_FOR_OWNER_DAYS:
        return f"Their order is {facts['days_late']} days late: a word from you lands better than one from Pheri."
    return None


def mode_for(store, kind: str, saved: dict[str, str] | None = None) -> str:
    saved = store.autonomy_modes() if saved is None else saved
    return saved.get(kind, BUSINESS_MODES.get(store.business, {}).get(kind, DEFAULT_MODES.get(kind, DEFAULT_MODE)))


def modes(store) -> dict[str, str]:
    saved = store.autonomy_modes()
    return {k: mode_for(store, k, saved) for k in BUSINESS_ACTIONS[store.business] if k != "no_action"}


def set_mode(store, kind: str, mode: str, by: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if kind not in BUSINESS_ACTIONS[store.business] or kind == "no_action":
        raise ValueError(f"{kind!r} is not an action {store.business} can set")
    with store.tx():
        before = mode_for(store, kind)
        store.set_autonomy(kind, mode, by)
        store.audit(by, "autonomy_changed", "action_kind", kind, {"from": before, "to": mode})


def at_most(mode: str, cap: str | None) -> str:
    return mode if cap is None else MODES[min(MODES.index(mode), MODES.index(cap))]


def _payload(a: ProposedAction) -> dict:
    return {"channel": a.channel, "discount_pct": a.discount_pct, "message": a.message,
            "send_at": a.send_at.isoformat() if a.send_at else None}


def submit(store, customer_key: str, draft: Draft, *, verify: VerifyContext, cap: str | None = None,
           actor: str = "pheri", cap_reason: str | None = None) -> dict:
    """Verify the draft, check the rules in code, then the dial. Returns the stored action. `cap` limits the mode.
    verify_draft runs here, whoever calls: the model has no way to skip it or to call it."""
    action, ctx = draft.action, verify.ctx
    t = CATALOG.get(action.kind)
    v = verify_draft(draft, verify)  # before the transaction: the judge is a model call
    action = action.model_copy(update={"send_at": next_send_time(active_rules(store), action, ctx)})  # after quiet hours
    payload = {**_payload(action), "verification": v.record()}
    if cap_reason:
        payload["waits_for_owner"] = cap_reason
    with store.tx():  # rules, dial and writes from one consistent view
        result = check(active_rules(store), action, ctx)
        mode = at_most(mode_for(store, action.kind), cap if t and t.customer_facing else None)
        if not result.allowed:
            aid = store.add_action(customer_key, action.kind, payload, draft.why, v.evidence, None,
                                   result.as_dict(), "blocked")
            store.audit(actor, "rule_blocked", "action", aid,
                        {"customer": customer_key, "kind": action.kind, "violations": result.violations})
            return store.get_action(aid)
        if not v.passed:  # never sent: a person reads it, with the reasons
            aid = store.add_action(customer_key, action.kind, payload, draft.why, v.evidence, "ask_owner",
                                   result.as_dict(), "awaiting_approval")
            pid = store.add_approval(aid)
            store.audit(actor, "verify_failed", "action", aid,
                        {"customer": customer_key, "kind": action.kind, "caught_by": v.caught_by,
                         "reasons": v.reasons, "approval_id": pid})
            return store.get_action(aid)
        status = {"suggest": "suggested", "ask_owner": "awaiting_approval", "act_alone": "approved"}[mode]
        aid = store.add_action(customer_key, action.kind, payload, draft.why, v.evidence, mode, result.as_dict(),
                               status)
        store.audit(actor, "verified", "action", aid, {"customer": customer_key, "sha": v.sha,
                                                       "code_checks": v.code_checks, "judge": v.judge_ran})
        store.audit(actor, "rule_passed", "action", aid, {"customer": customer_key, "kind": action.kind})
        if mode == "suggest":
            store.audit(actor, "suggested", "action", aid, {"customer": customer_key})
        elif mode == "ask_owner":
            pid = store.add_approval(aid)
            store.audit(actor, "approval_requested", "action", aid, {"approval_id": pid, "customer": customer_key})
        else:
            _execute(store, aid, ctx.now, actor)
        return store.get_action(aid)


def escalate(store, customer_key: str, reason: str, details: dict, actor: str = "pheri") -> dict:
    """Put a person in the loop: an item in the approval queue, never an action toward the customer."""
    with store.tx():
        aid = store.add_action(customer_key, ESCALATE, {"reason": reason, **details}, reason, [], "ask_owner",
                               {"allowed": True, "results": []}, "awaiting_approval")
        pid = store.add_approval(aid)
        store.audit(actor, "escalated", "action", aid, {"customer": customer_key, "approval_id": pid, "reason": reason})
        return store.get_action(aid)


def open_escalation(store, customer_key: str) -> dict | None:
    """An escalation the owner has not dealt with yet: Pheri holds off this customer until then."""
    return next((a for a in store.actions(customer_key)
                 if a["kind"] == ESCALATE and a["status"] == "awaiting_approval"), None)


def verified_to_send(action: dict, override: dict | None = None) -> bool:
    """The send step's gate, for every action Pheri drafted (customer-facing or an owner task): it is carried
    out only if its stored verification passed for exactly this payload (kind, channel, discount, message), or
    an owner overrode every check it failed, all of them soft, for exactly this payload. Only an action code
    made itself, with no draft behind it (an escalation), has no verification, and it never reaches a customer."""
    t = CATALOG.get(action["kind"])
    p = action["payload"]
    v = p.get("verification")
    if v is None:
        return not (t and t.customer_facing)
    sha = payload_sha(action["kind"], p.get("channel"), p.get("discount_pct"), p.get("message"))
    if v.get("passed") is True:
        return v.get("sha") == sha
    return (override is not None and v.get("overridable") is True and v.get("hard_failed") == []
            and override.get("sha") == sha == v.get("sha")
            and set(v.get("soft_failed") or ["?"]) <= set(override.get("overridden") or []))


def _execute(store, action_id: str, now: datetime, actor: str, override: dict | None = None,
             send_at: datetime | None = None) -> bool:
    """`send_at`: when it may go out (the end of quiet hours); by default, the time stored with the action."""
    action = store.get_action(action_id)
    if not verified_to_send(action, override):
        store.set_action(action_id, "blocked")
        store.audit("pheri", "send_refused", "action", action_id,
                    {"customer": action["customer_key"], "reason": "not verified: Pheri never sends an unverified draft",
                     "verification": (action["payload"].get("verification") or {}).get("reasons", [])})
        return False
    when = send_at or (datetime.fromisoformat(action["payload"]["send_at"]) if action["payload"].get("send_at") else None)
    if when and when > now:  # verified and allowed, waiting for the customer's quiet hours to end
        store.set_action(action_id, "scheduled")
        store.audit(actor, "scheduled", "action", action_id, {"send_at": when.isoformat()})
        return True
    store.set_action(action_id, "executed", executed_at=now)
    store.audit(actor, "executed", "action", action_id, {"delivery": "simulated"})
    return True


def approve(store, approval_id: str, by: str, context_for: Callable[[str], CheckContext],
            override: bool = False) -> dict:
    """The owner says yes. The rules are checked again now, in code, before anything happens.
    A draft that failed verification: refused if any hard check failed; sent only with override=True if every
    failed check is soft, and then logged as an owner override."""
    with store.tx():
        approval = store.get_approval(approval_id)
        action = store.get_action(approval["action_id"])
        p = action["payload"]
        v = p.get("verification") or {}
        unverified = bool(v) and not v.get("passed")  # any drafted action: an owner task too
        if unverified and approval["decision"] == "pending":
            if not v.get("overridable"):
                raise ValueError("Pheri can't send this draft: it failed checks no one can override ("
                                 + (", ".join(v.get("hard_failed") or []) or "nothing it could name") + "). "
                                 + "; ".join(v.get("hard_reasons") or []) + " Reject it, or write to them yourself.")
            if not override:
                raise ValueError(f"This draft failed soft checks ({', '.join(v['soft_failed'])}). Read it, then send "
                                 "it anyway with an owner override, or reject it.")
        proposed = ProposedAction(kind=action["kind"], channel=p.get("channel"), discount_pct=p.get("discount_pct"),
                                  message=p.get("message", ""))  # from now, not from the time first planned
        store.decide_approval(approval_id, "approved", by)
        store.audit(by, "approved", "action", action["id"], {"approval_id": approval_id})
        if action["kind"] == ESCALATE:  # the owner has read it and dealt with it; nothing goes out
            store.set_action(action["id"], "executed", executed_at=context_for(action["customer_key"]).now)
            store.audit(by, "escalation_closed", "action", action["id"], {})
            return store.get_action(action["id"])
        ctx = context_for(action["customer_key"])
        proposed.send_at = next_send_time(active_rules(store), proposed, ctx)  # approved at 07:30: out at 08:00
        result = check(active_rules(store), proposed, ctx)  # do-not-contact and quiet hours too: never overridden
        if result.allowed:
            store.set_action(action["id"], "approved", rule_check=result.as_dict())
            sent_anyway = None
            if unverified:
                sent_anyway = {"by": by, "at": ctx.now.isoformat(), "overridden": list(v["soft_failed"]),
                               "line": override_line(v), "judge": v.get("judge_summary") or "judge did not run",
                               "reasons": v.get("reasons", []), "text": p.get("message", ""),
                               "channel": p.get("channel"), "sha": v.get("sha")}
                store.audit(by, "owner_override", "action", action["id"], sent_anyway)
            _execute(store, action["id"], ctx.now, by, override=sent_anyway, send_at=proposed.send_at)
        else:
            store.set_action(action["id"], "blocked", rule_check=result.as_dict())
            store.audit("pheri", "rule_blocked", "action", action["id"],
                        {"customer": action["customer_key"], "kind": action["kind"], "violations": result.violations,
                         "at": "approval"})
    return store.get_action(action["id"])


def reject(store, approval_id: str, by: str, note: str | None = None) -> dict:
    with store.tx():
        approval = store.get_approval(approval_id)
        store.decide_approval(approval_id, "rejected", by, note)
        store.set_action(approval["action_id"], "rejected")
        store.audit(by, "rejected", "action", approval["action_id"], {"approval_id": approval_id, "note": note})
    return store.get_action(approval["action_id"])


def queue(store) -> list[dict]:
    """Pending approvals with their action, oldest first: what the owner sees."""
    with store.tx():
        return [{**p, "action": store.get_action(p["action_id"])} for p in store.approvals(pending_only=True)]


def sent_messages(store, customer_key: str) -> list[tuple[str, datetime]]:
    """Customer-facing actions already carried out for this customer: what channel limits count."""
    out = []
    for a in store.actions(customer_key):
        t = CATALOG.get(a["kind"])
        if a["status"] == "executed" and t and t.customer_facing and a["executed_at"] is not None:
            out.append((a["payload"]["channel"], a["executed_at"]))
    return out
