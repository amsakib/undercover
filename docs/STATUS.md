# Status

The claims pilot from `docs/SPEC.md` is built, to the plan in `docs/PLAN.md`. The agent's harness from `docs/HARNESS.md` is being built to `docs/PLAN_HARNESS.md`: phases 1 (the backend), 2 (the claim agent), 3 (the queue agent and the command line) and 4 (the dashboard) are done.

## Built

- `backend/`: FastAPI on SQLite. The database is created and filled from `data/` on first use, never from `data/evals/` or `data/security/`.
  - Read operations for the queue, claims, policies, claim history (without personal details), plans, policy wording, the agent's instructions and the handlers.
  - The claim lifecycle: waiting, in progress, waiting for sign-off, decided. Operations to start a claim, record the agent's steps, record a decision, pay a claim and sign off.
  - A payout over the $1,000 limit in `data/company.json` cannot be paid until a handler signs off, whatever the agent does. The sign-off makes the payment.
- `backend/instructions.md`: the agent's instructions, served by the API to the agent and the dashboard.
- `agent/`: the UnderCover Agent, LangChain's `create_agent` on OpenRouter. Its tools reach the claim, policy, claim history, plan and policy wording through the API, and record the decision and pay the claim. Each run posts every tool call, tool result and message to the backend as a step.
- `dashboard/`: React and Vite in the UnderCover brand, light and dark.
  - `#/`: the queue with each claim's status, refreshed every two seconds.
  - `#/claims/CLM-1001`: the claim in full with its policy, the agent's decision, reasons, section and payment, and the agent's activity step by step, refreshed while it works. A claim waiting for sign-off has a panel where a handler signs off and pays it.
  - `#/instructions`: the agent's instructions, read only.
- `e2e/`: Playwright tests of the queue, a decided claim, the sign-off rule and the instructions page. They run their own backend on port 8100 with a fresh database (`e2e/test.db`) and the dashboard on port 5174, so they never touch the dev database.

## Run it

- `uv sync` and `npm install` install everything. Put `OPENROUTER_API_KEY` in `.env`.
- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
- `uv run -m agent` works every waiting claim in queue order, and `uv run -m agent CLM-1001` works one claim. Both need the backend running. They use `openai/gpt-6-luna`, or the model in `MODEL_NAME`, such as `openrouter/free`.
- `npm run check` runs every check.

The database is `backend/undercover.db`, or the file named in `UNDERCOVER_DB`. Delete it to start again from `data/`.

## Not yet checked

The agent has not been run against a real model: there was no `OPENROUTER_API_KEY` when it was built. Its whole path was checked with a scripted model against the running backend, and the tests cover it with a stub model. Its accuracy against the handlers' decisions has not been measured.
