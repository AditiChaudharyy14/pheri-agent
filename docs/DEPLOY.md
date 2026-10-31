# Deploying the public demo on Render

Two services from `render.yaml`: **pheri-api** (FastAPI, replay mode) and **pheri-web** (Next.js).
The API replays the model replies recorded in live runs (`data/recorded/llm.jsonl`). It has **no model
key**, sends nothing to any model, and cannot spend: `create_app()` refuses live mode unless
`PHERI_API_ALLOW_LIVE=1`, and neither is set here. Code still runs every rule check, evidence check
and the autonomy dial on every request.

Time needed: about 20 minutes, most of it waiting for the first builds.

Render's screens change from time to time. If a button is named a little differently from what is
written here, go by what it does.

---

## 0. Before we start (on the laptop)

1. All tests green: `cd api && python -m pytest`. They run in mock mode, plus one replay test.
2. The recording matches the code. That replay test passes only if every showcase card and the
   Brightdesk Muse Wonder report replay as recorded.
3. **Push only when we both agree.** CLAUDE.md asks before any push to main:
   `git push origin main`
4. On github.com, open `AditiChaudharyy14/pheri-agent` and check:
   - the repo is **Public** (a hackathon rule);
   - the latest commit is there;
   - `render.yaml` sits at the root;
   - there is **no `.env`** in the file list.

## 1. Create the services from the blueprint

1. Go to <https://dashboard.render.com> and sign in with GitHub.
2. Click **New +** (top right) and choose **Blueprint**.
3. Under "Connect a repository", find **pheri-agent**.
   - If it is not listed, click **Configure account** (or **Connect GitHub**).
   - In GitHub, choose **Only select repositories**, add `pheri-agent`, then **Save**.
   - Back in Render, refresh the list.
4. Click **Connect** next to `pheri-agent`.
5. Fill in the blueprint form:
   - **Blueprint Name:** `pheri`
   - **Branch:** `main`
   - Render lists the two services it found in `render.yaml`: `pheri-api` (Python) and `pheri-web`
     (Node), both on the **Free** plan.
6. Render asks for the one value marked `sync: false`:
   - **PHERI_API_URL** (on pheri-web): type `https://pheri-api.onrender.com`
   - We fix it in step 3 if Render gives the API a different address.
7. Check that **no key** (MODEL_API_KEY, BASETEN_API_KEY) is in the list. There should be none.
8. Click **Apply** (sometimes labelled **Deploy Blueprint**).

## 2. Check the API

1. In the dashboard, open **pheri-api** and watch **Logs**. It should show:
   - `pip install -r requirements.txt` finishing;
   - `Build successful`;
   - uvicorn `Application startup complete`;
   - "Your service is live".
2. Copy the service URL shown under its name (for example `https://pheri-api.onrender.com`).
3. Open `<API URL>/health` in the browser. Expect `{"ok":true,"mode":"replay"}`.
   - If `mode` is anything but `replay`: stop. Open **Environment** and set `PHERI_LLM_MODE` to
     `replay`.
4. Open `<API URL>/docs`. The FastAPI page loads.

## 3. Point the web app at the API

Do this only if the API URL from step 2.2 is **not** exactly `https://pheri-api.onrender.com`. Render
adds a suffix when a name is taken, e.g. `https://pheri-api-x7k2.onrender.com`.

1. Open **pheri-web**, then **Environment**.
2. Edit `PHERI_API_URL`:
   - paste the real API URL;
   - use `https://`;
   - no slash at the end.
3. Click **Save Changes**. If asked how to apply them, a plain deploy or restart is enough; no rebuild
   is needed. The web app reads the address when it starts.

## 4. Check the web app

Wait for **pheri-web** to show "Your service is live", then open its URL.

1. It redirects to `/brightdesk`.
2. The header pill reads **Recorded from a live run · synthetic data**, with **Reset demo** beside it.
3. Maya Okafor's card:
   - the message names the CSV export failing at 90% and her weekly client reports;
   - WHY NOW says "renews in 8 days";
   - the message starts "Hi Maya, your weekly report export";
   - the footer reads "Decided by Muse Spark 1.3 · $… · 3 turns · ✓ Verified: 16 code checks + judge ·
     View trace".
4. Click **View trace**. You should see Draft 1 with 3 turns, tokens and cost, marked "Recorded from a live
   run", and under it the 16 code checks and the judge's verdict on each claim.
   - On Birgunj's Morning, approve Sita Karna's card with **Same rate as their last order**: it moves to
     "Ready at 8:00", marked "approved by you (same rate as their last order)". Press **Reset demo** to
     bring the card back.
   - Open the site in a second browser (or a private window): Sita Karna's card is still waiting there.
     Each visitor has their own sandbox.
5. Back on Maya's page, click **Offer a discount**.
   - The refusal quotes the rule "Never offer discounts in a customer's first month."
   - This proves the browser's `/api` calls reach the API.
   - If it says "The Pheri API is not reachable", `PHERI_API_URL` is wrong: go back to step 3.
6. **Proof**: the report says "Written by Muse Wonder, recorded from a live run" and "Attempt 1 rejected
   by code: headline → Attempt 2 passed". At the bottom, the Verification block: 11 drafts, 2 caught by
   code, 4 by the judge, 5 retries, 1 sent to the owner, and "16 checks" under "Caught by code".
   - **Rules**: under the rules, "Before Pheri writes a message" shows the stage and plan scores, with
     "Money actions need 100%" and "Nudges need 80%".
7. **Spend**: Meta and Baseten spend against the caps. "This server" says **Replay mode**.
8. Switch to **Birgunj Saree Ghar**. Every card reads "Decided by Muse Spark 1.3".

## 5. Before recording the demo video

- **Wake both services.** Free services sleep after about 15 minutes idle, and the first request then
  takes up to a minute. Open the web URL and the API `/health` about 5 minutes before recording.
- **Reset the demo state.** Each visitor's approvals, rejections, new rules and private-mode switch live
  in their own sandbox in memory (`PHERI_PUBLIC_DEMO=1`). **Reset demo** in the header puts yours back to
  the start. To reset everyone's, on **pheri-api** open **Manual Deploy** and choose **Restart service**.
  The audit log names every action "demo visitor (public demo, no login)": there is no owner login.
- **Private mode.** Turning it on shows decisions on Muse Spark Open. Those were not recorded, so they
  come from the offline stand-in, and the cards say so. Turn it off again for the main flow.

## If something goes wrong

| What you see | What to do |
|---|---|
| pheri-api build fails on the Python version | `render.yaml` pins `PYTHON_VERSION=3.14.0`, the version the tests ran on. If Render lacks it, set `3.13` in **Environment** and redeploy. 3.13 is untested here: run the tests on it first if we can. |
| pheri-web build fails at `npm ci` | `package-lock.json` is out of step with `package.json`. On the laptop: `cd web && npm install`, run the tests, commit the lock file, push. |
| Cards say "Decided by the offline stand-in" | That conversation was not recorded: a prompt or the data changed after the recording. Locally: `python scripts/record_demo.py --live --budget <usd>` (ask first: live calls), run the tests, commit, push. |
| "The Pheri API is not reachable" | `PHERI_API_URL` on pheri-web is wrong or the API is asleep: check step 3, and open the API `/health` once. |
| The first page load is very slow | The service was asleep: wait a minute and reload. |

## What is never set on Render

- `MODEL_API_KEY`, `BASETEN_API_KEY`, `MODAL_PROXY_TOKEN`: the demo needs no model access.
- `PHERI_API_ALLOW_LIVE`: without it the API refuses live mode.
- `DATABASE_URL`: the demo keeps its state in memory; the ledger is a SQLite file in `/tmp`.
