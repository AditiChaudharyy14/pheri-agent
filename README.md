# Pheri

The next step for every customer, inside your rules. Pheri is an AI agent that understands each
customer, decides their next best action ("why this, why now"), acts only inside the business's
rules and approvals, and proves what worked with a holdout.

## Run the tests

Python 3.12+.

```bash
cd api
pip install -r requirements-dev.txt
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

## The API

```bash
cd api
uvicorn pheri.app:app --reload     # mock mode: no network, no spend; docs at http://127.0.0.1:8000/docs
```

`pheri/app.py` (FastAPI) serves, per business: customers with their journey stage, a customer's
profile and next best action, the approval queue (approve re-runs the rules, reject keeps a note),
the owner's rules (add, confirm, list), the "offer a discount" check, the private-mode switch, the
twin's results, the "What Pheri learned" report, the audit log, and `/spend` against the caps. Every
route calls code that is already tested. It refuses live mode unless `PHERI_API_ALLOW_LIVE=1`, and it
never calls Muse Wonder from a request.

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

## How Pheri checks its own work

A model's draft is a claim, not an action. `pheri/verify.py` checks every draft before anything can be
sent; the idea follows Meta's Verifiable Agents workshop (28 Oct): verify the work in code, show the
verification, and never let the agent mark its own homework.

1. **Code first, 13 checks, free.** The owner's rules; the schema; evidence that exists in the profile;
   every number, date, amount and plan name present in the facts the draft cites; no pronoun the customer
   never gave; the message says "you", with their name only in the greeting (the why-text, for the owner,
   names them); one problem, the one behind their journey stage; the customer's language; length; links
   only to the business's own sites; no money offer unless it is an `offer_discount` the rules allow; no
   tool call Pheri does not have; and the **middle step** (below). Before checking, code makes one edit:
   the common word after the greeting's comma goes lowercase ("Hi Maya, Your..." becomes "Hi Maya, your...").
2. **Then a judge**, whenever every hard check passed (a soft failure does not stop it, so an owner who
   overrides one always sees its verdict): Muse Spark Open on Baseten, effort low, answers true or false
   per claim: "is this claim supported by the cited fact ids?" It sees only the facts and quotes the
   draft cites, and the message's claims first. A draft with more claims than it reads (12), or a why
   longer than 400 characters, fails the schema check, so the judge never reads part of one.
3. **Failures go back.** The reasons return to the model as the next turn of the same conversation, up
   to `PHERI_VERIFY_MAX_ATTEMPTS` drafts (3). After that the draft goes to the owner's queue with the
   reasons, and Pheri never sends it on its own.
   - **Soft checks** (the judge, tone and address, one problem, length, language, the middle step's bar):
     the owner may read the draft and press **Send anyway**. That is an owner override: the audit log
     records who, when, which checks were overridden, the reasons, and the exact text sent, and the trace
     shows "Sent by owner override: judge flagged 2 claims". The summary always says what the judge
     found ("address; judge supported all 4 claims"), and there is no override without a verdict.
   - **Hard checks** can never be overridden, by anyone: the owner's rules (which hold do-not-contact
     and quiet hours, and are checked again at approval), the schema, evidence, invented numbers, dates
     and plans, guessed pronouns, links, money offers, unknown tools. The queue says which one failed
     and why, and offers only Reject. That holds for every action Pheri drafts, an owner task included.
4. **The model cannot skip it or call it.** It is not a tool. `autonomy.submit()` runs `verify_draft()`
   itself and stores the result, with a hash of the exact payload, on the action; the send step
   (`_execute`) refuses any customer-facing action whose stored verification did not pass for that
   payload, unless an owner overrode every check it failed, all soft, for that same payload.
   `api/tests/test_verify.py` sends everything it can (every action on "act alone", every queued item
   approved, with an override wherever one is allowed) and proves each message that went out either passed
   or was overridden on the record for its exact text, and that nothing with a hard failure went out.
5. **Only three tools.** Any other tool call (`issue_refund`, `verify_draft`, `send_message`) is
   discarded, never run, and written to the audit log as `tool_call_discarded`; the draft then fails the
   hard `tools` check.

**The middle step** is checked before the message is written. Code scores its own journey stage and each
plan against the labelled truth set (`data/synth/*/_truth.json`: true stages, and per stage the plans that
fit, from the twin's hidden table): of the customers code puts in a stage, how many truly are there, and
how many the plan truly fits. Money actions (discount, upgrade, subscription) need 100%, nudges 80%, set
per business. `check_rules` returns that verdict in the loop, so the model hears "send_checkin fits 0% of
onboarding customers" and picks another plan. The Rules screen shows the scores.

**Muse Wonder's report** goes through the same loop: a rejected part goes back with the reason, at most two
more calls on that one report. The recorded run: attempt 1's headline stated no result, attempt 2 passed.

What you see: the Decision trace shows every draft, which layer caught it and why, and the reasons sent
back; each card's footer reads "Verified: 13 code checks + judge"; Proof has the totals. In the recorded
live run of the 12 showcase decisions: 22 drafts, 2 caught by code, 9 by the judge, 10 retries, 11
verified, 1 sent to the owner (Aarav: the judge rejected unsupported claims in all three drafts; a soft
check, so his card offers Send anyway).

**How good is the judge?** `evals/drafts.jsonl` has 20 cases for it, each passing every code check: 10
drafts that say only what they cite, and 10 with one planted claim no fact backs (an invented reason,
competitor, threat, preference, growth story, or a contradiction of a cited fact, all in words, so code
cannot see them). Muse Spark Open, recorded once for $0.11 (`evals/judge_recorded.jsonl`, with the 8 broken drafts it now also reads):
it caught 10 of 10 planted claims and passed 9 of 10 supported drafts. Its one false alarm is strict rather
than wrong: "the items in your cart are still saved" says a little more than the cited facts.

```bash
python evals/run.py     # includes the verification numbers: labelled broken drafts, tool attacks, middle step,
                        # and the loop on the recorded showcase; all $0
```

## Every reply is read safely first

`pheri/guard.py` reads each inbound customer reply before anything else happens:

1. A **code screen** looks for injection patterns (rule overrides, "system override", "reveal all
   customer emails", "refund everything", false owner authority, prompt markup, encoded payloads, a tool
   called by name) in
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

`evals/attacks.jsonl` holds 55 attacks (direct, indirect, multilingual, semantic, and 3 that try to make
Pheri call a tool it does not have) and 27 harmless messages that look alarming. `evals/replies.jsonl`
holds 60 labelled replies, 12 per language. `evals/drafts.jsonl` holds 37 labelled drafts: 17 broken on
purpose, one way each, for code to catch, and 20 for the judge (10 supported, 10 not). The
code screen's patterns were written alongside these sets, so its own catch rate here is an upper
bound; the semantic attacks are the ones it is not meant to catch.

Keys go in `.env` (see `.env.example`), never in the repo. Every model call passes through
`api/pheri/llm.py`, which enforces the spend caps and allows only synthetic data.

## The web app, and the public demo

```bash
cd api && uvicorn pheri.app:app                      # API on :8000 (mock mode by default)
cd web && npm ci && npm run dev                      # web app on :3000
```

The public demo runs the API with `PHERI_LLM_MODE=replay`. A live run records each model reply in
`data/recorded/llm.jsonl` (`python scripts/record_demo.py --live`: it drives the API in-process, then
replays the same requests and checks every one is found). Replay plays those replies back with no
network, no model key and no spend, while code still runs every rule check, evidence check and the
autonomy dial. A reply is found by the conversation it answered, so if a prompt or the data changes,
that conversation falls back to the offline stand-in, and the page says so: every decision card
names who decided and how it was checked ("Decided by Muse Spark 1.3 · $0.0157 · 3 turns · Verified:
13 code checks + judge", or "the offline stand-in"), and the header reads "Recorded from a live run".
The judge's verdicts are recorded too. `api/tests/test_app.py` fails if the recording stops matching the
code.

**Each visitor has their own sandbox.** With `PHERI_PUBLIC_DEMO=1` (set in `render.yaml`) the API gives every
visitor a copy of the demo state in memory, keyed by a cookie the web app sets (`web/proxy.ts`): at most 100,
each dropped after 30 minutes idle, the idlest dropped first when full. What one visitor approves, rejects or
writes reaches no one else, and **Reset demo** in the header puts theirs back to the start. There is no login,
so the audit log never names an owner: every approval is "by: demo visitor (public demo, no login)", and the
starting rules are confirmed by "demo setup (public demo, no login)".

Deploy: `render.yaml` is a Render blueprint with two services. `pheri-api` (Python, replay mode, no
keys) and `pheri-web` (Node). Set `PHERI_API_URL` on `pheri-web` to the API's public URL. The browser's
`/api/...` calls go through `web/app/api/[...path]/route.ts`, which reads that URL at run time, so
changing it needs a restart, not a rebuild. All state is in memory and resets when the API restarts.

`data/spend/live.json` is what this week's live runs cost, totals only, from the local ledger
(`python scripts/spend_snapshot.py`); the Spend page shows it.

## Built during the hackathon

Everything in this repository was written during the Meta Global AI Developer Hackathon,
27 Oct – 4 Nov 2026. All code is new; nothing was carried over from earlier projects.
All demo data is synthetic, generated by `api/pheri/synth.py`.

Cookbook patterns we adapt are credited here as we use them:

- None so far.
