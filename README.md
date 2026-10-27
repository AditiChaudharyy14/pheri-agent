# Pheri

The next step for every customer, inside your rules. Pheri is an AI agent that understands each
customer, decides their next best action ("why this, why now"), acts only inside the business's
rules and approvals, and proves what worked with a holdout.

## Run the tests

Python 3.12+.

```bash
pip install pydantic openai "psycopg[binary]" pytest
cd api
python -m pytest
```

Tests run in mock mode: no network and no model spend. The real-Postgres row-level-security tests
in `api/tests/test_schema.py` run only when `PHERI_TEST_DATABASE_URL` is set in `.env` (a throwaway
Neon branch). Without it they are skipped and say so.

## Smoke test

```bash
python scripts/smoke.py           # mock mode, no network
python scripts/smoke.py --live    # one real call per provider, under $0.01 in total
```

## How Pheri decides

Code decides, models explain. For each customer:

1. **Profile** (`pheri/profile.py`): facts counted in code; needs, blockers and mood read by Muse Spark,
   with every quote checked against its source.
2. **Journey** (`pheri/journey.py`): a stage chosen in code from the facts, with the rows that decided it.
3. **Decide** (`pheri/decide.py`): Muse Spark picks the next best action through three tools
   (`get_profile`, `list_allowed_actions`, `check_rules`) and explains "why this, why now".
   Code drops any evidence that is not in the profile.
4. **Rules** (`pheri/rules.py`): the owner writes a rule in plain words, Muse Spark compiles it into
   typed checks, the owner confirms code's own description of them, and pure code enforces them
   on every action.
5. **Autonomy** (`pheri/autonomy.py`): per action type, suggest / ask the owner / act alone.
   Approving re-runs the rules. Every step goes to the append-only audit log.

```bash
cd api
python -m pheri.journey            # stage accuracy against the hidden truth in data/synth/*/_truth.json
python -m pheri.decide brightdesk  # five mock decisions, no network
```

## Every reply is read safely first

`pheri/guard.py` reads each inbound customer reply before anything else happens:

1. A **code screen** looks for injection patterns (rule overrides, "system override", "reveal all
   customer emails", "refund everything", false owner authority, prompt markup, encoded payloads) in
   English, Spanish, Portuguese, Hindi and Nepali.
2. The **model** labels the reply (question, complaint, objection, stop, purchase intent, attack,
   other) and gives its language and a short safe summary. The customer's text goes in as escaped
   JSON inside a delimited block, as data, never as instructions.
3. **Code checks the answer**: an attack seen by either side is an attack, an unsafe summary is
   rewritten, and an unreadable reply goes to a person.

An attack never produces an action: it becomes one "escalate to human" item in the approval queue,
and Pheri holds off that customer until the owner closes it. "Stop" sets a do-not-contact flag;
from then on there is no model call for that customer, and the rule check refuses anything that
would reach them.

**Private mode** is a per-business switch (`pheri/privacy.py`), step by step: reading replies,
profiles, decisions and rule compiling can each run on Muse Spark Open: Meta's open-weight model,
served by a partner (Baseten), self-hostable. In **full** private mode the business sends nothing
to the Meta Model API: its work runs inside a code fence that refuses any Meta call before it is
sent. A private decision is a single call: code dry-runs the owner's rules on every allowed action
first, and checks the answer exactly as it does on the Meta Model API. On Baseten every step runs at
`reasoning_effort: low` (top-level, as Baseten documents for Muse Spark Open, whose default is
`xhigh`). The model always reasons, and `max_tokens` covers reasoning and answer together.

```bash
python evals/run.py                                    # mock: both providers, every message, $0
python evals/run.py --live --sample 20 --budget 0.50   # real calls, budget per provider, refused if the worst case is over
```

## Proving what worked

`pheri/twin.py` is a customer twin: synthetic customers whose responses are maths, not a model. Each
has a hidden true stage. Pheri sees it only through its journey rules' measured mistakes, and the
chance of a response depends on the hidden stage and the action taken. 20% are held out and get
nothing. Thompson sampling learns, round by round, which action works for each stage, inside the
owner's rules. The results show the lift against the holdout for each stage, with a 95% interval
and a verdict decided in code. `pheri/learn.py` has Muse Wonder write "What Pheri learned" from
those results. The model can only cite facts by id, and code checks every number and verdict
before a sentence is kept.

```bash
cd api
python -m pheri.twin brightdesk            # 200 customers, $0; writes chart-ready JSON to .pheri/twin/
python -m pheri.learn ../.pheri/twin/brightdesk-n200-seed7.json   # mock report, checked in code
```

`evals/attacks.jsonl` holds 52 attacks (direct, indirect, multilingual, semantic) and 27 harmless
messages that look alarming. `evals/replies.jsonl` holds 60 labelled replies, 12 per language. The
code screen's patterns were written alongside these sets, so its own catch rate here is an upper
bound; the semantic attacks are the ones it is not meant to catch.

Keys go in `.env` (see `.env.example`), never in the repo. Every model call passes through
`api/pheri/llm.py`, which enforces the spend caps and allows only synthetic data.

## Built during the hackathon

Everything in this repository was written during the Meta Global AI Developer Hackathon,
27 Oct – 4 Nov 2026. All code is new; nothing was carried over from earlier projects.
All demo data is synthetic, generated by `api/pheri/synth.py`.

Cookbook patterns we adapt are credited here as we use them:

- None so far.
