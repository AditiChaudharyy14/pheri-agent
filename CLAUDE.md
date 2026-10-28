# CLAUDE.md — Pheri (Meta Global AI Developer Hackathon, Indie track)

Read this before every task. These rules are not optional.

## Status (update in every commit)
- Done: spend guard, synthetic data, profiles, journey (Brightdesk 92.1%, Kettle 100%), rules, decide (tool loop,
  evidence by id), autonomy + approvals, guard + private mode (Muse Spark Open), evals, twin + Thompson (5,000,
  12/12 learned right, close calls flagged), Wonder report (checked in code), FastAPI (mock), web scaffold + Next steps.
- Doing: web app screens, one commit each, Playwright screenshots checked by eye. Next steps, Journey done.
- Next: Customer, Decision trace (each turn + rule checks), Rules, Safety, Proof, Spend;
  then polish, README, deploy, demo video. Servers for screenshots: uvicorn :8000 (mock), next dev :3000.
- Live spend: Meta $0.4782 of $130, Baseten $0.1447 of $90. Tests: 246 pass (mock).

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
- Never use `muse-wonder-1.0` in loops. Never click "Stop using free credits" on the Billing page.

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
data/synth/  generated demo data (Brightdesk, Kettle & Co)
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
