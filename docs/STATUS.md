# Status

The claims pilot from `docs/SPEC.md`, built to `docs/PLAN.md`.

## Built

- `backend/`: FastAPI on SQLite. The database is created and seeded from `data/` on first use (never from `data/evals/` or `data/security/`). Read operations for the queue, claims, policies, claim history, plans, policy wording, the agent's instructions and the handlers. Write operations for the claim lifecycle (waiting, in progress, waiting for sign-off, decided), the agent's steps, decisions, payments and sign-off. A payout over the $1,000 limit in `data/company.json` cannot be paid until a handler signs off; the sign-off makes the payment.
- `agent/`: the UnderCover Agent, LangChain's `create_agent` on OpenRouter. Its tools reach the claim, policy, claim history, plan and policy wording through the API, and record the decision and pay the claim. Its instructions are `backend/instructions.md`, served by the API. Each run posts every tool call, tool result and message to the backend as a step.
- `dashboard/`: React and Vite in the UnderCover brand, light and dark. The queue (`#/`) with each claim's status, refreshed every two seconds, and a page for each claim (`#/claims/CLM-1001`) with the story, items, documents, policy, the agent's decision, reasons, section and payment, and the agent's activity step by step, refreshed every two seconds while it works. A claim waiting for sign-off has a panel where a handler signs off and pays it. The agent's instructions are at `#/instructions`, read only.
- `e2e/`: one test that the queue loads.

## Run it

- `uv sync` and `npm install` install everything.
- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
- `uv run -m agent` works every waiting claim in queue order, and `uv run -m agent CLM-1001` works one claim. Both need the backend running and `OPENROUTER_API_KEY` in `.env`; set `MODEL_NAME` to use another model, such as `openrouter/free`.
- `npm run check` runs every check.

The database is `backend/undercover.db`, or the file named in `UNDERCOVER_DB`. Delete it to start again from `data/`.
