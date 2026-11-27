# Status

The claims pilot from `docs/SPEC.md` is built, to the plan in `docs/PLAN.md`. The agent's harness from `docs/HARNESS.md` is built on top of it, to the plan in `docs/PLAN_HARNESS.md`.

## Built

- `backend/`: FastAPI on SQLite. The database is created and filled from `data/` on first use, never from `data/evals/` or `data/security/`. `main.py` puts the app together from a router per resource in `backend/routers/`: `claims.py`, `documents.py`, `reference.py` and `runs.py`. Request bodies are in `schemas.py`, the database and its request dependency in `db.py`.
  - Read operations for the queue, claims, policies, claim history (without personal details), plans, the agent's two sets of instructions and the handlers.
  - The policy wording and the claims manual, stored by section: each document's contents, one section, and a keyword search across both.
  - The claim lifecycle: waiting, in progress, waiting for sign-off, decided, and left for a handler. Operations to start a claim, record the agent's steps (including the sections it read and any problems), record a decision, pay a claim, sign off, and release a claim that failed before its decision. A release puts the claim back in the queue and counts the attempt; the second counted failure leaves it for a handler. A claim with a decision can never be released, decided or paid again.
  - A payout over the $1,000 limit in `data/company.json` cannot be paid until a handler signs off, whatever the agent does. The sign-off makes the payment.
  - Runs: each run's cap, its to-do list, its status and its summary. The latest run is `null` before the first.
- `backend/instructions/`: `queue.md` for running the queue and `claim.md` for working a claim. Each gives the agent a goal, what it has, what done looks like and its boundaries, not a script; the claim agent finds how to work a claim in the manual. The API serves them to the agents and the dashboard.
- `agent/`: the UnderCover Agent, two LangChain `create_agent` agents on OpenRouter, in four modules that depend in one direction.
  - `api.py`: every call to the backend, with its address in one place. A refusal raises `Refused` with the backend's reason.
  - `tools.py`: every tool. The claim agent's tools get their claim from `ClaimContext` through `ToolRuntime`, so a claim agent can act only on its own claim; `get_section` records each section read. The queue agent's tools share the run through `RunContext`: `work_claim` enforces the cap and says how to mark the to-do, and `finish_run` refuses while a waiting claim within the cap is missed.
  - `harness.py`: the model, the shared rate limit and the middleware (retries, a longer backoff for rate limits, a limit on model calls, and backend refusals shown to the agent as tool results). `work_claim` runs a fresh claim agent on a new thread, records every step, and releases the claim whatever goes wrong; a rate limit that outlasts the retries puts the claim back without counting an attempt and stops the run. `run_queue` releases any claim an earlier run left in progress, starts the run, nudges the queue agent twice if it stops early, and always closes the run.
  - `__main__.py`: the command line.
- `dashboard/`: React and Vite in the UnderCover brand, light and dark.
  - `#/`: the current or last run with its to-do list and summary, and the queue with each claim's status, refreshed every two seconds.
  - `#/claims/CLM-1001`: the claim in full with its policy, the agent's decision, reasons, section and payment, what the agent read, how many times it failed, and the agent's activity step by step, refreshed while it works. A claim waiting for sign-off has a panel where a handler signs off and pays it.
  - `#/instructions`: both sets of instructions, read only.
- `agent/tests/test_structure.py` and `dashboard/src/structure.test.ts` check that only the `api` modules call the backend and that the agent's modules depend in one direction.
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

## Review of the harness code

A review (`docs/HUMAN_REVIEW_HARNESS.md`) found the agent unfit for a PR: URL strings across `agent/main.py` and `agent/queue_agent.py`, two ways to call the backend, the queue agent reaching into `main.py`, the harness mixed with UnderCover's rules, and instructions written as step-by-step scripts. The agent was restructured into `api.py`, `tools.py` and `harness.py`, the backend split into routers, the dashboard's second fetch path and hard-coded payout limit removed, and the instructions rewritten as goals. `docs/CODE_STANDARDS.md` and `docs/PROCESS.md` now cover structure and a design review of every phase.

After the change, a reseeded live run, `uv run -m agent --limit 2` on `openrouter/free`, took under 3 minutes: CLM-1001 approved and paid $420.00, CLM-1002 approved and paid $580.00 (the $300 per-item limit, less the airline's $400). Working from the goal, each claim agent read manual 4 on how to work a claim, and 10 to 12 sections in all.

## Not yet checked

- A run on the default model, `deepseek/deepseek-v4.1-flash`: `MODEL_NAME=openrouter/free` is set in this machine's `.env`, which overrides it.
- The agent's accuracy against the handlers' decisions.
