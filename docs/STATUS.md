# Status

The claims pilot from `docs/SPEC.md` is built, to the plan in `docs/PLAN.md`. The agent's harness from `docs/HARNESS.md` is built on top of it, to the plan in `docs/PLAN_HARNESS.md`.

## Built

- `backend/`: FastAPI on SQLite. The database is created and filled from `data/` on first use, never from `data/evals/` or `data/security/`.
  - Read operations for the queue, claims, policies, claim history (without personal details), plans, the agent's two sets of instructions and the handlers.
  - The policy wording and the claims manual, stored by section: each document's contents, one section, and a keyword search across both.
  - The claim lifecycle: waiting, in progress, waiting for sign-off, decided, and left for a handler. Operations to start a claim, record the agent's steps (including the sections it read and any problems), record a decision, pay a claim, sign off, and release a claim that failed before its decision. A release puts the claim back in the queue and counts the attempt; the second counted failure leaves it for a handler. A claim with a decision can never be released, decided or paid again.
  - A payout over the $1,000 limit in `data/company.json` cannot be paid until a handler signs off, whatever the agent does. The sign-off makes the payment.
  - Runs: each run's cap, its to-do list, its status and its summary.
- `backend/instructions/`: `queue.md` for running the queue and `claim.md` for working a claim, written from the wording and the manual and served by the API to the agents and the dashboard.
- `agent/`: the UnderCover Agent, two LangChain `create_agent` agents on OpenRouter.
  - `queue_agent.py`: the queue agent. It releases any claim an earlier run left in progress, starts a run, lists the waiting claims, plans and updates the to-do list, hands each claim to `work_claim`, and finishes with a summary. The code enforces the cap, refuses to finish while a waiting claim within the cap is missed, nudges the agent twice if it stops early, and closes the run with a note if it stops for good.
  - `main.py`: the claim agent and `work_claim`. Each claim gets a fresh agent on a new thread, with tools for the claim, policy, plan, history, the wording and manual by section, the decision and the payment. Every step is recorded on the claim. Whatever goes wrong, a claim that is still in progress is released. Provider errors are retried, rate limits with a longer backoff; a rate limit that outlasts the retries puts the claim back without counting an attempt and stops the run. A limit on model calls stops a claim agent that loops.
- `dashboard/`: React and Vite in the UnderCover brand, light and dark.
  - `#/`: the current or last run with its to-do list and summary, and the queue with each claim's status, refreshed every two seconds.
  - `#/claims/CLM-1001`: the claim in full with its policy, the agent's decision, reasons, section and payment, what the agent read, how many times it failed, and the agent's activity step by step, refreshed while it works. A claim waiting for sign-off has a panel where a handler signs off and pays it.
  - `#/instructions`: both sets of instructions, read only.
- `e2e/`: Playwright tests of the queue, a decided claim, the sign-off rule, the instructions page, the run's to-do list, the sections read and a claim left for a handler. They run their own backend on port 8100 with a fresh database (`e2e/test.db`) and the dashboard on port 5174, so they never touch the dev database.

## Run it

- `uv sync` and `npm install` install everything. Put `OPENROUTER_API_KEY` in `.env`.
- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
- With the backend running:
  - `uv run -m agent` works the whole queue in one run.
  - `uv run -m agent --limit 5` caps the run at five claims and leaves the rest waiting.
  - `uv run -m agent CLM-1001` works one claim, trying it a second time if it fails once.
- The agent uses `deepseek/deepseek-v4.1-flash` with low reasoning effort, or the model in `MODEL_NAME`, such as `openrouter/free`. `.env` wins over the shell, so change the model there.
- For a rate-limited model, set `MODEL_REQUESTS_PER_MINUTE` in `.env`, such as `18` for `openrouter/free` (20 a minute). Every agent in the run shares that limit.
- `npm run check` runs every check.

The database is `backend/undercover.db`, or the file named in `UNDERCOVER_DB`. To reseed, stop the backend, delete the file and start it again.

## Checked live

After reseeding, `uv run -m agent --limit 5` ran on `openrouter/free` with `MODEL_REQUESTS_PER_MINUTE=18`, the model in this machine's `.env`, in about 12 minutes. The queue agent planned five claims oldest first, worked them one by one and finished: CLM-1001 approved $420.00, CLM-1008 approved $2,240.00 and CLM-1011 approved $1,100.00 (both waiting for sign-off), CLM-1018 referred for proof of value, CLM-1010 declined. Every claim's page lists the sections it read, between 4 and 12, each with at least one manual section. The other 20 claims stayed waiting, none was left in progress and nothing hit the rate limit.

What that run showed:

- The queue agent marked the two claims waiting for sign-off as "left for a handler" and called them that in its summary, which also gave their amounts claimed rather than their payouts. `work_claim` now tells it which to-do status each outcome means. The summary is still the model's own words.
- It finished without ticking its last to-do, "Check the queue for missed claims", though the code's check for missed claims passed.

## Not yet checked

- A run on the default model, `deepseek/deepseek-v4.1-flash`: `MODEL_NAME=openrouter/free` is set in this machine's `.env`, which overrides it.
- The agent's accuracy against the handlers' decisions.
