"""Evals at scale: closed weights against open weights, per language, with 95% intervals.

    python evals/scale.py                      # replays the recorded live run (or the stand-in where none): $0
    python evals/scale.py --live --meta-budget 4 --baseten-budget 4   # every message on both providers, recorded

The guard reads every message in evals/scale/messages.jsonl (about 600, labelled by code) and attacks.jsonl (100):
on Muse Spark 1.3 (Meta Model API) and on Muse Spark Open (open weights, Baseten). Then the judge (Muse Spark Open)
reads the 50 cases in judge.jsonl. Per language it reports: label accuracy, language accuracy, attacks stopped,
and harmless messages wrongly stopped, each with a Wilson 95% interval. Writes evals/scale/results.json.

Language codes: the guard answers in ISO 639-1, which has no code for Bhojpuri (bh, "Bihari", was withdrawn) and
none for a script, so Roman Nepali is right as "ne", and Bhojpuri is scored twice: never exactly right by
construction, and "Hindi family" (hi or bh) right. Both are printed.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCALE = HERE / "scale"
sys.path.insert(0, str(HERE.parent / "api"))
sys.path.insert(0, str(HERE))

PROVIDERS = {"meta": "Muse Spark 1.3 (closed, Meta Model API)", "baseten": "Muse Spark Open (open weights, Baseten)"}
LANGS = ("ne", "ne-Latn", "hi", "bho", "en")
EXPECTED_CODE = {"ne": "ne", "ne-Latn": "ne", "hi": "hi", "bho": None, "en": "en"}  # None: ISO 639-1 has none
FAMILY = {"ne": {"ne"}, "ne-Latn": {"ne"}, "hi": {"hi"}, "bho": {"hi", "bh"}, "en": {"en"}}
RECORDING = SCALE / "recorded.jsonl"
JUDGE_RECORDING = SCALE / "judge_recorded.jsonl"
WORKERS = 8


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (SCALE / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def _llm(mode: str, record: Path | None, replay: Path, **caps):
    from pheri.config import Settings
    from pheri.llm import LLM

    tmp = Path(tempfile.mkdtemp()) / "ledger.sqlite"
    if mode == "live":
        return LLM(Settings(llm_mode="live", record_path=str(record), **caps))
    return LLM(Settings(llm_mode="replay", replay_path=str(replay), record_path=None, database_url=None,
                        ledger_path=str(tmp)))


def read_all(rows: list[dict], provider: str, llm) -> list[dict]:
    """The guard on every row, WORKERS at a time. Each result keeps what was expected next to what came back."""
    from pheri.guard import guard, screen

    def one(r):
        g = guard(r["text"], business="birgunj", llm=llm, source_id=r["id"], channel="whatsapp",
                  private=provider == "baseten")
        return {"id": r["id"], "lang": r["lang"], "expected_label": r["label"], "kind": r.get("kind"),
                "label": g.label, "language": g.language, "attack": g.attack, "code_screen": bool(screen(r["text"])),
                "error": g.error, "cost_usd": g.cost_usd, "recorded": None}
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(one, rows))


def _ci(k: int, n: int) -> dict:
    from pheri.twin import wilson

    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci": wilson(k, n)}


def summarize(out: list[dict]) -> dict:
    """Per language and overall: label right (non-attacks), language right (exact and family), attacks stopped,
    harmless messages stopped (false alarms), and the code screen's share of the catches."""
    def block(rows):
        benign = [r for r in rows if r["expected_label"] != "attack"]
        attacks = [r for r in rows if r["expected_label"] == "attack"]
        exact = [r for r in rows if EXPECTED_CODE[r["lang"]] is not None]
        return {
            "label": _ci(sum(r["label"] == r["expected_label"] for r in benign), len(benign)),
            "language_exact": _ci(sum(r["language"] == EXPECTED_CODE[r["lang"]] for r in exact), len(exact)),
            "language_family": _ci(sum(r["language"] in FAMILY[r["lang"]] for r in rows), len(rows)),
            "attacks_stopped": _ci(sum(r["attack"] for r in attacks), len(attacks)),
            "attacks_code_alone": _ci(sum(r["code_screen"] for r in attacks), len(attacks)),
            "false_alarms": _ci(sum(r["attack"] for r in benign), len(benign)),
            "unreadable": sum(r["error"] is not None for r in rows),
        }
    res = {"all": block(out)}
    for lang in LANGS:
        res[lang] = block([r for r in out if r["lang"] == lang])
    res["cost_usd"] = round(sum(r["cost_usd"] for r in out), 4)
    return res


def judge(cases: list[dict], judge_llm) -> dict:
    from run import verify_drafts

    offline = _llm("replay", None, SCALE / "none.jsonl")
    rows = verify_drafts(offline, judge_llm, cases=cases)["rows"]
    planted = [r for r in rows if r["expect"] == ["judge"]]
    supported = [r for r in rows if not r["expect"]]
    return {"planted_caught": _ci(sum(r["ok"] for r in planted), len(planted)),
            "supported_passed": _ci(sum(r["ok"] for r in supported), len(supported)),
            "judge_recorded": all(r["judge_recorded"] for r in rows if r["judge_ran"]),
            "cost_usd": round(sum(r["judge_cost_usd"] or 0 for r in rows), 4),
            "missed": [r["id"] for r in planted if not r["ok"]],
            "false_alarms": [{"id": r["id"], "unsupported": r["unsupported"]} for r in supported if not r["ok"]]}


def fmt(c: dict) -> str:
    if not c["n"]:
        return "n/a"
    lo, hi = c["ci"]
    return f"{100 * c['rate']:5.1f}% [{100 * lo:.0f}-{100 * hi:.0f}] ({c['k']}/{c['n']})"


def table(results: dict) -> str:
    lines = []
    for p, name in PROVIDERS.items():
        s = results["guard"][p]
        lines += [f"== {name}: ${s['cost_usd']:.2f}",
                  f"  {'language':9} {'label right':24} {'language (family)':24} {'attacks stopped':24} {'false alarms':22}"]
        for lang in (*LANGS, "all"):
            b = s[lang]
            lines.append(f"  {lang:9} {fmt(b['label']):24} {fmt(b['language_family']):24} "
                         f"{fmt(b['attacks_stopped']):24} {fmt(b['false_alarms']):22}")
    j = results["judge"]
    lines += [f"== judge (Muse Spark Open): planted claims caught {fmt(j['planted_caught'])}, "
              f"supported drafts passed {fmt(j['supported_passed'])}, ${j['cost_usd']:.2f}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--meta-budget", type=float, default=None)
    ap.add_argument("--baseten-budget", type=float, default=None)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rows = load("messages.jsonl") + load("attacks.jsonl")
    cases = load("judge.jsonl")
    caps = {}
    if args.live:
        if args.meta_budget is None or args.baseten_budget is None:
            print("--live needs --meta-budget and --baseten-budget (USD).")
            return 2
        from pheri.ledger import Ledger

        led = Ledger()
        caps = {"meta_cap_usd": led.totals("meta").committed_usd + args.meta_budget,
                "baseten_cap_usd": led.totals("baseten").committed_usd + args.baseten_budget}
        os.environ["PHERI_LLM_MODE"] = "live"
    mode = "live" if args.live else "replay"
    llm = _llm(mode, RECORDING, RECORDING, **caps)
    results = {"messages": len(rows), "judge_cases": len(cases), "guard": {}, "rows": {}}
    for p in PROVIDERS:
        out = read_all(rows, p, llm)
        results["guard"][p] = summarize(out)
        results["rows"][p] = out
    results["judge"] = judge(cases, _llm(mode, JUDGE_RECORDING, JUDGE_RECORDING, **caps))
    if args.live:
        (SCALE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
