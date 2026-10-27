"""One live "What Pheri learned" report from a twin results file, written by Muse Wonder, checked in code.

    python scripts/live_learn.py .pheri/twin/brightdesk-n200-seed7.json            # mock, $0
    python scripts/live_learn.py .pheri/twin/brightdesk-n200-seed7.json --live --budget 0.20

Refused up front if the worst case (the whole prompt plus the full output limit at Wonder's price) is over
--budget; the Meta cap for this one process is lowered to "spent so far + budget" as a backstop. The run is
saved to .pheri/runs/ with the report, the check results and the model's answer text.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.stdout.reconfigure(encoding="utf-8")

LIVE = "--live" in sys.argv
BUDGET = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 0.20
os.environ["PHERI_LLM_MODE"] = "live" if LIVE else "mock"
REPO = Path(__file__).resolve().parents[1]
if not LIVE:
    os.environ["PHERI_LEDGER_PATH"] = str(REPO / ".pheri" / "mock-ledger.sqlite")

from pheri import learn  # noqa: E402
from pheri.ledger import Ledger  # noqa: E402
from pheri.llm import LLM, _estimate_input_tokens  # noqa: E402
from pheri.pricing import cost_usd, price_for  # noqa: E402
from pheri.runlog import call_record, save_run  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1])
    results = json.loads(path.read_text(encoding="utf-8"))
    facts = learn.catalogue(results)
    prompt = [{"role": "system", "content": learn.SYSTEM},
              {"role": "user", "content": json.dumps({"business": results["business"], "facts": facts})}]
    schema_tokens = len(json.dumps(learn.report_schema([s["stage"] for s in results["stages"]], list(facts))
                                   .model_json_schema())) // 3
    worst = cost_usd(price_for("meta", learn.MODEL), _estimate_input_tokens(prompt) + schema_tokens,
                     learn.MAX_OUTPUT_TOKENS)
    print(f"{path.name}: {len(facts)} facts; worst case ${worst:.4f} (budget ${BUDGET:.2f})")
    if worst > BUDGET:
        print("Worst case is over the budget: nothing was sent.")
        return 2
    before = Ledger().totals("meta")
    if LIVE:
        os.environ["PHERI_META_CAP_USD"] = f"{before.committed_usd + BUDGET:.6f}"  # this process only
    llm = LLM()
    calls = []
    real = llm.complete

    def recorded(messages, **kw):
        try:
            r = real(messages, **kw)
        except Exception as exc:  # a failed answer still used (and was billed for) its tokens
            if getattr(exc, "result", None) is not None:
                calls.append(call_record(kw.get("purpose"), exc.result))
            raise
        calls.append(call_record(kw.get("purpose"), r))
        return r

    llm.complete = recorded
    rep = learn.write_report(results, llm)
    after = Ledger().totals("meta")
    print("\n" + rep.markdown)
    print(f"\nChecks: {len(rep.findings)} findings and {len(rep.caveats)} caveats kept, {len(rep.rejected)} rejected")
    for x in rep.rejected:
        print(f"  REJECTED {x['part']}: {x['text']!r}\n           {'; '.join(x['problems'])}")
    for c in calls:
        print(f"Call: {c['model']} output={c['output_tokens']} reasoning={c['reasoning_tokens']} "
              f"answer={c['answer_chars']} chars{' CUT OFF' if c['incomplete'] else ''}")
    print(f"Cost: this run ${after.settled_usd - before.settled_usd:.4f}; total Meta spend ${after.settled_usd:.4f}")
    if LIVE:
        saved = save_run("learn", {"results_file": str(path), "budget_usd": BUDGET, "worst_case_usd": worst,
                                   "report": {"headline": rep.headline, "findings": rep.findings,
                                              "caveats": rep.caveats, "rejected": rep.rejected,
                                              "markdown": rep.markdown},
                                   "calls": calls, "ledger": {"before": before.settled_usd,
                                                              "after": after.settled_usd}})
        print(f"Saved this run: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
