"""Pheri's HTTP API (FastAPI). Every route calls code the rest of the repo already tests: no new logic here.

    cd api && uvicorn pheri.app:app --reload        # mock mode: no network, no spend

Routes, per business (brightdesk, birgunj):
  GET  /businesses/{b}/customers                     customers with their journey stage (code only)
  GET  /businesses/{b}/customers/{key}               one customer's facts and stage (code only)
  GET  /businesses/{b}/customers/{key}/profile       the profile (the model reads their messages)
  POST /businesses/{b}/customers/{key}/decision      guard, profile, decide: the next best action
  POST /businesses/{b}/customers/{key}/discount-check   would a discount pass the owner's rules?
  GET  /businesses/{b}/approvals                     the approval queue
  POST /businesses/{b}/approvals/{id}/approve|reject approve (rules checked again) or reject; approve with
                                                     {"override": true} sends a draft that failed only soft checks
  GET  /businesses/{b}/rules  POST /rules  POST /rules/{id}/confirm   the owner's rules
  GET|PUT /businesses/{b}/private-mode               which steps run on Muse Spark Open
  GET  /businesses/{b}/twin                          the customer twin's results (chart-ready)
  GET  /businesses/{b}/learned                       "What Pheri learned" from those results
  GET  /businesses/{b}/verification                  how the showcase drafts fared: caught by code, by the judge,
                                                     retried, sent to the owner
  GET  /businesses/{b}/middle-step                   the stage and plan scores against the truth set, and the bar
  GET  /businesses/{b}/audit                         the append-only audit log
  GET  /spend                                        model spend against the caps, per provider; plus the
                                                     live runs' snapshot (data/spend/live.json)

  POST /demo/reset                                   the public demo: this visitor's sandbox back to the start

The public demo (PHERI_PUBLIC_DEMO=1): every visitor gets their own sandbox, a copy of the demo state in
memory, found by a cookie (or the web app's x-pheri-sandbox header): at most MAX_SANDBOXES, each dropped after
SANDBOX_IDLE_S idle, the one idle longest dropped first when full. Nothing one visitor approves or writes
reaches another. There is no login, so the audit log never names an owner: every approval, rule and switch
is "by: demo visitor (public demo, no login)", and the starting rules are the demo setup's.

Mock mode only for now: create_app() refuses live mode unless PHERI_API_ALLOW_LIVE=1, so no request can
spend by accident. Even then, /learned never calls Muse Wonder; a Wonder report is a deliberate,
budgeted run (scripts/live_learn.py).
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .actions import ProposedAction
from .words import plain, plain_reason, read_language
from .autonomy import approve, queue, reject, sent_messages
from .config import REPO_ROOT, get_settings
from .decide import decide_customer
from .journey import STAGES, stage, stages
from .guard import handle_reply
from .learn import write_report
from .llm import LLM
from .privacy import private_mode, set_private_mode
from .profile import Profile, build_profile, compute_facts, load, norm_email
from .rules import CheckContext, active_rules, check, confirm, describe, local_time, propose, seed
from .store import MemoryStore, NotFound, PgStore
from .synth import BUSINESS_NAMES, CLOCKS
from . import voice
from . import voice as voice_module
from .verify import CODE_CHECKS, THRESHOLDS, middle_step_scores, override_line, override_summary

BUSINESSES = tuple(BUSINESS_NAMES)
TWIN_DIR = REPO_ROOT / "data" / "twin"
SPEND_SNAPSHOT = REPO_ROOT / "data" / "spend" / "live.json"  # written by scripts/spend_snapshot.py
PROVIDERS = ("meta", "baseten")
PER_STAGE = {"brightdesk": 1, "birgunj": 3}  # showcase customers per journey stage (Birgunj: the night shift)


# ---- request bodies ---------------------------------------------------------------
class By(BaseModel):
    by: str = Field(min_length=1, max_length=120, description="who: owner:<name>")


class ApproveIn(By):
    override: bool = Field(default=False, description="send a draft that failed only soft checks, as an owner override")
    choice: str | None = Field(default=None, max_length=200,
                               description="for a money question: which of the step's owner_options the owner picked")


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
DEMO_ACTOR = "demo visitor (public demo, no login)"  # who the audit log names in the public demo: never an owner
DEMO_SETUP = "demo setup (public demo, no login)"  # who confirmed the starting rules there
SANDBOX_COOKIE = "pheri_sandbox"
SANDBOX_HEADER = "x-pheri-sandbox"  # the web app's server forwards the visitor's cookie this way
MAX_SANDBOXES = 100
SANDBOX_IDLE_S = 30 * 60
_SANDBOX_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_visitor: ContextVar[str | None] = ContextVar("pheri_visitor", default=None)  # this request's sandbox id


@dataclass
class Sandbox:
    """Everything a visitor can change: the stores (rules, approvals, the audit log), the decisions, the profiles."""
    stores: dict
    decided: dict[str, dict[str, dict]]  # business -> key -> Outcome
    profiles: dict[tuple[str, str], Profile]
    seen: float = field(default_factory=time.monotonic)


class State:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.settings = llm.settings
        self.data = {b: load(b) for b in BUSINESSES}
        self.voice = {b: voice.fill(ds, llm) for b, ds in self.data.items()}  # before anything reads the messages
        self.stages = {b: stages(ds) for b, ds in self.data.items()}  # code only, no model
        self.learned: dict[tuple[str, int, int], dict] = {}  # the same for everyone: written from the twin's results
        self.slop: dict[str, list[dict]] = {}  # Slop vs Pheri: the same for everyone, made once
        self.lock = threading.RLock()  # the memory store is not thread-safe: one request at a time touches it
        self.public_demo = self.settings.public_demo
        if self.public_demo and self.settings.database_url:
            raise RuntimeError("The public demo keeps each visitor's sandbox in memory: unset DATABASE_URL.")
        self.base = self.fresh()  # the demo as it starts; in the public demo, only ever copied
        self.base_warm = False
        self.sandboxes: OrderedDict[str, Sandbox] = OrderedDict()  # least recently used first

    def fresh(self) -> Sandbox:
        url = self.settings.database_url
        stores = {b: PgStore(b, url) if url else MemoryStore(b) for b in BUSINESSES}
        if self.settings.llm_mode != "live" or self.settings.record_path:
            # The demo's starting rules (Brightdesk: no discounts in the first month). A recording run seeds them
            # too, so replay rebuilds exactly the conversations it recorded.
            for b in BUSINESSES:
                seed(stores[b], self.llm, by=DEMO_SETUP if self.public_demo else "owner:demo")
        return Sandbox(stores, {b: {} for b in BUSINESSES}, {})

    @property
    def current(self) -> Sandbox:
        sid = _visitor.get()
        return self.base if sid is None else self.sandboxes[sid]

    # The routes read these; in the public demo they are this visitor's own.
    @property
    def stores(self) -> dict:
        return self.current.stores

    @property
    def decided(self) -> dict:
        return self.current.decided

    @property
    def profiles(self) -> dict:
        return self.current.profiles

    @profiles.setter
    def profiles(self, value: dict) -> None:
        self.current.profiles = value

    def who(self, by: str) -> str:
        """The name the audit log records: in the public demo there is no login, so never a pretend owner."""
        return DEMO_ACTOR if self.public_demo else by


def create_app(llm: LLM | None = None) -> FastAPI:
    settings = llm.settings if llm else get_settings()
    if settings.llm_mode == "live" and os.environ.get("PHERI_API_ALLOW_LIVE") != "1":
        raise RuntimeError("The API runs in mock mode (or replay) for now. Set PHERI_API_ALLOW_LIVE=1 to serve live "
                           "on purpose.")
    state = State(llm or LLM(settings))
    app = FastAPI(title="Pheri", description="The next step for every customer, inside your rules.")
    app.state.pheri = state

    def sandbox_for(sid: str) -> Sandbox:
        """This visitor's sandbox: made from the warmed demo on the first request, dropped after SANDBOX_IDLE_S idle,
        and the one idle longest dropped first when MAX_SANDBOXES are open."""
        with state.lock:
            now = time.monotonic()
            for old in [k for k, sb in state.sandboxes.items() if now - sb.seen > SANDBOX_IDLE_S]:
                del state.sandboxes[old]
            sb = state.sandboxes.get(sid)
            if sb is None:
                if not state.base_warm:  # decide the showcase once, on the shared start; visitors get copies
                    token = _visitor.set(None)
                    try:
                        for b in BUSINESSES:
                            warm(b)
                    finally:
                        _visitor.reset(token)
                    state.base_warm = True
                while len(state.sandboxes) >= MAX_SANDBOXES:
                    state.sandboxes.popitem(last=False)
                base = state.base
                sb = state.sandboxes[sid] = Sandbox(copy.deepcopy(base.stores),
                                                    {b: dict(v) for b, v in base.decided.items()}, dict(base.profiles))
            state.sandboxes.move_to_end(sid)
            sb.seen = now
            return sb

    @app.middleware("http")
    async def visitor_sandbox(request: Request, call_next):
        if not state.public_demo:
            return await call_next(request)
        sid = request.headers.get(SANDBOX_HEADER) or request.cookies.get(SANDBOX_COOKIE) or ""
        if not _SANDBOX_ID.fullmatch(sid):
            sid = str(uuid.uuid4())
        token = _visitor.set(sid)
        try:
            sandbox_for(sid)
            response = await call_next(request)
        finally:
            _visitor.reset(token)
        response.set_cookie(SANDBOX_COOKIE, sid, max_age=SANDBOX_IDLE_S, httponly=True, samesite="lax")
        return response

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
        return CheckContext(b, facts, CLOCKS[b][1], sent_messages(store, c.key),  # the owner's clock
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
        """mode: live (real calls), replay (replies recorded in a live run, played back), or mock (the stand-in).
        public_demo: every visitor has their own sandbox, and no one is logged in. code_checks: how many there are."""
        return {"ok": True, "mode": state.settings.llm_mode, "public_demo": state.public_demo,
                "code_checks": len(CODE_CHECKS)}

    @app.post("/demo/reset")
    def reset_demo():
        """Back to the start: in the public demo, this visitor's sandbox only (the next request copies the start
        again); run locally, the one shared demo state."""
        with state.lock:
            if state.public_demo:
                state.sandboxes.pop(_visitor.get() or "", None)
            else:
                state.base, state.base_warm = state.fresh(), False
        return {"reset": True, "public_demo": state.public_demo}

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
            out = dataclasses.asdict(decide_customer(state.data[b], key, state.stores[b], state.llm, CLOCKS[b][1]))
            state.decided[b][c.key] = out
        return out

    def decided(b: str, key: str) -> dict:
        c = customer(b, key)
        if c.key not in state.decided[b]:
            state.decided[b][c.key] = dataclasses.asdict(decide_customer(state.data[b], c.key, state.stores[b],
                                                                         state.llm, CLOCKS[b][0]))
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
                    "dropped_evidence": out["dropped_evidence"], "attempts": out["attempts"],
                    "final_verification": out["verification"], "discarded_tools": out["discarded_tools"]}

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
    def approve_one(approval_id: str, body: ApproveIn, b: str = Depends(business)):
        with state.lock:
            try:
                # The re-check needs code-computed facts only: approving never costs a model call.
                return approve(state.stores[b], approval_id, state.who(body.by), context_for=lambda k: ctx_for(b, k),
                               override=body.override, choice=body.choice)
            except NotFound:
                raise HTTPException(404, f"no approval {approval_id!r}") from None
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None

    @app.post("/businesses/{b}/approvals/{approval_id}/reject")
    def reject_one(approval_id: str, body: RejectIn, b: str = Depends(business)):
        with state.lock:
            try:
                return reject(state.stores[b], approval_id, state.who(body.by), body.note)
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
                draft = propose(state.stores[b], state.llm, body.text, actor=state.who(body.by))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return {**rule_view(state.stores[b].get_rule(draft.id)), "confirmable": draft.confirmable}

    @app.post("/businesses/{b}/rules/{rule_id}/confirm")
    def confirm_rule(rule_id: str, body: By, b: str = Depends(business)):
        with state.lock:
            try:
                confirm(state.stores[b], rule_id, state.who(body.by))
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
            return set_private_mode(state.stores[b], by=state.who(body.by), full=body.full, guard=body.guard,
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
        if state.settings.llm_mode == "live":
            raise HTTPException(409, "Muse Wonder reports are written on purpose: run scripts/live_learn.py.")
        k = (b, customers, seed_)
        with state.lock:
            if k not in state.learned:
                rep = write_report(twin_results(b, customers, seed_), state.llm)
                # Offline, the report is Muse Wonder's only if a live run recorded it; else the stand-in wrote it.
                source = "recorded" if rep.recorded else "stand-in"
                state.learned[k] = {**dataclasses.asdict(rep), "markdown": rep.markdown, "source": source}
            return state.learned[k]

    # ---- for the web app: next steps, replies, which model runs ----
    def showcase(b: str) -> list[str]:
        """The customers the home page shows, the same every run: Maya first (Brightdesk), then the first
        PER_STAGE[b] customers (in file order) in each journey stage, then whoever sent a voice note, then whoever
        sent the known attack messages (they go to Safety). Birgunj's is the night shift: about 25 customers."""
        ds, picked = state.data[b], []
        truth = json.loads((REPO_ROOT / "data" / "synth" / b / "_truth.json").read_text(encoding="utf-8"))
        if truth.get("night"):  # the night shift: everyone who wrote in overnight, in the order they wrote
            return [n["customer"] for n in truth["night"] if n["customer"] in ds.customers]
        if b == "brightdesk":
            picked.append("maya.okafor@pinecrest.example")
        for st in STAGES[b]:
            have = sum(state.stages[b][k].stage == st for k in picked)  # Maya is already the stuck one
            for k in [k for k, j in state.stages[b].items() if j.stage == st][:max(0, PER_STAGE[b] - have)]:
                picked.append(k)
        for note in state.voice[b].values():
            if note["customer"] not in picked:
                picked.append(note["customer"])
        attacks = json.loads((REPO_ROOT / "data" / "synth" / b / "_truth.json").read_text(encoding="utf-8"))["attacks"]
        for k, cu in ds.customers.items():
            if any(src.id in attacks for src in cu.sources) and k not in picked:
                picked.append(k)
        return picked

    def warm(b: str) -> None:
        for k in showcase(b):
            if k not in state.decided[b]:
                state.decided[b][k] = dataclasses.asdict(decide_customer(state.data[b], k, state.stores[b], state.llm,
                                                                        CLOCKS[b][0]))  # the night shift's clock
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
        sends_at = None
        if action and action["status"] == "scheduled" and action["payload"].get("send_at"):
            sends_at = local_time(datetime.fromisoformat(action["payload"]["send_at"]),
                                  CheckContext(b, {"country": cu.attrs.get("country")}, CLOCKS[b][1]))
        drafts = [{"attempt": a.get("attempt", i + 1), "passed": a["verification"]["passed"],
                   "caught_by": a["verification"]["caught_by"],
                   "reasons": [plain_reason(r) for r in a["verification"]["reasons"][:3]]}
                  for i, a in enumerate(out.get("attempts") or [])]
        return {"sends_at_local": sends_at, "drafts": drafts,
                "waits_for_owner": (action or {}).get("payload", {}).get("waits_for_owner"),
                "owner_options": (action or {}).get("payload", {}).get("owner_options") or [],
                "owner_choice": owner_choice(b, action),
                "holding_reply": holding(b, k),
                "customer": {"key": k, "name": cu.name, "company": cu.company, "town": cu.attrs.get("town"),
                             "stage": state.stages[b][k].stage},
                # why is for the owner: in plain words (the message itself is shown exactly as it was checked)
                "decision": {**out["decision"], "why_this": plain(out["decision"].get("why_this")),
                             "why_now": plain(out["decision"].get("why_now"))},
                "evidence": receipts(b, cu, out["evidence"]), "action": action,
                "approval": approval, "skipped": out["skipped"], "fallback": out["fallback"],
                "unsupported_numbers": out["unsupported_numbers"], "message_problems": out["message_problems"],
                "private": out["private"], "cost_usd": out["cost_usd"], "turns": out["turns"],
                "decided_by": decided_by(out), "verification": verification_line(out),
                "override": override_of(b, action)}

    def holding(b: str, k: str) -> dict | None:
        """The fixed reply, written by code, that a customer whose message looked like an attack gets."""
        from .holding import holding_reply_for

        a = holding_reply_for(state.stores[b], k)
        if a is None:
            return None
        cu = state.data[b].customers[k]
        at = a["payload"].get("send_at")
        when = local_time(datetime.fromisoformat(at), CheckContext(b, {"country": cu.attrs.get("country")}, CLOCKS[b][1]))             if at and a["status"] == "scheduled" else None
        return {"message": a["payload"]["message"], "language": a["payload"].get("language"), "status": a["status"],
                "sends_at_local": when, "checks": (a["payload"].get("verification") or {}).get("code_checks")}

    def owner_choice(b: str, action: dict | None) -> str | None:
        """What the owner picked when approving a money question (from the audit log), or None."""
        if not action:
            return None
        return next((e["details"]["choice"] for e in reversed(state.stores[b].audit_log(action["id"]))
                     if e["event"] == "approved" and (e["details"] or {}).get("choice")), None)

    def receipts(b: str, cu, evidence: list[dict]) -> list[dict]:
        """A receipt for each piece of evidence, in the owner's terms: the order numbers a fact was counted from,
        or where and when the customer wrote a quote (never an internal row or message id)."""
        _, prov = compute_facts(cu, b)
        orders = {o["_ref"]: o["order_id"] for o in cu.orders}
        sources = {src.id: src for src in cu.sources}
        out = []
        for e in evidence:
            r = None
            if e["kind"] == "fact":
                refs = prov.get(e["ref"], [])
                ids = [orders[x] for x in refs if x in orders]
                if ids:
                    r = {"kind": "order", "ids": ids[-3:], "more": max(0, len(ids) - 3)}
                elif cal := next((x for x in refs if x.startswith("calendar:")), None):
                    r = {"kind": "calendar", "name": cal.split(":", 1)[1].split("_")[0]}
                elif any(x.startswith("events.jsonl") for x in refs):
                    r = {"kind": "activity"}
            elif e["kind"] == "quote" and (src := sources.get(e.get("ref"))):
                r = {"kind": "message", "channel": src.channel or ("email" if src.kind == "ticket" else None),
                     "at": src.at, "lang": src.lang, "from_staff": src.kind == "sales_note"}
            out.append({**e, "receipt": r})
        return out

    def override_of(b: str, action: dict | None) -> dict | None:
        """An owner's override of soft checks, from the audit log: who, when, what, and the text sent."""
        if not action:
            return None
        e = next((x for x in reversed(state.stores[b].audit_log(action["id"])) if x["event"] == "owner_override"), None)
        if e is None:
            return None
        v = action["payload"].get("verification") or {}
        return {**e["details"], "summary": override_summary(v), "line": e["details"].get("line") or override_line(v),
                "logged_at": str(e["at"])}

    def verification_line(out: dict) -> dict | None:
        """For the card's footer: "Verified: N code checks + judge" (N: the checks that applied, of CODE_CHECKS), or
        why a person has it."""
        v = out.get("verification")
        if not v:
            return None
        return {"passed": v["passed"], "code_checks": v["code_checks"], "judge": v["judge_ran"],
                "caught_by": v["caught_by"], "reasons": [plain_reason(r) for r in v["reasons"]], "attempts": len(out.get("attempts") or []),
                "hard_failed": v["hard_failed"], "soft_failed": v["soft_failed"],  # Verification's own
                "judge_cost_usd": out.get("verify_cost_usd", 0.0),
                "judge_recorded": all(a["verification"]["judge_recorded"] for a in out.get("attempts") or []
                                      if a["verification"]["judge_ran"])}

    def decided_by(out: dict) -> dict | None:
        """Which model made the decision, and how this server got its replies: live, recorded from a live run,
        or the offline stand-in (mock mode, or a conversation never recorded). None: no model was asked."""
        usage = [t["usage"] for t in out.get("turn_log") or [] if t.get("usage")]
        if not usage:
            return None
        if state.settings.llm_mode == "live":
            source = "live"
        else:
            source = "recorded" if all(u.get("recorded") for u in usage) else "stand-in"
        return {"provider": usage[-1]["provider"], "model": usage[-1]["model"], "source": source}

    @app.get("/businesses/{b}/next-steps")
    def next_steps(b: str = Depends(business)):
        """One decided next step per showcase customer. Escalations (possible attacks) are on /replies."""
        with state.lock:
            warm(b)
            cards = [card(b, k, state.decided[b][k]) for k in showcase(b)]
        return [x for x in cards if x["skipped"] not in ("escalated", "open_escalation")]

    @app.get("/businesses/{b}/verification")
    def verification(b: str = Depends(business)):
        """Every showcase draft and what checking it found: one row per draft, in totals and per check."""
        with state.lock:
            warm(b)
            outs = [state.decided[b][k] for k in showcase(b) if state.decided[b][k].get("verification")]
        drafts = [a for o in outs for a in o["attempts"]]
        by_check = {name: sum(1 for a in drafts if name in [c["name"] for c in a["verification"]["checks"]
                                                            if c["applies"] and not c["passed"]])
                    for name in CODE_CHECKS}
        return {"decisions": len(outs), "drafts": len(drafts), "code_checks": len(CODE_CHECKS),
                "caught_by_code": sum(a["verification"]["caught_by"] == "code" for a in drafts),
                "caught_by_judge": sum(a["verification"]["caught_by"] == "judge" for a in drafts),
                "retries": sum(max(0, len(o["attempts"]) - 1) for o in outs),
                "verified": sum(1 for o in outs if o["verification"]["passed"]),
                "sent_to_owner": sum(1 for o in outs if not o["verification"]["passed"]),
                "judge_calls": sum(a["verification"]["judge_ran"] for a in drafts),
                "by_check": {k: v for k, v in by_check.items() if v},
                "first_try": sum(1 for o in outs if len(o["attempts"]) == 1 and o["verification"]["passed"])}

    @app.get("/businesses/{b}/middle-step")
    def middle_step_view(b: str = Depends(business)):
        """Before Pheri writes a message, code checks the customer's stage and the plan against the labelled truth
        set (data/synth/<b>/_truth.json). Money actions need the money bar, nudges the nudge bar."""
        from .actions import BUSINESS_ACTIONS, CATALOG
        from .verify import MONEY_ACTIONS

        rows = []
        for st, row in middle_step_scores(b).items():
            plans = []
            for a, score in row["plan_scores"].items():
                cls = "money" if a in MONEY_ACTIONS else "nudge"
                need = THRESHOLDS[b][cls]
                plans.append({"action": a, "class": cls, "plan_score": score, "threshold": need,
                              "passed": score + 1e-9 >= need and row["stage_score"] + 1e-9 >= need})
            rows.append({"stage": st, "customers": row["customers"], "stage_score": row["stage_score"],
                         "fits": row["fits"], "plans": plans})
        return {"thresholds": THRESHOLDS[b], "stages": rows,
                "actions": [a for a in BUSINESS_ACTIONS[b] if CATALOG[a].customer_facing]}

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
                            "label": g["label"], "language": g["language"], "summary": plain(g["summary"]),
                            # the message's own language (its tag, else code's reading): Bhojpuri stays Bhojpuri
                            "written_in": src.lang or read_language(src.text or ""),
                            "attack": g["attack"], "stop": g["stop"], "screen_before": g["screen_before"],
                            "screen_after": g["screen_after"], "provider": g["provider"], "model": g["model"],
                            "escalation": {"id": esc["id"], "status": esc["status"]} if esc else None})
            return out

    SLOP_STAGES = {"birgunj": ("complaint", "festival", "wholesale"), "brightdesk": ("stuck", "at_risk_renewal", "quiet")}

    @app.get("/businesses/{b}/slop")
    def slop_view(b: str = Depends(business)):
        """Slop vs Pheri for three customers: a plain AI draft (a real, recorded model reply) checked exactly as
        Pheri's own drafts are, next to Pheri's card. The same for every visitor: it changes nothing."""
        from . import slop

        with state.lock:
            warm(b)
            if b not in state.slop:
                keys = []
                for st in SLOP_STAGES[b]:
                    in_stage = [k for k in showcase(b) if state.stages[b][k].stage == st
                                and not state.decided[b][k].get("skipped")]  # not a customer Pheri stopped or holds
                    wrote = [k for k in in_stage if any(src.kind in ("message", "ticket") and src.text
                                                        for src in state.data[b].customers[k].sources)]
                    k = (wrote or in_stage or [None])[0]  # someone who wrote, if the stage has one
                    if k:
                        keys.append(k)
                checker = MemoryStore(b)
                seed(checker, state.llm, by=DEMO_SETUP)
                state.slop[b] = [slop.compare(state.data[b], k, checker, state.llm, CLOCKS[b][0]) for k in keys]
            return [{**x, "pheri": card(b, x["customer"]["key"], state.decided[b][x["customer"]["key"]])}
                    for x in state.slop[b]]

    def timeline(b: str, cards: list[dict], night: list[dict]) -> list[dict]:
        """Tonight, message by message, in the order they came in: what each customer wrote (or said, for a voice
        note), and what happened: stopped, blocked by a rule, waiting for the owner, or scheduled; with every draft
        Pheri wrote, so a draft caught and rewritten shows as it really happened."""
        by_key = {c["customer"]["key"]: c for c in cards}
        out = []
        for n in night:
            cu = state.data[b].customers.get(n["customer"])
            src = next((x for x in cu.sources if x.id == n["message"]), None) if cu else None
            c = by_key.get(n["customer"])
            if src is None or c is None:
                continue
            if c["skipped"] in ("escalated", "open_escalation"):
                outcome = "stopped"
            elif c["skipped"] == "do_not_contact":
                outcome = "blocked"
            else:
                outcome = (c["action"] or {}).get("status") or "no_action"
            note = state.voice[b].get(src.id)
            out.append({"at": src.at, "customer": c["customer"], "lang": src.lang, "kind": src.kind, "text": src.text,
                        "voice": note["says"] if note else None, "outcome": outcome, "action": c["decision"]["action"],
                        "sends_at_local": c.get("sends_at_local"), "waits_for_owner": c.get("waits_for_owner"),
                        "drafts": c.get("drafts") or [], "holding_reply": c.get("holding_reply")})
        return sorted(out, key=lambda x: x["at"] or "")

    def rule_moments(b: str, cards: list[dict]) -> list[dict]:
        """Where the owner's rules stopped something tonight: a customer who asked not to be contacted, or a step a
        rule refused inside the decision (the model asked check_rules; code said no). Never the middle step's bar."""
        out = []
        for c in cards:
            k = c["customer"]["key"]
            if c["skipped"] == "do_not_contact":
                out.append({"customer": c["customer"], "rule": "Asked not to be contacted", "refused": None,
                            "then": "Pheri sent nothing and asked no model."})
                continue
            for pre in state.decided[b][k].get("prechecks") or []:
                said = [v for v in pre.get("violations") or [] if "truth set" not in v and "code's stage" not in v]
                if not pre.get("allowed") and said:
                    out.append({"customer": c["customer"], "rule": said[0], "refused": pre["action"],
                                "then": c["decision"]["action"]})
                    break
        return out

    @app.get("/businesses/{b}/brief")
    def brief(b: str = Depends(business)):
        """The owner's morning: what the night shift read, wrote, scheduled, held back and stopped, from the same
        cards, replies and audit log the other pages show. Counted in code; no model is asked."""
        with state.lock:
            warm(b)
            cards = [card(b, k, state.decided[b][k]) for k in showcase(b)]
        reps = replies(b)
        truth = json.loads((REPO_ROOT / "data" / "synth" / b / "_truth.json").read_text(encoding="utf-8"))
        if truth.get("night"):  # the brief counts tonight's messages, not every older one Pheri re-read
            tonight = {n["message"] for n in truth["night"]}
            reps = [r for r in reps if r["source_id"] in tonight]
        status = lambda c: (c["action"] or {}).get("status")  # noqa: E731
        talking = [c for c in cards if c["skipped"] not in ("escalated", "open_escalation")]
        need = [c for c in talking if (c["approval"] or {}).get("decision") == "pending"
                or c["decision"]["action"] == "task_for_owner"]
        voice = list(state.voice[b].values())
        with state.lock:  # each attack's fixed reply, written by code (pheri/holding.py)
            stopped = [{**r, "holding_reply": holding(b, r["customer"]["key"])} for r in reps if r["attack"]]
        langs: dict[str, int] = {}
        written = [r for r in reps if r["kind"] != "voice_note"]  # a voice note is counted as a voice note, once
        for r in written:
            langs[r["written_in"]] = langs.get(r["written_in"], 0) + 1
        twin_file = TWIN_DIR / f"{b}-n5000-seed7.json"
        proof = None
        if twin_file.exists():
            o = json.loads(twin_file.read_text(encoding="utf-8"))["overall"]
            proof = {"treated": o["treated"]["rate"], "holdout": o["holdout"]["rate"], "lift_pp": o["lift_pp"],
                     "ci_pp": o["ci_pp"], "verdict": o["verdict"], "customers": 5000,
                     "outcome": "ordered" if b == "birgunj" else "responded"}
        clock = CLOCKS[b]
        return {"night": clock[0].isoformat(), "morning": clock[1].isoformat(),
                "read": {"messages": len(written), "by_language": langs,
                         "voice_notes": {"read": sum(v["status"] != voice_module.UNREADABLE for v in voice),
                                         "unreadable": sum(v["status"] == voice_module.UNREADABLE for v in voice)}},
                "customers": len(talking),
                "scheduled": [c for c in talking if status(c) == "scheduled"],
                "sent": [c for c in talking if status(c) == "executed" and c["decision"]["action"] != "task_for_owner"],
                "need_you": need,
                "blocked": [c for c in talking if status(c) == "blocked"],
                "rule_moments": rule_moments(b, cards),
                "timeline": timeline(b, cards, truth.get("night") or []),
                "stopped": stopped,
                "unreadable_voice": [{"customer": v["customer"], "name": state.data[b].customers[v["customer"]].name,
                                      "lang": v["lang"], "says": v["says"]}
                                     for v in voice if v["status"] == voice_module.UNREADABLE],
                "voice_stand_in": any(v["status"] == voice_module.STAND_IN for v in voice),
                "proof": proof, "public_demo": state.public_demo, "mode": state.settings.llm_mode}

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
        live = SPEND_SNAPSHOT.exists() and json.loads(SPEND_SNAPSHOT.read_text(encoding="utf-8"))
        return {"mode": state.settings.llm_mode, "providers": out, "as_of": datetime.now().isoformat(timespec="seconds"),
                "max_call_usd": state.settings.max_call_usd, "by_purpose": state.llm.ledger.breakdown(),
                "live_runs": live or None}

    return app


def __getattr__(name: str):
    # `uvicorn pheri.app:app` builds the app on first use, so importing this module never loads data or seeds.
    if name == "app":
        return create_app()
    raise AttributeError(name)
