"""Probe: how the guard reads Bhojpuri and Roman Nepali today, before Birgunj depends on it.

    python scripts/probe_languages.py                      # mock: no network
    python scripts/probe_languages.py --live --budget 0.05 # 20 messages per provider, real calls

Reads evals/probe_bho_roman.jsonl (20 messages, not yet reviewed by a native speaker). For each provider
(Muse Spark 1.3 on Meta, Muse Spark Open on Baseten) it prints the label the model gave, the language code
it gave before code checks it, the final verdict after code, and the totals. --budget is per provider: the
ledger cap is lowered to "spent so far + budget" for this process, so nothing past it can be sent.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--budget", type=float, default=None)
    args = ap.parse_args()
    if args.live and args.budget is None:
        print("--live needs --budget (USD per provider).")
        return 2
    if args.live:
        os.environ["PHERI_LLM_MODE"] = "live"

    from pheri import guard as g
    from pheri.config import Settings
    from pheri.ledger import Ledger
    from pheri.llm import LLM

    rows = [json.loads(line) for line in (ROOT / "evals" / "probe_bho_roman.jsonl").read_text(encoding="utf-8").splitlines() if line]
    base = Settings()
    caps = {}
    if args.live:
        led = Ledger(base)
        caps = {"meta_cap_usd": led.totals("meta").committed_usd + args.budget,
                "baseten_cap_usd": led.totals("baseten").committed_usd + args.budget}
    llm = LLM(Settings(**caps)) if caps else LLM(base)
    report = {}
    for mode in ("meta", "private"):
        where = g.PROVIDERS[mode]
        provider, model = where["provider"], where["model"] or llm.default_model(where["provider"])
        tally, cost = Counter(), 0.0
        print(f"\n== {provider} / {model}")
        for r in rows:
            messages = [{"role": "system", "content": g.SYSTEM},
                        {"role": "user", "content": g._payload(r["text"], "birgunj", "whatsapp")}]
            try:
                res = llm.complete_json(messages, schema=g.GuardOutput, provider=provider, model=model,
                                        purpose=g.PURPOSE, effort=where["effort"], max_tokens=g.MAX_OUTPUT_TOKENS)
                out, cost = res.parsed, cost + res.cost_usd
            except Exception as exc:  # noqa: BLE001
                print(f"  {r['id']}  ERROR {type(exc).__name__}: {str(exc)[:120]}")
                tally["error"] += 1
                continue
            final = g._settle(r["id"], out, g.screen(r["text"]), g.wants_stop(r["text"]))
            label_ok = final.label == r["label"]
            lang_ok = out.language.strip().lower() == r["lang"]
            hindi_family = r["lang"] == "bho" and out.language.strip().lower() == "hi"
            tally["label_ok"] += label_ok
            tally["lang_ok"] += lang_ok
            tally["bho_as_hi"] += hindi_family
            tally["code_caught"] += bool(final.screen_before)
            print(f"  {r['id']}  want {r['label']:15} {r['lang']:3} | model {out.label:15} lang {out.language!r:6}"
                  f" | final {final.label:15} {'OK ' if label_ok else 'XX '} code_hits={final.screen_before}")
        n = len(rows)
        report[provider] = {"n": n, **tally, "cost_usd": round(cost, 6)}
        print(f"  label right {tally['label_ok']}/{n}, language code right {tally['lang_ok']}/{n} "
              f"(Bhojpuri read as Hindi: {tally['bho_as_hi']}/10), code screen hits {tally['code_caught']}, "
              f"errors {tally['error']}, cost ${cost:.6f}")
    print("\n" + json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
