"""The autonomy dial and the approval queue. What happens to an action after Pheri decides it.

Per action type the owner picks one mode:
  suggest    Pheri shows the action; the owner does it, or not. Pheri never carries it out.
  ask_owner  Pheri queues it for approval and carries it out only once approved.
  act_alone  Pheri carries it out straight away.

Before any of that, the action must pass the rule check in code; a blocked action goes nowhere.
Approving re-runs the check, because rules, limits and the clock may have moved since Pheri asked.
Every step is written to the audit log. Delivery is simulated for now: "executed" means recorded
as done, and nothing is sent to anyone yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .actions import BUSINESS_ACTIONS, CATALOG, ESCALATE, ProposedAction
from .rules import CheckContext, active_rules, check

MODES = ("suggest", "ask_owner", "act_alone")  # from least to most autonomous
DEFAULT_MODE = "ask_owner"
DEFAULT_MODES = {"task_for_owner": "act_alone"}  # internal: it only puts a task on the owner's list


def mode_for(store, kind: str, saved: dict[str, str] | None = None) -> str:
    saved = store.autonomy_modes() if saved is None else saved
    return saved.get(kind, DEFAULT_MODES.get(kind, DEFAULT_MODE))


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


def submit(store, customer_key: str, action: ProposedAction, ctx: CheckContext, *, why: str,
           evidence: list[dict], cap: str | None = None, actor: str = "pheri") -> dict:
    """Rule check in code, then the dial. Returns the stored action. `cap` limits the mode (weak evidence)."""
    t = CATALOG.get(action.kind)
    with store.tx():  # rules, dial and writes from one consistent view
        result = check(active_rules(store), action, ctx)
        mode = at_most(mode_for(store, action.kind), cap if t and t.customer_facing else None)
        if not result.allowed:
            aid = store.add_action(customer_key, action.kind, _payload(action), why, evidence, None,
                                   result.as_dict(), "blocked")
            store.audit(actor, "rule_blocked", "action", aid,
                        {"customer": customer_key, "kind": action.kind, "violations": result.violations})
            return store.get_action(aid)
        status = {"suggest": "suggested", "ask_owner": "awaiting_approval", "act_alone": "approved"}[mode]
        aid = store.add_action(customer_key, action.kind, _payload(action), why, evidence, mode, result.as_dict(),
                               status)
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


def _execute(store, action_id: str, now: datetime, actor: str) -> None:
    store.set_action(action_id, "executed", executed_at=now)
    store.audit(actor, "executed", "action", action_id, {"delivery": "simulated"})


def approve(store, approval_id: str, by: str, context_for: Callable[[str], CheckContext]) -> dict:
    """The owner says yes. The rules are checked again now, in code, before anything happens."""
    with store.tx():
        approval = store.get_approval(approval_id)
        action = store.get_action(approval["action_id"])
        p = action["payload"]
        proposed = ProposedAction(kind=action["kind"], channel=p.get("channel"), discount_pct=p.get("discount_pct"),
                                  message=p.get("message", ""))  # sent now, not at the time first planned
        store.decide_approval(approval_id, "approved", by)
        store.audit(by, "approved", "action", action["id"], {"approval_id": approval_id})
        if action["kind"] == ESCALATE:  # the owner has read it and dealt with it; nothing goes out
            store.set_action(action["id"], "executed", executed_at=context_for(action["customer_key"]).now)
            store.audit(by, "escalation_closed", "action", action["id"], {})
            return store.get_action(action["id"])
        ctx = context_for(action["customer_key"])
        result = check(active_rules(store), proposed, ctx)
        if result.allowed:
            store.set_action(action["id"], "approved", rule_check=result.as_dict())
            _execute(store, action["id"], ctx.now, by)
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
