"""A small live run of Day 2: compile the seed rule, then profile + decide for Maya and four others.

    python scripts/live_decide.py            # mock: prints the worst-case cost, spends nothing
    python scripts/live_decide.py --live     # real calls; refused up front if the worst case is over --budget
    python scripts/live_decide.py --live --backstop-only   # owner's call: only the ledger cap stops it
    python scripts/live_decide.py --live --limit 1 --budget 0.16   # Maya only
    python scripts/live_decide.py --live --limit 1 --budget 0.10 --private   # Maya, decided on Muse Spark Open

The four others are the first Brightdesk customers (in file order) in four other journey stages, so
the sample covers different kinds of next step. The worst case assumes every decision uses all its
turns at the full output limit and every turn re-reads a profile-sized tool result. As a backstop the
Meta cap for this one process is lowered to "spent so far + budget", so the ledger itself refuses
any call that would go past the budget. The seed rule is compiled once and the compiled checks are
saved in .pheri/ (git-ignored); later runs confirm the saved checks instead of paying to compile again.
"""

import dataclasses
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.stdout.reconfigure(encoding="utf-8")

LIVE = "--live" in sys.argv
BUDGET = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 0.40
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 5  # --limit 1: Maya only
# --private: decide on Muse Spark Open (Meta's open-weight model, served by a partner, self-hostable).
# The budget then applies to each provider: Meta (rule, profiles) and Baseten (decisions).
PRIVATE = "--private" in sys.argv
os.environ["PHERI_LLM_MODE"] = "live" if LIVE else "mock"
REPO = Path(__file__).resolve().parents[1]
if not LIVE:  # mock rows cost nothing, but they don't belong in the real ledger
    os.environ["PHERI_LEDGER_PATH"] = str(REPO / ".pheri" / "mock-ledger.sqlite")
COMPILED = REPO / ".pheri" / "seed_rules_brightdesk.json"  # compile once, reuse after

from pheri import decide as decide_mod  # noqa: E402
from pheri import profile as profile_mod  # noqa: E402
from pheri import rules as rules_mod  # noqa: E402
from pheri.actions import ProposedAction  # noqa: E402
from pheri.journey import stage  # noqa: E402
from pheri.ledger import Ledger  # noqa: E402
from pheri.llm import LLM, _estimate_input_tokens  # noqa: E402
from pheri.pricing import cost_usd, price_for  # noqa: E402
from pheri.privacy import private_mode, set_private_mode  # noqa: E402
from pheri.runlog import call_record, save_run  # noqa: E402
from pheri.store import MemoryStore  # noqa: E402

MAYA = "maya.okafor@pinecrest.example"
OTHER_STAGES = ("at_risk_renewal", "expanding", "onboarding", "quiet")
PRICE = price_for("meta", "muse-spark-1.3")


def sample(ds) -> list[str]:
    keys, wanted = [MAYA], list(OTHER_STAGES)
    for key, c in ds.customers.items():
        facts, prov = profile_mod.compute_facts(c, ds.business)
        s = stage(ds.business, facts, prov).stage
        if key != MAYA and s in wanted:
            keys.append(key)
            wanted.remove(s)
    return keys


def seed_once(store, llm):
    if not COMPILED.exists():
        drafts = rules_mod.seed(store, llm, by="owner:demo")
        COMPILED.parent.mkdir(exist_ok=True)
        COMPILED.write_text(json.dumps([{"source_text": d.source_text, "compiled": d.compiled()} for d in drafts]),
                            encoding="utf-8")
        return drafts, "compiled now"
    drafts = []
    for saved in json.loads(COMPILED.read_text(encoding="utf-8")):
        rid = store.add_rule(saved["source_text"][:80], saved["source_text"], saved["compiled"])
        store.audit("owner:demo", "rule_proposed", "rule", rid, saved["compiled"])
        drafts.append(rules_mod.confirm(store, rid, by="owner:demo"))
    return drafts, f"compiled earlier, reused from {COMPILED.name}"


def worst_case(ds, keys, store) -> dict:
    tok = _estimate_input_tokens
    compile_in = tok([{"role": "system", "content": rules_mod.SYSTEM},
                      {"role": "user", "content": json.dumps({"business": "brightdesk",
                                                              "rule": rules_mod.SEED_RULES["brightdesk"][0]})}])
    out = {"compile": 0.0 if COMPILED.exists() else cost_usd(PRICE, compile_in, rules_mod.MAX_OUTPUT_TOKENS),
           "profiles": 0.0, "decisions": 0.0}
    tools = len(json.dumps(decide_mod.TOOLS)) // 3 + 1
    allowed = len(json.dumps(decide_mod._allowed_view(store))) // 3
    for key in keys:
        c = ds.customers[key]
        sources = profile_mod._recent(c.sources)
        if sources:
            p_in = tok([{"role": "system", "content": profile_mod.SYSTEM},
                        {"role": "user", "content": profile_mod._prompt(c, sources)}])
            out["profiles"] += cost_usd(PRICE, p_in, profile_mod.MAX_OUTPUT_TOKENS)
        facts, _ = profile_mod.compute_facts(c, ds.business)
        # A profile view with room for a full set of insights: every source quoted in full once.
        view = len(json.dumps({"facts": facts, "insights": [s.text for s in sources]}, default=str)) // 3 + allowed
        base = tok([{"role": "system", "content": decide_mod.SYSTEM}, {"role": "user", "content": "x" * 200}]) + tools
        # The profile and the allowed actions are given once (repeat reads get a one-line note); every turn
        # after that re-reads the full output limit plus a check_rules-sized result.
        per_turn = decide_mod.MAX_OUTPUT_TOKENS + 200
        if PRIVATE:  # one call: strict json_schema only, no instructions retry
            one = tok([{"role": "system", "content": decide_mod.PRIVATE_SYSTEM}]) + view + 400
            price = price_for("baseten", "meta-models/muse-spark-open-1026")
            limit = decide_mod.PRIVATE_MAX_OUTPUT_TOKENS
            out["decisions"] += cost_usd(price, one, limit)
            continue
        for turn in range(decide_mod.MAX_TURNS):
            context = base + (view + per_turn * turn if turn else 0)
            out["decisions"] += cost_usd(PRICE, context, decide_mod.MAX_OUTPUT_TOKENS)
    out["total"] = sum(out.values())
    return out


def over_budget(estimate: dict) -> bool:
    if PRIVATE:  # each provider has its own budget
        return estimate["compile"] + estimate["profiles"] > BUDGET or estimate["decisions"] > BUDGET
    return estimate["total"] > BUDGET


MODE_LABELS = {"suggest": "suggest", "ask_owner": "ask owner", "act_alone": "act alone"}


def card(o, prof, proof, store, run_usd: float, total, cap_usd: float) -> str:
    """Maya's decision in the owner's format."""
    d = o.decision
    quotes = "; ".join(f'"{e["value"]}" ({e["ref"]})' for e in o.evidence
                       if e["ref"] not in prof.facts and e["ref"] != "journey_stage")
    facts = ", ".join(f"{e['ref']}={e['value']}" for e in o.evidence if e["ref"] in prof.facts or
                      e["ref"] == "journey_stage")
    rules = {r.id: r for r in rules_mod.active_rules(store)}
    tried = [a["details"] for a in store.audit_log(o.customer_key)
             if a["event"] == "rule_precheck" and a["details"]["action"] == "offer_discount"]
    dry = [x for x in o.prechecks if o.private and x["action"] == "offer_discount"]
    blocked_by = [r for r in proof.results if not r["passed"]]
    rule = rules.get(blocked_by[0]["rule_id"]) if blocked_by else None
    rule_text = (f"rule \"{rule.source_text}\" ({'; '.join(rules_mod.describe(c) for c in rule.checks)})"
                 if rule else "no rule")
    if dry:
        attempt = ("Code dry-ran a 10% discount before the model saw anything -> "
                   + ("blocked: " + "; ".join(dry[0]["violations"]) if not dry[0]["allowed"] else "allowed"))
    elif tried:
        attempt = "; ".join(f"Pheri tried offer_discount {t['discount_pct']:g}% -> "
                            f"{'blocked: ' + '; '.join(t['violations']) if not t['allowed'] else 'allowed'}"
                            for t in tried)
    else:
        attempt = ("Pheri did not try a discount this run. Code check of a 10% discount for Maya -> "
                   f"allowed={proof.allowed}: {'; '.join(proof.violations)}")
    action = o.action or {}
    lines = [
        f"ACTION:   {d['action']} via {d['channel']}" + (f", {d['discount_pct']:g}% off" if d["discount_pct"] else "")
        + f"  [{action.get('status', 'no_action')}]",
        f"          message: {d['message']}",
        f"WHY THIS: {d['why_this']}",
        f"          evidence: {quotes or 'none'}",
        f"          facts: {facts or 'none'}",
        f"WHY NOW:  {d['why_now']}",
        f"BLOCKED:  {attempt}",
        f"          by {rule_text}",
        f"CHECKS:   evidence kept {len(o.evidence)}, dropped {len(o.dropped_evidence)}"
        + (f" ({'; '.join(e['reason'] for e in o.dropped_evidence)})" if o.dropped_evidence else "")
        + f"; numbers not backed: {', '.join(o.unsupported_numbers) or 'none'}"
        + f"; message: {'; '.join(o.message_problems) or 'ok'}",
        f"MODE:     {MODE_LABELS.get(action.get('mode'), action.get('mode') or 'n/a')}",
        f"COST:     Meta: this run ${run_usd:.4f}; total Meta spend in the ledger ${total.settled_usd:.4f}"
        + (f" (+ ${total.offset_usd:.2f} offset)" if total.offset_usd else "")
        + f", cap ${cap_usd:.2f}",  # the configured cap, not this run's backstop
    ]
    if o.private:
        lines.insert(0, "PRIVATE MODE: Muse Spark Open via Baseten (Meta's open-weight model, served by a partner, "
                        "self-hostable)")
        steps = private_mode(store)
        lines.insert(1, "          private steps: " + ", ".join(k for k, v in steps.items() if v)
                     + "; on the Meta API: " + (", ".join(k for k, v in steps.items() if not v) or "nothing"))
    if o.fallback:
        lines.insert(1, f"          FALLBACK: {o.fallback}")
    return "\n".join(lines)



def main() -> int:
    ds = profile_mod.load("brightdesk")
    keys = sample(ds)[:LIMIT]
    estimate = worst_case(ds, keys, MemoryStore("brightdesk"))
    print("Sample:", ", ".join(keys))
    print("Worst case: " + ", ".join(f"{k} ${v:.4f}" for k, v in estimate.items()) + f"  (budget ${BUDGET:.2f})")
    if over_budget(estimate) and "--backstop-only" not in sys.argv:
        print("Worst case is over the budget: nothing was sent. (--backstop-only runs anyway; the ledger cap "
              "still refuses any call past the budget.)")
        return 2
    if not LIVE:
        print("Mock mode: add --live to run for real.")

    before = Ledger().totals("meta")
    before_bt = Ledger().totals("baseten")
    if LIVE:
        os.environ["PHERI_META_CAP_USD"] = f"{before.committed_usd + BUDGET:.6f}"  # this process only
        os.environ["PHERI_BASETEN_CAP_USD"] = f"{before_bt.committed_usd + BUDGET:.6f}"
    llm = LLM()
    results = []  # every call's LLMResult, to show where the output tokens went
    real_complete = llm.complete
    def recorded(messages, **kw):
        try:
            r = real_complete(messages, **kw)
        except Exception as exc:  # a cut-off answer still used (and billed) its tokens
            if getattr(exc, "result", None) is not None:
                results.append((kw.get("purpose"), exc.result))
            raise
        results.append((kw.get("purpose"), r))
        return r

    llm.complete = recorded
    store = MemoryStore("brightdesk")

    maya = None
    outcomes = []
    drafts, how = seed_once(store, llm)
    if PRIVATE:
        set_private_mode(store, guard=True, decide=True, by="owner:demo")
    for d in drafts:
        print(f"\nRule ({how}): {d.source_text!r} -> {[c.model_dump() for c in d.checks]}")
        print(f"  Owner confirms: {d.described}  unsupported={d.unsupported}")

    for key in keys:
        p = profile_mod.build_profile(ds, key, llm)
        o = decide_mod.decide(p, store, llm)
        outcomes.append(dataclasses.asdict(o))
        status = o.action["status"] if o.action else "no_action"
        print(f"\n== {p.name} ({key}) stage={stage('brightdesk', p.facts).stage} -> {o.decision['action']} "
              f"[{status}] turns={o.turns} fallback={o.fallback} private={o.private}")
        print(f"  channel={o.decision['channel']} discount={o.decision['discount_pct']}")
        print(f"  message: {o.decision['message']}")
        print(f"  why this: {o.decision['why_this']}")
        print(f"  why now:  {o.decision['why_now']}")
        print(f"  evidence kept: {o.evidence}")
        if o.dropped_evidence:
            print(f"  evidence dropped: {o.dropped_evidence}")
        print(f"  check_rules calls in the loop: {o.prechecks}")
        if o.action:
            print(f"  final code check: {o.action['rule_check']}")
        if key == MAYA:
            print("  tool trace:")
            for t in o.trace:
                print(f"    {t['tool']}({t['arguments']}) -> {t['output'][:160]}")
            proof = rules_mod.check(rules_mod.active_rules(store),
                                    ProposedAction(kind="offer_discount", channel="email", discount_pct=10),
                                    decide_mod.context_for(store, p))
            print(f"  PROOF: a 10% discount for Maya through the code check -> allowed={proof.allowed}, "
                  f"violations={proof.violations}")
            maya = (o, p, proof)

    after = Ledger().totals("meta")
    print(f"\nLedger (meta): settled ${before.settled_usd:.6f} -> ${after.settled_usd:.6f}; "
          f"this run ${after.settled_usd - before.settled_usd:.6f}; still reserved ${after.reserved_usd:.6f}")
    after_bt = Ledger().totals("baseten")
    bt_run = after_bt.settled_usd - before_bt.settled_usd
    print(f"Ledger (baseten): settled ${before_bt.settled_usd:.6f} -> ${after_bt.settled_usd:.6f}; this run ${bt_run:.6f}")
    print("\nOutput tokens per call (reasoning counts as output and is billed):")
    for _, r in results:
        answer_est = round(len(r.text) / 3.5)  # JSON answers run ~3.5 characters a token
        reasoning = (f"{r.reasoning_tokens} reported" if r.reasoning_tokens is not None
                     else f"~{max(0, r.output_tokens - answer_est)} (output minus answer estimate)")
        print(f"  {r.provider:8} {r.model:34} output={r.output_tokens:5}  reasoning={reasoning}  "
              f"answer~{answer_est} ({len(r.text)} chars)"
              + (f"  reasoning_text={r.reasoning_chars} chars" if r.reasoning_chars else "")
              + (f"  CUT OFF ({r.incomplete})" if r.incomplete else ""))
    if maya:
        text = card(*maya, store, after.settled_usd - before.settled_usd, after, before.cap_usd)
        if PRIVATE:
            text += (f"\n          Baseten (Muse Spark Open): this run ${bt_run:.4f}; total ${after_bt.settled_usd:.4f}, "
                     f"cap ${before_bt.cap_usd:.2f} (placeholder prices in pricing.py: an estimate)")
        print("\n" + text)
    if LIVE:
        path = save_run("decide", {
            "args": sys.argv[1:], "budget_usd": BUDGET, "private": private_mode(store), "worst_case": estimate,
            "outcomes": outcomes, "calls": [call_record(purpose, r) for purpose, r in results],
            "audit": store.audit_log(),
            "ledger": {"meta": {"before": before.settled_usd, "after": after.settled_usd},
                       "baseten": {"before": before_bt.settled_usd, "after": after_bt.settled_usd}}})
        print(f"\nSaved this run: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
