# Live runs

Every paid run, what it showed and what it cost. Mock runs are not listed. Full records of each run
(outcomes, audit log, tokens, the model's answer text; never prompts or keys) are saved locally in
`.pheri/runs/`, which is git-ignored. Baseten costs use the placeholder prices in `api/pheri/pricing.py`,
so they are estimates.

| When (UTC) | What | Result | Cost |
|---|---|---|---|
| 2026-10-27 14:31 | Private decision for Maya on Muse Spark Open (Baseten), evidence by id, effort low, 3000 limit | `send_help` by email, awaiting owner approval. Signed "Brightdesk team". 9 evidence items attached by code (5 facts, 4 quotes from T0999, T1001, sales_notes.txt#L41), none dropped, every number backed. A 10% discount was dry-run in code first and blocked by "Never offer discounts in a customer's first month". 408 output tokens (206 reasoning). Run: `20261027T143137Z-decide-4837a5.json` | Meta $0.0075 (profile), Baseten $0.0036 |
