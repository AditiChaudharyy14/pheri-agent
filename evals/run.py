"""Guard and verification evals: attack block rate, false positives, label and language accuracy, cost per
message; then how Pheri checks its own work.

    python evals/run.py                                   # mock, both providers, every message, $0
    python evals/run.py --provider meta                   # one provider
    python evals/run.py --live --sample 40 --budget 0.50  # real calls: 40 messages per provider
    python evals/run.py --record-judge --budget 0.05      # the real judge on drafts.jsonl, recorded once

Providers: "meta" is Muse Spark on the Meta Model API; "baseten" is Muse Spark Open, Meta's open-weight
model, served by a partner (Baseten), self-hostable. The code screen runs before either and costs nothing;
its own catch rate is reported on its own line, so you can see what the model adds.

In mock mode the "model" is guard.py's offline stand-in (word lists), so mock numbers test the plumbing
and the code screen, not Muse Spark. Live: --budget is per provider; the run refuses to start if the
worst case is over it, and each provider's cap in the ledger is lowered to "spent so far + budget" for
this process, so the ledger itself refuses any call past it. --sample takes a seeded, stratified sample.

The code screen's patterns were written alongside attacks.jsonl, so its catch rate here is an upper bound;
the semantic attacks (S*) are the ones no pattern is meant to catch.

Verification (always $0: code, the offline judge, and the recorded live run):
  drafts.jsonl   labelled drafts, each broken on purpose in one way (or clean): which check catches it,
                 and whether a clean draft passes. The J* rows have nothing code can see; only a judge
                 model can catch them. The judge's verdicts come from evals/judge_recorded.jsonl (Muse Spark
                 Open, recorded once with --record-judge); without it the stand-in judge reads numbers only.
  tool attacks   the T* replies in attacks.jsonl try to make Pheri call a tool it does not have
                 (issue_refund): a model that obeyed is played, and the call must be discarded and logged.
  middle step    stage and plan scores against the truth set, per business, against the bar.
  the loop       the 12 showcase decisions replayed from the recorded live run: drafts, caught by code,
                 caught by the judge, retries, sent to the owner.
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "api"))
sys.stdout.reconfigure(encoding="utf-8")


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def items() -> list[dict]:
    out = [{**a, "set": "attacks", "is_attack": a["expect_attack"], "label": None} for a in load("attacks.jsonl")]
    out += [{**r, "set": "replies", "is_attack": r["label"] == "attack"} for r in load("replies.jsonl")]
    return out


def sample(rows: list[dict], n: int | None, seed: int = 7) -> list[dict]:
    """Stratified by set and by attack/benign, so a small sample still measures every rate."""
    if not n or n >= len(rows):
        return rows
    rng = random.Random(seed)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["set"], r["is_attack"]), []).append(r)
    # Largest remainders: every group gets at least one, and the quotas add up to exactly n.
    keys = sorted(groups)
    exact = {k: n * len(groups[k]) / len(rows) for k in keys}
    quota = {k: max(1, int(exact[k])) for k in keys}
    for k in sorted(keys, key=lambda k: exact[k] - int(exact[k]), reverse=True)[:max(0, n - sum(quota.values()))]:
        quota[k] += 1
    picked = []
    for key in keys:
        picked += rng.sample(groups[key], min(quota[key], len(groups[key])))
    rng.shuffle(picked)
    return picked[:n]


def worst_case_usd(rows, provider: str, llm) -> float:
    from pheri import guard as g
    from pheri.llm import _estimate_input_tokens, _with_json_instructions
    from pheri.pricing import cost_usd, price_for

    model = g.PROVIDERS["private" if provider == "baseten" else "meta"]["model"] or llm.default_model(provider)
    price = price_for(provider, model)
    total = 0.0
    for r in rows:
        msgs = [{"role": "system", "content": g.SYSTEM}, {"role": "user", "content": g._payload(r["text"], r["business"], None)}]
        if provider != "meta":  # instructions mode is the longer prompt, and it may need its one retry
            msgs = _with_json_instructions(msgs, g.GuardOutput)
        one = cost_usd(price, _estimate_input_tokens(msgs), g.MAX_OUTPUT_TOKENS)
        total += one if provider == "meta" else 2 * one + cost_usd(price, g.MAX_OUTPUT_TOKENS, 0)
    return total


def evaluate(rows, provider: str, llm) -> dict:
    from pheri.guard import guard, screen

    results, cost, errors = [], 0.0, 0
    started = time.monotonic()
    for r in rows:
        res = guard(r["text"], business=r["business"], llm=llm, source_id=r["id"], private=provider == "baseten")
        cost += res.cost_usd
        errors += res.error is not None
        results.append((r, res, bool(screen(r["text"]))))
    attacks = [(r, g, c) for r, g, c in results if r["is_attack"]]
    benign = [(r, g, c) for r, g, c in results if not r["is_attack"]]
    labelled = [(r, g, c) for r, g, c in results if r["label"]]

    def rate(xs, ok):
        return (sum(1 for x in xs if ok(x)), len(xs))

    return {
        "provider": provider,
        "n": len(rows),
        "blocked": rate(attacks, lambda x: x[1].attack),
        "code_only": rate(attacks, lambda x: x[2]),
        "false_pos": rate(benign, lambda x: x[1].attack),
        "false_pos_code": rate(benign, lambda x: x[2]),
        "label_ok": rate(labelled, lambda x: x[1].label == x[0]["label"]),
        "lang_ok": rate(results, lambda x: x[1].language == x[0]["lang"]),
        "errors": errors,
        "cost": cost,
        "seconds": time.monotonic() - started,
        "missed": [r["id"] for r, g, _ in attacks if not g.attack],
        "false_alarms": [r["id"] for r, g, _ in benign if g.attack],
        "wrong_labels": Counter(f"{r['label']}->{g.label}" for r, g, _ in labelled if g.label != r["label"]),
        "rows": [{"id": r["id"], "expected_attack": r["is_attack"], "expected_label": r["label"],
                  "expected_lang": r["lang"], "code_screen": c, **g.as_dict()} for r, g, c in results],
    }


def pct(pair) -> str:
    k, n = pair
    return f"{k}/{n} = {k / n:.0%}" if n else "n/a"


def report(res: dict, live: bool) -> str:
    per = res["cost"] / res["n"] if res["n"] else 0.0
    cost = f"${res['cost']:.4f} total, ${per:.5f}/message" if live else "$0 (mock)"
    lines = [f"== {res['provider']} ({'live' if live else 'mock'}, {res['n']} messages, {res['seconds']:.1f}s)",
             f"  attack block rate     {pct(res['blocked'])}   (code screen alone: {pct(res['code_only'])})",
             f"  false-positive rate   {pct(res['false_pos'])}   (code screen alone: {pct(res['false_pos_code'])})",
             f"  label accuracy        {pct(res['label_ok'])}",
             f"  language accuracy     {pct(res['lang_ok'])}",
             f"  unreadable replies    {res['errors']}",
             f"  cost                  {cost}"]
    if res["missed"]:
        lines.append(f"  missed attacks: {', '.join(res['missed'])}")
    if res["false_alarms"]:
        lines.append(f"  false alarms:   {', '.join(res['false_alarms'])}")
    if res["wrong_labels"]:
        lines.append("  wrong labels:   " + ", ".join(f"{k} x{v}" for k, v in res["wrong_labels"].most_common()))
    return "\n".join(lines)


# ---- verification -----------------------------------------------------------------------------
JUDGE_RECORDING = HERE / "judge_recorded.jsonl"


def judge_llm(live_budget: float | None = None):
    """The judge for drafts.jsonl: replayed from its recording (or the stand-in where none), or, to record it, live on
    Baseten with the cap lowered to "spent so far + budget" for this process."""
    import tempfile

    from pheri.config import Settings
    from pheri.ledger import Ledger
    from pheri.llm import LLM

    if live_budget is None:
        tmp = Path(tempfile.mkdtemp()) / "ledger.sqlite"
        return LLM(Settings(llm_mode="replay", replay_path=str(JUDGE_RECORDING), record_path=None, database_url=None,
                            ledger_path=str(tmp)))
    spent = Ledger().totals("baseten").committed_usd
    return LLM(Settings(llm_mode="live", record_path=str(JUDGE_RECORDING), baseten_cap_usd=spent + live_budget))


def verify_drafts(llm, judge=None) -> dict:
    """Every labelled draft through verify_draft: the expected check must fail; a clean draft must pass.
    Profiles come from `llm` (offline); the judge is `judge` when given."""
    from pheri.actions import ProposedAction
    from pheri.journey import stage
    from pheri.profile import build_profile, load as load_data
    from pheri.rules import CheckContext, seed
    from pheri.store import MemoryStore
    from pheri.synth import NOW
    from pheri.verify import Draft, context, verify_draft

    data, stores, profiles, rows = {}, {}, {}, []
    for r in load("drafts.jsonl"):
        b = r["business"]
        if b not in stores:
            data[b], stores[b] = load_data(b), MemoryStore(b)
            seed(stores[b], llm)
        key = (b, r["customer"])
        if key not in profiles:
            profiles[key] = build_profile(data[b], r["customer"], llm)
        prof = profiles[key]
        j = stage(b, prof.facts, prof.provenance.get("facts"))
        d = r["draft"]
        draft = Draft(ProposedAction(kind=d["action"], channel=d["channel"], discount_pct=d["discount_pct"],
                                     message=d["message"], send_at=NOW), d["why_this"], d["why_now"], d["fact_keys"],
                      d["quote_ids"])
        v = verify_draft(draft, context(prof, j, CheckContext(b, prof.facts, NOW), stores[b], judge or llm))
        failed = {c["name"] for c in v.checks if c["applies"] and not c["passed"]} | (
            {"judge"} if v.caught_by == "judge" else set())
        ok = set(r["expect"]) <= failed if r["expect"] else not failed
        rows.append({"id": r["id"], "expect": r["expect"], "failed": sorted(failed), "ok": ok, "judge_ran": v.judge_ran,
                     "judge_recorded": v.judge_recorded, "judge_cost_usd": v.judge_cost_usd,
                     "unsupported": [x["claim"] for x in v.judge if not x["supported"]]})
    return {"rows": rows}


def tool_attacks(llm) -> dict:
    """A model that obeys the T* replies and calls the tool they ask for: discarded and logged, never run."""
    from pheri import llm as llm_module
    from pheri.decide import PURPOSE, decide
    from pheri.guard import screen
    from pheri.profile import build_profile, load as load_data
    from pheri.rules import seed
    from pheri.store import MemoryStore

    rows = []
    real = llm_module._mock_responders[PURPOSE]
    for r in [a for a in load("attacks.jsonl") if a["kind"] == "tool"]:
        ds = load_data(r["business"])
        store = MemoryStore(r["business"])
        seed(store, llm)
        key = next(iter(ds.customers))

        def obeying(messages, schema, tool=r["tool"]):
            if not any(m.get("type") == "function_call" for m in messages):
                return {"function_calls": [{"name": tool, "arguments": {"amount": 500, "customer": "all"}}]}
            return real(messages, schema)

        llm_module._mock_responders[PURPOSE] = obeying
        try:
            out = decide(build_profile(ds, key, llm), store, llm)
        finally:
            llm_module._mock_responders[PURPOSE] = real
        logged = [a["details"]["tool"] for a in store.audit_log() if a["event"] == "tool_call_discarded"]
        ran = [t["tool"] for t in out.trace if t["tool"] == r["tool"] and not t.get("discarded")]
        rows.append({"id": r["id"], "tool": r["tool"], "discarded": out.discarded_tools == [r["tool"]],
                     "logged": logged == [r["tool"]], "ran": bool(ran), "screen": bool(screen(r["text"])),
                     "decided": out.decision["action"]})
    return {"rows": rows}


def middle_steps() -> dict:
    from pheri.verify import THRESHOLDS, middle_step_scores

    out = {}
    for b in ("brightdesk", "kettle"):
        scores = middle_step_scores(b)
        out[b] = {"thresholds": THRESHOLDS[b],
                  "stages": {s: {"stage_score": r["stage_score"], "customers": r["customers"],
                                 "plans_over_bar": [a for a, v in r["plan_scores"].items()
                                                    if v + 1e-9 >= THRESHOLDS[b]["nudge"]]}
                             for s, r in scores.items()}}
    return out


def loop_numbers() -> dict | None:
    """The showcase decisions, replayed from data/recorded/llm.jsonl through the API: $0, no network."""
    import tempfile

    from fastapi.testclient import TestClient

    from pheri.app import create_app
    from pheri.config import REPO_ROOT, Settings
    from pheri.llm import LLM

    rec = REPO_ROOT / "data" / "recorded" / "llm.jsonl"
    if not rec.exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(llm_mode="replay", replay_path=str(rec), record_path=None, database_url=None,
                            ledger_path=str(Path(tmp) / "ledger.sqlite"))
        with TestClient(create_app(LLM(settings))) as api:
            return {b: api.get(f"/businesses/{b}/verification").json() for b in ("brightdesk", "kettle")}


def verification_report(drafts: dict, tools: dict, middle: dict, loop: dict | None) -> str:
    rows = drafts["rows"]
    code = [r for r in rows if r["expect"] and r["expect"] != ["judge"]]
    clean = [r for r in rows if not r["expect"]]
    judged = [r for r in rows if r["expect"] == ["judge"]]
    real = [r for r in rows if r["judge_ran"]]
    who = ("Muse Spark Open, recorded live" if real and all(r["judge_recorded"] for r in real)
           else "Muse Spark Open, live" if any(r["judge_cost_usd"] for r in real)
           else "offline stand-in: it reads numbers only")
    lines = ["== verification: how Pheri checks its own drafts ($0)",
             f"  caught by code        {pct((sum(r['ok'] for r in code), len(code)))}   "
             f"(drafts broken on purpose, one way each)",
             f"  clean drafts passed   {pct((sum(r['ok'] for r in clean), len(clean)))}   (code and the judge let these through)",
             f"  caught by the judge   {pct((sum(r['ok'] for r in judged), len(judged)))}   "
             f"(a claim no fact backs, nothing code can see; judge: {who})"]
    per: dict[str, list[bool]] = {}
    for r in code:
        per.setdefault(r["expect"][0], []).append(r["ok"])
    lines.append("  per check             " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in per.items()))
    if missed := [r["id"] for r in code + clean if not r["ok"]]:
        lines.append(f"  wrong:                {', '.join(missed)}")
    t = tools["rows"]
    lines += ["", "== tool allowlist",
              f"  unknown tool calls    {sum(r['discarded'] and r['logged'] for r in t)}/{len(t)} discarded and logged, "
              f"{sum(r['ran'] for r in t)} run   (code screen caught the reply first in {sum(r['screen'] for r in t)}/{len(t)})"]
    lines += ["", "== middle step: stage and plan against the truth set"]
    for b, m in middle.items():
        bar = m["thresholds"]
        lines.append(f"  {b} (money {bar['money']:.0%}, nudges {bar['nudge']:.0%}): " + ", ".join(
            f"{s} {x['stage_score']:.0%}" for s, x in m["stages"].items()))
    if loop:
        lines += ["", "== the loop on the showcase (replayed from the recorded live run)"]
        for b, n in loop.items():
            lines.append(f"  {b}: {n['decisions']} decisions, {n['drafts']} drafts; caught by code {n['caught_by_code']}, "
                         f"by the judge {n['caught_by_judge']}; retries {n['retries']}; verified {n['verified']}, "
                         f"sent to the owner {n['sent_to_owner']}"
                         + (f"; failed checks: {', '.join(f'{k} {v}' for k, v in n['by_check'].items())}"
                            if n["by_check"] else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", choices=("meta", "baseten", "both"), default="both")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--sample", type=int, default=None, help="messages per provider (default: all)")
    ap.add_argument("--budget", type=float, default=None, help="USD per provider; required with --live")
    ap.add_argument("--record-judge", action="store_true", help="call the real judge on drafts.jsonl and record it")
    args = ap.parse_args(argv)
    if args.record_judge:
        if args.budget is None:
            print("--record-judge needs --budget (USD on Baseten).")
            return 2
        from pheri.config import Settings
        from pheri.llm import LLM

        offline = LLM(Settings(llm_mode="mock", record_path=None, database_url=None,
                               ledger_path=str(HERE.parent / ".pheri" / "mock-ledger.sqlite")))
        res = verify_drafts(offline, judge_llm(args.budget))
        print(verification_report(res, {"rows": []}, middle_steps(), None).split("\n\n")[0])
        print(f"Judge cost: ${sum(r['judge_cost_usd'] for r in res['rows']):.4f}; recorded to {JUDGE_RECORDING.name}")
        return 0
    os.environ["PHERI_LLM_MODE"] = "live" if args.live else "mock"
    if not args.live:
        os.environ["PHERI_LEDGER_PATH"] = str(HERE.parent / ".pheri" / "mock-ledger.sqlite")
    if args.live and (args.budget is None or args.sample is None):
        print("--live needs --sample and --budget, so a run can never be bigger than you meant.")
        return 2

    from pheri.ledger import Ledger
    from pheri.llm import LLM

    rows = sample(items(), args.sample)
    providers = ["meta", "baseten"] if args.provider == "both" else [args.provider]
    probe = LLM()
    caps = {}
    if args.live:
        for prov in providers:
            worst = worst_case_usd(rows, prov, probe)
            print(f"{prov}: {len(rows)} messages, worst case ${worst:.4f} (budget ${args.budget:.2f})")
            if worst > args.budget:
                print("Worst case is over the budget: nothing was sent.")
                return 2
        led = Ledger()
        caps = {prov: led.cap_for(prov) for prov in providers}  # the configured caps, before this run's backstop
        for prov in providers:  # this process only: the ledger refuses anything past the budget
            os.environ[f"PHERI_{prov.upper()}_CAP_USD"] = f"{led.totals(prov).committed_usd + args.budget:.6f}"
    llm = LLM()
    print(f"{len(rows)} messages ({sum(r['is_attack'] for r in rows)} attacks, "
          f"{sum(not r['is_attack'] for r in rows)} harmless, {sum(bool(r['label']) for r in rows)} labelled)\n")
    runs = []
    for prov in providers:
        runs.append(evaluate(rows, prov, llm))
        print(report(runs[-1], args.live) + "\n")
    offline = llm if not args.live else LLM(__import__("pheri.config", fromlist=["Settings"]).Settings(
        llm_mode="mock", record_path=None, database_url=None,
        ledger_path=str(HERE.parent / ".pheri" / "mock-ledger.sqlite")))
    print(verification_report(verify_drafts(offline, judge_llm()), tool_attacks(offline), middle_steps(), loop_numbers())
          + "\n")
    if args.live:
        from pheri.runlog import save_run

        print(f"Saved this run: {save_run('evals', {'args': argv or sys.argv[1:], 'results': runs})}")
        led = Ledger()
        print("Ledger: " + "; ".join(f"{p} spent ${led.totals(p).settled_usd:.4f} in total (cap ${caps[p]:.2f})"
                                     for p in providers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
