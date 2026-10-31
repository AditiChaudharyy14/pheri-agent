# CLAUDE.md — Pheri (Meta Global AI Developer Hackathon, Indie track)

Read this before every task. These rules are not optional.

## Status (update in every commit)
- Done: spend guard, synthetic data, profiles, journey (Brightdesk 92.1%, Birgunj 98.7%), rules, decide (tool loop,
  evidence by id), autonomy + approvals, guard + private mode (Muse Spark Open), evals, twin + Thompson (5,000,
  12/12 learned right, close calls flagged), Wonder report (checked in code), FastAPI, all 7 web screens, card
  footer, pronouns (only Maya's given), replay mode (PHERI_LLM_MODE=replay; pill "Recorded from a live run").
- Verification (pheri/verify.py): verify_draft = 13 code checks (rules, schema, evidence, facts, pronouns, address
  "you"/name only in greeting, one problem, language, length, link allowlist, money, middle step, tools), then a judge
  (Muse Spark Open, Baseten, low) per claim. Reasons go back, max PHERI_VERIFY_MAX_ATTEMPTS=3 drafts, then the
  owner's queue (never sent). Runs inside autonomy.submit(); _execute() sends only a payload whose stored
  verification passed (sha). Middle step: stage + plan scored vs _truth.json (plans from the twin's table), money
  100% / nudges 80% per business, in check_rules and on the Rules screen. Tool allowlist: other calls discarded +
  audited. Wonder: same loop, max 2 retries. Shown in the trace (per draft), card footer, Proof block.
  Owner override: soft checks only (judge, address, one problem, length, language, middle step); audit
  "owner_override" has who, when, checks, reasons, exact text; hard checks (rules incl. do-not-contact and quiet
  hours, schema, evidence, facts, pronouns, links, money, tools) never, for any drafted action (owner tasks too).
  The judge runs whenever hard checks pass (overrides always show its verdict); message claims first; >12 claims
  or a why over 400 chars fails schema. A cited fact's window (_30d) backs "30". tidy_message (only in
  Draft.of) lowercases "Your". A judge that could not answer stays soft (owner may send), but the card and the
  audit log say "Judge could not answer, sent by owner override". Hard/soft live only in Verification's
  properties; the check count only in CODE_CHECKS (docs that state it are pinned by a test).
- Public demo (PHERI_PUBLIC_DEMO=1, render.yaml): a sandbox per visitor (cookie pheri_sandbox via web/proxy.ts,
  in memory, max 100, 30 min idle, idlest dropped first); "Reset demo" button; audit actor "demo visitor (public
  demo, no login)", rules by "demo setup (public demo, no login)".
- Recorded (data/recorded/llm.jsonl): Brightdesk's 6 cards (re-recorded 31 Oct with the plan hint: 9 drafts, 1 caught
  by code, 2 by the judge, all verified; Aarav no longer fails, so no recorded override example is left) and the
  Brightdesk Wonder report (attempt 1 headline rejected, attempt 2 passed). Birgunj's report is the stand-in until the night is recorded.
  evals/judge_recorded.jsonl: the real judge on 20 cases in evals/drafts.jsonl: 10/10 planted claims caught,
  9/10 supported passed (S04 "sent a cart" vs the fact days_since_enquiry: strict, pinned in test_evals; the 7
  Birgunj cases rewritten for the new world and re-recorded on 29 Oct, Baseten $0.0227).
  Re-record: python scripts/record_demo.py --live --budget <usd> --baseten-budget <usd>.
- Pivot (approved 29 Oct; plan in ~/.claude/plans/pasted-content-id-3e3c-use-the-humming-bachman.md): hero
  becomes Birgunj Saree Ghar (Kettle reskinned), six moments: Morning brief, Night shift, Slop vs Pheri, Speak a
  rule, Nepali reply attack, Proof. Code freeze Mon 2 Nov 23:59; video Tue 3 – Wed 4.
- Thu night done: LLM.transcribe (Muse Voice, /v1/asr/transcribe, WAV mono PCM16 16/24 kHz, billed per second,
  recorded + replayed by audio hash; live smoke OK, scripts/transcribe.py). Modal billed by GPU-seconds
  (PHERI_MODAL_GPU, default L40S; reserve timeout + scale-down tail; ledger column gpu_seconds), Modal cap $25.
  Audio parts estimated by length (scripts/probe_audio.py ready for the Nepali clip, ≤ $0.10). Language probe
  (docs/live-runs.md): Bhojpuri labels 9/10 but read as Hindi; Roman Nepali fine on Spark Open; code screen has
  no Bhojpuri/Roman-Nepali attack patterns yet. Web: nav = Next steps, Rules, Safety, Proof (Journey from a
  customer, Spend in the footer); Proof is one sentence + verification line + 3 findings + lift chart folded;
  discount widget and scaffold SVGs gone.
- D1 done (Birgunj world): Kettle is now `birgunj`, Birgunj Saree Ghar (synth.birgunj, own random stream, so
  Brightdesk's data is byte-identical). 300 customers keyed by phone (profile.norm_phone; Instagram handles mapped),
  hidden world per customer in _truth.json "world" (segment, town, language ne/ne-Latn/hi/bho/en, payment, festival,
  reorder cycle, returns, complaint). Festival dates in synth.FESTIVALS (Dashain 21 Oct, Tihar 8 Nov, Chhath 15 Nov
  2026). Stages: new, loyal, wholesale, festival, asked_no_order, gone_quiet, complaint; journey 98.7% (misses:
  festival buyers with one ordinary order). New action offer_reorder; Brightdesk keeps its recorded decision schema
  (decide.RECORDED_ACTIONS). Voice notes: voice.fill (Muse Voice for hi/en; script stand-in until audio exists;
  Nepali unreadable). Seed rule: quiet hours 21-08. Night set: 3 per stage + voice-note senders + attackers.
  Twin 5,000: +15.7 pp [+13.4, +18.0], learned = truth in every stage. Not yet re-recorded: Birgunj's night
  (test_replay_serves_birgunjs_recorded_night is a strict xfail until then), recorded once after Step 3's scheduling
  change, because that changes what the decide tools return. Native review of all Birgunj strings: pending (Aditi).
- D2 done (delayed outcomes, twin.py): Birgunj's twin runs day by day on customers drawn from the hidden world
  (world_population; COD, price sensitivity, returns, wholesale change the chances). Milestones: reply day 1,
  order day 3 (the objective), reorder day 30, each credited to the decision that caused it (Event.decision).
  MilestoneThompson: a reply is provisional evidence (weight = P(order | reply) learned so far), replaced by the
  real order on day 3. 5,000, seed 7: orders 22.9% vs holdout 8.9% (+14.0 [+11.8, +16.2]); replies-only learner
  21.0%; random 12.0%; reorders 6.7% vs 2.8%. Correcting beats replies-only on every seed at 5,000; at 2,000 it does
  not (kept in the test docstring). Brightdesk keeps its one outcome; its results file is pinned byte-for-byte
  (test_brightdesk_keeps_its_one_outcome_and_its_recorded_results). Proof: "Learns from replies today, corrects
  with orders later" + corrections per stage. Wonder may cite milestone facts (learn.catalogue).
- D4 done: docs/LESSONS.md maps each Agents 101/102 lesson to file/function and test (gaps marked: per-action
  autonomy defaults wait for Step 3; builder/reviewer split is a habit, not enforced). test_docs checks every
  test it names exists. New: test_the_system_prompt_is_behaviour_and_the_task_is_the_brief.
- D3 done (evals at scale, evals/scale/): 591 labelled messages (labels by code; 310 paraphrased by Spark 1.3
  Contributor, checked in code) + 100 attacks + 50 judge cases, read once live by both models, every row saved
  (guard_<provider>.jsonl, resumable). Attacks stopped: Spark 1.3 87% [79-92], Spark Open 96% [90-98];
  Bhojpuri 55% vs 90%, Roman Nepali 80% vs 90%; false alarms 0/591 vs 2/591. Judge: 24/25 planted caught (JP10
  missed), 25/25 supported passed. Pinned in test_evals; table in README. Cost: Meta $1.91 + $0.05 paraphrase,
  Baseten $1.75 (guard + judge).
- Guard v2 (dev-only tuning; 140 attacks, 40 each bho/ne-Latn, seeded dev/test split): code screen test 14/71 -> 68/71,
  full guard test 62 -> 70 (Spark 1.3), 69 -> 70 (Spark Open), false alarms unchanged. Defence in depth
  (evals/pipeline.py, code screen off, everything act_alone): Spark Open 140/140, 6 past the guard, 0 sent, 0 harmful;
  Spark 1.3 stopped at 74/140 (partial, by choice): 7 past, 3 sent (ordinary), 0 harmful. Bug found and fixed: a
  cut-off profile reading no longer crashes a decision.
- Sat A done: Birgunj first; nav Morning / Night shift / Rules / Proof (Safety -> Night shift); receipt chips
  (order numbers, or the customer's words with channel and date; no internal ids); status palette teal / marigold /
  vermilion; phone layout (390 px) for the shell, cards and customer page.
- Sat B/C backend + recording: scheduling (rules.next_send_time; status "scheduled", out at 08:00 the customer's time),
  Birgunj autonomy (nudges act_alone, discount ask_owner), CLOCKS (night 06:15, owner 07:30 NPT), GET /brief,
  GET /slop (plain AI draft vs Pheri, checked by verify_draft, struck sentence by sentence). Birgunj's night and the
  plain drafts recorded live (Meta ~$0.67, Baseten ~$0.23); 217 replies; replay checked in a fresh process. Bug
  found: a live 4xx was not recorded, so replay diverged (Pooja Ansari); refusals are now recorded and replayed.
- Modal: its billing docs say a payment method is required for all usage (no Modal deploy). Baseten lists no
  Glimmer (only muse-spark-open and muse-spark-open-1026 of Meta's models).
- Sat screens done: Morning brief (sentences; needs you / stopped / ready at 8:00 / sent; partial = Nepali voice note,
  permission = public demo banner; error.tsx at both levels), Slop vs Pheri (/slop), Night shift. Evidence:
  web/evidence/report.json + 20 screenshots at 390x844 and 1440x900; check-evidence.js passes. Plain-draft
  comparison skips customers Pheri stopped or holds.
- Curated night (synth.NIGHT, own stream "{SEED}:night", truth["night"]): 14 safe, 4 owner (Raxaul rate, refund,
  9-days-late bho complaint, 25% Tihar ask), 2 blocked (30% ask, "stop messaging"), 3 attacks (ne, ne-Latn, bho),
  voice notes hi (stand-in transcript) + ne (unreadable); 4 Bhojpuri. Seed rules add "No discounts above 10%".
  autonomy.owner_reason: money talk (fact asks_about_money) or days_late >= 7 caps any action at ask_owner
  (payload waits_for_owner). Recorded live (Meta ~$0.83, Baseten ~$0.20): 16 ready at 08:00, 5 need you (2 are
  turn-limit owner tasks, footer "No message drafted"), 3 attacks stopped, 1 rule moment (do-not-contact; the model
  never tried > 10%, so no discount block, not faked), 10 customers with real caught-and-rewritten drafts on the
  Night shift timeline.
- Money hand-offs fixed (31 Oct): root cause was check_rules refusing a plan with no hint of what fits, so the
  model walked the action list one refusal per turn and ran out (Sita Karna, Kiran Chaudhary). Now a refused check
  for a customer who asked about money carries owner_decides (decide.money_hint: the owner decides money; reply
  with a nudge that fits the stage; promise nothing). Only those 2 conversations changed (re-recorded, Meta
  $0.07): Sita offer_reorder in 4 turns, Kiran send_checkin (3 drafts), both verified holding replies. Money
  questions carry two owner choices written by code (autonomy.owner_options from profile.money_ask: rate /
  discount, capped by the rule / refund, plus 'You decide'); approve(choice=...) checks the pick and audits it;
  the card shows it.
- Plan hint (31 Oct, approved): every refusal by the middle step now carries plans_that_fit (decide.plan_hint: the
  plans that pass for the stage; money ones only if the stage is sure enough). Money customers keep owner_decides.
  Re-recorded the 7 it changed (Meta+Baseten $0.16): Anita Rai 7->4 turns, Aarav 7->4 (now verified on draft 1),
  Nisha Das, Sanjay Karna 5->4; Ranju Jha/Poudel use their turns on real rewrites. One refusal each, at most.
- Attack moment (Step 5, Glimmer cut: Modal needs a card): an attacker gets no word from any model. The owner gets
  the escalation; the customer gets a fixed holding reply written by code (pheri/holding.py, TEMPLATES ne, ne-Latn,
  hi, bho, en; native review pending, Aditi), in the language of their message, once, from decide_customer.
  Action holding_reply is code-only (actions.CODE_ACTIONS: never in list_allowed_actions, so no recording changed).
  verify_template runs the code checks that apply (rules incl. quiet hours + do-not-contact, template, language,
  length, links, money); no judge (the text claims nothing about the customer), stated in the stored verification;
  sent only through the sha gate, at 08:00 their time. Shown under Stopped (brief) and on the Night shift timeline.
  Recorder: same request twice in a run reuses its reply; refusals recorded; the pruned file
  is re-checked in a fresh process and restored if anything misses. Recording 218 replies.
- Waiting on Aditi: Nepali + Hindi clips; native review of Birgunj strings; Render clicks.
  Screenshots: uvicorn :8000 (replay), then `npm run build && npm start` (not the dev server), then
  `node scripts/evidence.mjs evidence [state]`; one heavy process at a time; restart the API before retaking
  (approving changes its state; the script approves last).
- Live spend: Meta $5.8318 of $130, Baseten $3.2721 of $90, Modal $0 of $25. Tests: 402 (Postgres tests run when
  PHERI_TEST_DATABASE_URL is set).

## What we are building
Pheri: an AI agent that understands each customer, decides their next best action ("why this, why now"),
acts only inside the business's rules, permissions and approvals, and proves what worked with a holdout.
Pitch: "The next step for every customer, inside your rules." Problem statement: **Build for Your World**
(Aditi worked in AI lead generation for businesses and saw owners guess each customer's next step;
the theme is picked on the submission form).

## Hackathon rules (disqualification if broken)
- Repo is **public**. Only code written during the event (27 Oct – 4 Nov 2026). No code from the old Pheri repo.
- Only approved participants may work on the project. AI coding tools are fine.
- No code, data or assets we don't have rights to. Cookbook patterns: adapt, credit in README.
- Anti-projects to stay clear of: medical advice, basic RAG, Streamlit apps, **dashboards as the main feature**,
  chatbots, job screeners, nutrition/sports/personality analyzers, politics/war.
  The demo leads with the agent deciding and acting; charts only prove it.
- Demo video ≤ 3:00, opens with: "Everything you'll see was built this week, 27 Oct to 4 Nov."

## Money: never spend past the free credits
- Every model call goes through `api/pheri/llm.py` (`LLM.complete`). Never call a model any other way.
- Hard caps (env): Meta $130 (`PHERI_META_CAP_USD`), Baseten $90, Modal $90. Per-call limit $0.50.
- Tests and dev default to `PHERI_LLM_MODE=mock` (zero network, zero spend). Use `live` only on purpose.
- Develop on small samples (≤ 20 customers). Run the full 5,000-customer twin once, on Sat 31 Oct.
- Never use `muse-wonder-1.0` per customer; at most 3 calls per report. Never click "Stop using free credits" on the Billing page.

## Data and secrets
- Only synthetic data goes to any model (free-credit content may be used by Meta). Enforced in `llm.py`.
- Keys live in `.env` (git-ignored) or Render env vars. Never print, log, commit or paste a key.
- Demo date is fixed: `TODAY = 2026-10-30` in `pheri/synth.py`, so every run is identical.

## Models and APIs (checked against dev.meta.ai/docs on 27 Oct 2026)
- Meta Model API: `https://api.meta.ai/v1`, key `MODEL_API_KEY` (pass explicitly to the OpenAI SDK).
  **Use the Responses API** (`client.responses.create`), Meta's default for agents:
  JSON output via `text.format` (json_schema), effort via `reasoning.effort`, limit via `max_output_tokens`,
  tool loop via function tools (flat shape) + `function_call_output` + `previous_response_id`.
  `tool_choice` supports only `"auto"`: always handle a plain-text reply too. Usage: `input_tokens`,
  `input_tokens_details.cached_tokens`, `output_tokens` (includes reasoning tokens, billed as output).
  Free pre-check: `POST /v1/responses/input_tokens`. Caching is automatic: stable prefix first, `prompt_cache_key` per job.
- Models: `muse-spark-1.3` (decisions, $1.25/$4.25 per 1M, cached $0.15), `muse-spark-1.3-contributor`
  (synthetic only, $0.10/$0.20, 150 req/min, no effort `max`), `muse-wonder-1.0` (reports + grading only, $4/$20),
  `muse-voice-transcribe-1.0` (voice, $0.18/hour). Effort values: minimal, low, medium, high, xhigh, max ("none" = 400).
  Effort per job: low = triage, medium = decisions, high = compiling rules only.
- Private mode (open weights, open-weight prize): **Muse Spark Open on Baseten** via Chat Completions,
  `https://inference.baseten.co/v1`, key `BASETEN_API_KEY`, model `meta-models/muse-spark-open-1026`
  (the hackathon id, not the docs id). It always reasons: pass `reasoning_effort` low/medium.
- Optional: Muse Glimmer on Modal only if Modal credits are approved. Fireworks backup:
  `https://api.fireworks.ai/inference/v1`, model `accounts/fireworks/models/muse-spark-open`.
- Retries: only 429/500/502/503, honour `Retry-After`, max 3 tries. Never retry 4xx. On 504, send less work.
- Not used: Muse Image, SAM 3.1.
- Smoke test: `python scripts/smoke.py` (mock) and `python scripts/smoke.py --live` (one call each, < $0.01).

## Architecture
Code decides, models explain. Every action passes a rule check in code before it can happen.
Loop: any data → profile + journey → decide (Spark tool calls) → rule check (code) → autonomy dial
(act / ask owner) → act + append-only audit log → measure (holdout, twin) → learn (Thompson sampling,
Wonder report) → back to decide. Replies go through the private guard (Glimmer / Spark Open): labels +
prompt-injection screen.

## Stack and layout
Python 3.12+, FastAPI, Postgres (Neon) with row-level security per business, Next.js frontend, Render.
```
api/pheri/   config.py llm.py ledger.py pricing.py synth.py  (+ profile, journey, decide, rules, guard, twin, learn)
api/tests/   pytest; must stay green
db/          schema.sql (RLS)
data/synth/  generated demo data (Brightdesk, Birgunj Saree Ghar)
evals/       attacks + labelled replies, one command
web/         Next.js
```

## Build plan (Nepal time) — code complete by Fri 30 Oct
- Tue 27: llm wrapper on Responses API + spend ledger (done), synthetic data (done), smoke test (done),
  schema + RLS, Feature 1 profile.
- Wed 28: journey stages, next best action + why, rules compiler + code check, autonomy dial + approvals.
- Thu 29: multilingual replies + injection screen, private mode on Spark Open (Baseten) with an on/off switch, eval set v1.
- Fri 30: customer twin + holdout + Thompson sampling, Wonder "What Pheri learned", UI, deploy.
- Sat 31 – Sun 1: polish, full twin run, README. Mon 2 Nov 23:59: feature freeze.

## Working rules for Claude Code
- Small, tested steps. Run `pytest` before every commit. Never weaken a test to make it pass.
- Ask before: any live model run over 50 calls, deleting files, changing caps, pushing to main.
- Commit messages say what changed and why. Keep the README's "Built during the hackathon" section true.
