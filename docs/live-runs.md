# Live runs

Every paid run, what it showed and what it cost. Mock runs are not listed. Full records of each run
(outcomes, audit log, tokens, the model's answer text; never prompts or keys) are saved locally in
`.pheri/runs/`, which is git-ignored. Baseten costs use the placeholder prices in `api/pheri/pricing.py`,
so they are estimates.

| When (UTC) | What | Result | Cost |
|---|---|---|---|
| 2026-10-27 14:31 | Private decision for Maya on Muse Spark Open (Baseten), evidence by id, effort low, 3000 limit | `send_help` by email, awaiting owner approval. Signed "Brightdesk team". 9 evidence items attached by code (5 facts, 4 quotes from T0999, T1001, sales_notes.txt#L41), none dropped, every number backed. A 10% discount was dry-run in code first and blocked by "Never offer discounts in a customer's first month". 408 output tokens (206 reasoning). Run: `20261027T143137Z-decide-4837a5.json` | Meta $0.0075 (profile), Baseten $0.0036 |
| 2026-10-27 14:32 | Muse Wonder "What Pheri learned" from the 200-customer Brightdesk twin results (`brightdesk-n200-seed7.json`), effort medium, 3000 limit | 6 findings and 3 caveats, all passing code's checks, 0 rejected: stuck and at-risk work, overall and four stages unclear, small holdouts flagged. 2904 of 3000 output tokens used (1651 reasoning): close to the limit. Run: `20261027T143250Z-learn-5b25de.json` | Meta $0.0650 |

## Not paid, recorded here because the demo uses them

| When (UTC) | What | Result | Cost |
|---|---|---|---|
| 2026-10-27 14:40 | Full customer twin, 5,000 customers per business, 10 rounds, seed 7 (`data/twin/*-n5000-seed7.json`) | Brightdesk lift +12.6 pp [+10.6, +14.6], every stage works; Kettle +12.1 pp [+9.8, +14.4], every stage works except subscriber (+3.8 [-0.6, +8.2], unclear). Learned best action matches the twin's truth in 11 of 12 stages; Brightdesk healthy learned offer_discount where the truth is offer_upgrade (Thompson under-explored upgrade after an unlucky start: 8/131). Wonder-ready summaries written (`*.wonder.json`), not sent | $0 (maths only) |
