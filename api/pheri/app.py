"""Pheri's HTTP API (FastAPI). Every route calls code the rest of the repo already tests: no new logic here.

    cd api && uvicorn pheri.app:app --reload        # mock mode: no network, no spend

Routes, per business (brightdesk, kettle):
  GET  /businesses/{b}/customers                     customers with their journey stage (code only)
  GET  /businesses/{b}/customers/{key}               one customer's facts and stage (code only)
  GET  /businesses/{b}/customers/{key}/profile       the profile (the model reads their messages)
  POST /businesses/{b}/customers/{key}/decision      guard, profile, decide: the next best action
  POST /businesses/{b}/customers/{key}/discount-check   would a discount pass the owner's rules?
  GET  /businesses/{b}/approvals                     the approval queue
  POST /businesses/{b}/approvals/{id}/approve|reject approve (rules checked again) or reject
  GET  /businesses/{b}/rules  POST /rules  POST /rules/{id}/confirm   the owner's rules
  GET|PUT /businesses/{b}/private-mode               which steps run on Muse Spark Open
  GET  /businesses/{b}/twin                          the customer twin's results (chart-ready)
  GET  /businesses/{b}/learned                       "What Pheri learned" from those results
  GET  /businesses/{b}/audit                         the append-only audit log
  GET  /spend                                        model spend against the caps, per provider

Mock mode only for now: create_app() refuses live mode unless PHERI_API_ALLOW_LIVE=1, so no request can
spend by accident. Even then, /learned never calls Muse Wonder; a Wonder report is a deliberate,
budgeted run (scripts/live_learn.py).
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .actions import ProposedAction
from .autonomy import approve, queue, reject, sent_messages
from .config import REPO_ROOT, get_settings
from .decide import decide_customer
from .journey import STAGES, stage, stages
from .guard import handle_reply
from .learn import write_report
from .llm import LLM
from .privacy import private_mode, set_private_mode
from .profile import Profile, build_profile, compute_facts, load, norm_email
from .rules import CheckContext, active_rules, check, confirm, describe, propose, seed
from .store import MemoryStore, NotFound, PgStore
from .synth import BUSINESS_NAMES, NOW

BUSINESSES = tuple(BUSINESS_NAMES)
TWIN_DIR = REPO_ROOT / "data" / "twin"
PROVIDERS = ("meta", "baseten")


# ---- request bodies ---------------------------------------------------------------
class By(BaseModel):
    by: str = Field(min_length=1, max_length=120, description="who: owner:<name>")


class RejectIn(By):
    note: str | None = Field(default=None, max_length=500)


class RuleIn(By):
    text: str = Field(min_length=1, max_length=500, description="the rule in the owner's own words")


class DiscountIn(BaseModel):
    discount_pct: float = Field(gt=0, le=100)
    channel: str | None = None


class PrivateModeIn(By):
    full: bool = False
    guard: bool = False
    profile: bool = False
    decide: bool = False
    rules: bool = False


# ---- state ------------------------------------------------------------------------
class State:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.settings = llm.settings
        self.data = {b: load(b) for b in BUSINESSES}
        self.stages = {b: stages(ds) for b, ds in self.data.items()}  # code only, no model
        url = self.settings.database_url
        self.stores = {b: PgStore(b, url) if url else MemoryStore(b) for b in BUSINESSES}
        self.profiles: dict[tuple[str, str], Profile] = {}
        self.learned: dict[tuple[str, int, int], dict] = {}
        self.decided: dict[str, dict[str, dict]] = {b: {} for b in BUSINESSES}  # business -> key -> Outcome
        self.lock = threading.RLock()  # the memory store is not thread-safe: one request at a time touches it
        if self.settings.llm_mode == "mock":
            for b in BUSINESSES:  # the demo's starting rules (Brightdesk: no discounts in the first month)
                seed(self.stores[b], llm, by="owner:demo")


def create_app(llm: LLM | None = None) -> FastAPI:
    settings = llm.settings if llm else get_settings()
    if settings.llm_mode != "mock" and os.environ.get("PHERI_API_ALLOW_LIVE") != "1":
        raise RuntimeError("The API runs in mock mode for now. Set PHERI_API_ALLOW_LIVE=1 to serve live on purpose.")
    state = State(llm or LLM(settings))
    app = FastAPI(title="Pheri", description="The next step for every customer, inside your rules.")
    app.state.pheri = state

    def business(b: str) -> str:
        if b not in BUSINESSES:
            raise HTTPException(404, f"no business {b!r}")
        return b

    def customer(b: str, key: str):
        c = state.data[b].customers.get(norm_email(key))
        if c is None:
            raise HTTPException(404, f"no customer {key!r} at {b}")
        return c

    def profile_of(b: str, key: str) -> Profile:
        k = (b, norm_email(key))
        if k not in state.profiles:
            customer(b, key)
            state.profiles[k] = build_profile(state.data[b], key, state.llm,
                                              private=private_mode(state.stores[b])["profile"])
        return state.profiles[k]

    def ctx_for(b: str, key: str) -> CheckContext:
        c = customer(b, key)
        facts, _ = compute_facts(c, b)
        store = state.stores[b]
        return CheckContext(b, facts, NOW, sent_messages(store, c.key),
                            do_not_contact=store.do_not_contact(c.key) is not None)

    def rule_view(row: dict) -> dict:
        c = row["compiled"]
        return {"id": row["id"], "source_text": row["source_text"], "active": row["active"],
                "confirmed_by": row.get("confirmed_by"), "confirmed_at": row.get("confirmed_at"),
                "described": c.get("described", []), "problems": c.get("problems", []),
                "unsupported": c.get("unsupported", [])}

    # ---- the basics ----
    @app.get("/health")
    def health():
        return {"ok": True, "mode": state.settings.llm_mode}

    @app.get("/businesses")
    def businesses():
        return [{"slug": b, "name": BUSINESS_NAMES[b], "customers": len(state.data[b].customers)} for b in BUSINESSES]

    # ---- customers ----
    @app.get("/businesses/{b}/customers")
    def customers(b: str = Depends(business), stage_: str | None = Query(None, alias="stage"),
                  limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        rows = [{"key": k, "name": c.name, "company": c.company, "stage": state.stages[b][k].stage,
                 "because": [{"fact": x["fact"], "value": x["value"]} for x in state.stages[b][k].because]}
                for k, c in state.data[b].customers.items()]
        if stage_:
            rows = [r for r in rows if r["stage"] == stage_]
        return {"total": len(rows), "items": rows[offset:offset + limit]}

    @app.get("/businesses/{b}/customers/{key}")
    def one_customer(key: str, b: str = Depends(business)):
        c = customer(b, key)
        facts, prov = compute_facts(c, b)
        j = stage(b, facts, prov)
        return {"key": c.key, "name": c.name, "company": c.company, "facts": facts, "journey": j.as_dict(),
                "do_not_contact": state.stores[b].do_not_contact(c.key)}

    @app.get("/businesses/{b}/customers/{key}/profile")
    def profile(key: str, b: str = Depends(business)):
        with state.lock:
            return profile_of(b, key).as_dict()

    @app.post("/businesses/{b}/customers/{key}/decision")
    def decision(key: str, b: str = Depends(business)):
        """Decide again now (guard, profile, decide). The result replaces the stored one."""
        c = customer(b, key)
        with state.lock:
            out = dataclasses.asdict(decide_customer(state.data[b], key, state.stores[b], state.llm))
            state.decided[b][c.key] = out
        return out

    def decided(b: str, key: str) -> dict:
        c = customer(b, key)
        if c.key not in state.decided[b]:
            state.decided[b][c.key] = dataclasses.asdict(decide_customer(state.data[b], c.key, state.stores[b],
                                                                         state.llm))
        return state.decided[b][c.key]

    @app.get("/businesses/{b}/customers/{key}/decision")
    def stored_decision(key: str, b: str = Depends(business)):
        """The customer's current decision (decided once, then read), with the action's live status."""
        with state.lock:
            k = customer(b, key).key
            return card(b, k, decided(b, k))

    @app.get("/businesses/{b}/customers/{key}/trace")
    def trace(key: str, b: str = Depends(business)):
        """The agent's loop for this decision: every turn (what the model was sent, the tool it called, what came
        back), then what code did with the answer: evidence attached, rule checks, the autonomy dial."""
        with state.lock:
            k = customer(b, key).key
            out = decided(b, k)
            return {**card(b, k, out), "turns": out["turn_log"], "prechecks": out["prechecks"],
                    "dropped_evidence": out["dropped_evidence"]}

    @app.post("/businesses/{b}/customers/{key}/discount-check")
    def discount_check(body: DiscountIn, key: str, b: str = Depends(business)):
        """Would this discount pass the owner's rules for this customer? Pure code, no model."""
        from .actions import CHANNELS

        with state.lock:
            proposed = ProposedAction(kind="offer_discount", channel=body.channel or CHANNELS[b][0],
                                      discount_pct=body.discount_pct)
            r = check(active_rules(state.stores[b]), proposed, ctx_for(b, key))
            by_id = {x.id: x for x in active_rules(state.stores[b])}
            refused_by = []
            for res in r.results:
                if res["passed"]:
                    continue
                rule = by_id.get(res["rule_id"])
                refused_by.append({"rule_id": res["rule_id"], "source_text": rule.source_text if rule else None,
                                   "described": [describe(x) for x in rule.checks] if rule else [res["reason"]],
                                   "reason": res["reason"]})
        return {"allowed": r.allowed, "violations": r.violations, "results": r.results, "refused_by": refused_by}

    # ---- the approval queue ----
    @app.get("/businesses/{b}/approvals")
    def approvals(b: str = Depends(business)):
        with state.lock:
            return queue(state.stores[b])

    @app.post("/businesses/{b}/approvals/{approval_id}/approve")
    def approve_one(approval_id: str, body: By, b: str = Depends(business)):
        with state.lock:
            try:
                # The re-check needs code-computed facts only: approving never costs a model call.
                return approve(state.stores[b], approval_id, body.by, context_for=lambda k: ctx_for(b, k))
            except NotFound:
                raise HTTPException(404, f"no approval {approval_id!r}") from None
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None

    @app.post("/businesses/{b}/approvals/{approval_id}/reject")
    def reject_one(approval_id: str, body: RejectIn, b: str = Depends(business)):
        with state.lock:
            try:
                return reject(state.stores[b], approval_id, body.by, body.note)
            except NotFound:
                raise HTTPException(404, f"no approval {approval_id!r}") from None
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None

    # ---- the owner's rules ----
    @app.get("/businesses/{b}/rules")
    def rules(b: str = Depends(business)):
        with state.lock:
            return [rule_view(r) for r in state.stores[b].rules(active_only=False)]

    @app.post("/businesses/{b}/rules", status_code=201)
    def add_rule(body: RuleIn, b: str = Depends(business)):
        """Compile the owner's words (the model translates, code validates). Not enforced until confirmed."""
        with state.lock:
            try:
                draft = propose(state.stores[b], state.llm, body.text, actor=body.by)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return {**rule_view(state.stores[b].get_rule(draft.id)), "confirmable": draft.confirmable}

    @app.post("/businesses/{b}/rules/{rule_id}/confirm")
    def confirm_rule(rule_id: str, body: By, b: str = Depends(business)):
        with state.lock:
            try:
                confirm(state.stores[b], rule_id, body.by)
            except NotFound:
                raise HTTPException(404, f"no rule {rule_id!r}") from None
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            return rule_view(state.stores[b].get_rule(rule_id))

    # ---- private mode ----
    @app.get("/businesses/{b}/private-mode")
    def get_private(b: str = Depends(business)):
        with state.lock:
            return private_mode(state.stores[b])

    @app.put("/businesses/{b}/private-mode")
    def put_private(body: PrivateModeIn, b: str = Depends(business)):
        """On: those steps run on Muse Spark Open (Meta's open-weight model, served by a partner, self-hostable).
        full: every step, and nothing goes to the Meta Model API."""
        with state.lock:
            state.profiles = {k: v for k, v in state.profiles.items() if k[0] != b}  # re-read on the new path
            return set_private_mode(state.stores[b], by=body.by, full=body.full, guard=body.guard,
                                    profile=body.profile, decide=body.decide, rules=body.rules)

    # ---- what worked ----
    def twin_results(b: str, customers: int, seed_: int) -> dict:
        path = TWIN_DIR / f"{b}-n{customers}-seed{seed_}.json"
        if not path.exists():
            raise HTTPException(404, f"no twin results for {b} at {customers} customers, seed {seed_}")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/businesses/{b}/twin")
    def twin(b: str = Depends(business), customers: int = 5000, seed_: int = Query(7, alias="seed")):
        return twin_results(b, customers, seed_)

    @app.get("/businesses/{b}/learned")
    def learned(b: str = Depends(business), customers: int = 5000, seed_: int = Query(7, alias="seed")):
        """'What Pheri learned', every number and verdict checked in code. Written by the offline stand-in in
        mock mode; never calls Muse Wonder from a request (that is scripts/live_learn.py, on purpose)."""
        if state.settings.llm_mode != "mock":
            raise HTTPException(409, "Muse Wonder reports are written on purpose: run scripts/live_learn.py.")
        k = (b, customers, seed_)
        with state.lock:
            if k not in state.learned:
                rep = write_report(twin_results(b, customers, seed_), state.llm)
                state.learned[k] = {**dataclasses.asdict(rep), "markdown": rep.markdown}
            return state.learned[k]

    # ---- for the web app: next steps, replies, which model runs ----
    def showcase(b: str) -> list[str]:
        """The customers the home page shows, the same every run: Maya first, then the first customer (in file
        order) in each journey stage, then whoever sent the known attack messages (they go to Safety)."""
        ds, picked = state.data[b], []
        if b == "brightdesk":
            picked.append("maya.okafor@pinecrest.example")
        for st in STAGES[b]:
            if any(state.stages[b][k].stage == st for k in picked):
                continue  # already shown (Maya is the stuck one)
            k = next((k for k, j in state.stages[b].items() if j.stage == st), None)
            if k:
                picked.append(k)
        attacks = json.loads((REPO_ROOT / "data" / "synth" / b / "_truth.json").read_text(encoding="utf-8"))["attacks"]
        for k, cu in ds.customers.items():
            if any(src.id in attacks for src in cu.sources) and k not in picked:
                picked.append(k)
        return picked

    def warm(b: str) -> None:
        for k in showcase(b):
            if k not in state.decided[b]:
                state.decided[b][k] = dataclasses.asdict(decide_customer(state.data[b], k, state.stores[b], state.llm))
        # The Safety screen reads replies in every language the data has: the first one in each other language.
        seen_langs = {"en"}
        for cu in state.data[b].customers.values():
            for src in sorted(cu.sources, key=lambda x: x.at or ""):
                if src.kind in ("ticket", "message") and src.lang and src.lang not in seen_langs:
                    seen_langs.add(src.lang)
                    handle_reply(state.stores[b], state.llm, cu.key, src.text, source_id=src.id,
                                 data_class=state.data[b].data_class)

    def card(b: str, k: str, out: dict) -> dict:
        store = state.stores[b]
        cu = state.data[b].customers[k]
        action = store.get_action(out["action"]["id"]) if out.get("action") else None  # live status, not cached
        approval = next((a for a in store.approvals(pending_only=False) if action and a["action_id"] == action["id"]),
                        None)
        return {"customer": {"key": k, "name": cu.name, "company": cu.company, "stage": state.stages[b][k].stage},
                "decision": out["decision"], "evidence": out["evidence"], "action": action,
                "approval": approval, "skipped": out["skipped"], "fallback": out["fallback"],
                "unsupported_numbers": out["unsupported_numbers"], "message_problems": out["message_problems"],
                "private": out["private"], "cost_usd": out["cost_usd"], "turns": out["turns"]}

    @app.get("/businesses/{b}/next-steps")
    def next_steps(b: str = Depends(business)):
        """One decided next step per showcase customer. Escalations (possible attacks) are on /replies."""
        with state.lock:
            warm(b)
            cards = [card(b, k, state.decided[b][k]) for k in showcase(b)]
        return [x for x in cards if x["skipped"] not in ("escalated", "open_escalation")]

    @app.get("/businesses/{b}/replies")
    def replies(b: str = Depends(business)):
        """Every inbound reply the guard has read, newest decision first, with what code and the model made of it."""
        with state.lock:
            warm(b)
            store, ds = state.stores[b], state.data[b]
            texts = {src.id: (cu, src) for cu in ds.customers.values() for src in cu.sources}
            escalated = {a["payload"].get("source_id"): a for a in store.actions() if a["kind"] == "escalate_to_human"}
            out = []
            for e in store.audit_log():
                if e["event"] != "reply_screened" or e["subject_id"] not in texts:
                    continue
                cu, src = texts[e["subject_id"]]
                g = e["details"]
                esc = escalated.get(e["subject_id"])
                out.append({"source_id": src.id, "kind": src.kind, "at": src.at, "text": src.text,
                            "customer": {"key": cu.key, "name": cu.name, "company": cu.company},
                            "label": g["label"], "language": g["language"], "summary": g["summary"],
                            "attack": g["attack"], "stop": g["stop"], "screen_before": g["screen_before"],
                            "screen_after": g["screen_after"], "provider": g["provider"], "model": g["model"],
                            "escalation": {"id": esc["id"], "status": esc["status"]} if esc else None})
            return out

    @app.get("/businesses/{b}/private-mode/runs-on")
    def runs_on(b: str = Depends(business)):
        """Which model each step runs on right now."""
        with state.lock:
            mode = private_mode(state.stores[b])
        meta = {"provider": "meta", "model": "muse-spark-1.3", "label": "Muse Spark via the Meta Model API"}
        private = {"provider": "baseten", "model": state.settings.baseten_model,
                   "label": "Muse Spark Open via Baseten (Meta's open-weight model, served by a partner, "
                            "self-hostable)"}
        return {"steps": {step: private if on else meta for step, on in mode.items()},
                "full_private": all(mode.values())}

    @app.get("/businesses/{b}/audit")
    def audit(b: str = Depends(business), subject_id: str | None = None, limit: int = Query(200, ge=1, le=2000)):
        with state.lock:
            return state.stores[b].audit_log(subject_id)[-limit:]

    # ---- spend ----
    @app.get("/spend")
    def spend():
        out = {}
        for p in PROVIDERS:
            t = state.llm.ledger.totals(p)
            out[p] = {"settled_usd": round(t.settled_usd, 6), "reserved_usd": round(t.reserved_usd, 6),
                      "offset_usd": t.offset_usd, "cap_usd": t.cap_usd, "remaining_usd": round(t.remaining_usd, 6)}
        return {"mode": state.settings.llm_mode, "providers": out, "as_of": datetime.now().isoformat(timespec="seconds")}

    return app


def __getattr__(name: str):
    # `uvicorn pheri.app:app` builds the app on first use, so importing this module never loads data or seeds.
    if name == "app":
        return create_app()
    raise AttributeError(name)
