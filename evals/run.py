"""Guard evals: attack block rate, false positives, label and language accuracy, cost per message.

    python evals/run.py                                   # mock, both providers, every message, $0
    python evals/run.py --provider meta                   # one provider
    python evals/run.py --live --sample 40 --budget 0.50  # real calls: 40 messages per provider

Providers: "meta" is Muse Spark on the Meta Model API; "baseten" is Muse Spark Open, Meta's open-weight
model, served by a partner (Baseten), self-hostable. The code screen runs before either and costs nothing;
its own catch rate is reported on its own line, so you can see what the model adds.

In mock mode the "model" is guard.py's offline stand-in (word lists), so mock numbers test the plumbing
and the code screen, not Muse Spark. Live: --budget is per provider; the run refuses to start if the
worst case is over it, and each provider's cap in the ledger is lowered to "spent so far + budget" for
this process, so the ledger itself refuses any call past it. --sample takes a seeded, stratified sample.

The code screen's patterns were written alongside attacks.jsonl, so its catch rate here is an upper bound;
the semantic attacks (S*) are the ones no pattern is meant to catch.
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
    picked = []
    for key in sorted(groups):
        g = groups[key]
        picked += rng.sample(g, max(1, round(n * len(g) / len(rows))))
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", choices=("meta", "baseten", "both"), default="both")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--sample", type=int, default=None, help="messages per provider (default: all)")
    ap.add_argument("--budget", type=float, default=None, help="USD per provider; required with --live")
    args = ap.parse_args(argv)
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
    if args.live:
        for prov in providers:
            worst = worst_case_usd(rows, prov, probe)
            print(f"{prov}: {len(rows)} messages, worst case ${worst:.4f} (budget ${args.budget:.2f})")
            if worst > args.budget:
                print("Worst case is over the budget: nothing was sent.")
                return 2
        led = Ledger()
        for prov in providers:  # this process only: the ledger refuses anything past the budget
            os.environ[f"PHERI_{prov.upper()}_CAP_USD"] = f"{led.totals(prov).committed_usd + args.budget:.6f}"
    llm = LLM()
    print(f"{len(rows)} messages ({sum(r['is_attack'] for r in rows)} attacks, "
          f"{sum(not r['is_attack'] for r in rows)} harmless, {sum(bool(r['label']) for r in rows)} labelled)\n")
    for prov in providers:
        print(report(evaluate(rows, prov, llm), args.live) + "\n")
    if args.live:
        led = Ledger()
        print("Ledger: " + "; ".join(f"{p} spent ${led.totals(p).settled_usd:.4f} of ${led.cap_for(p):.2f}"
                                     for p in providers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
