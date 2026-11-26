# Status

The claims pilot from `docs/SPEC.md`, built to `docs/PLAN.md`.

## Built

- `backend/`: FastAPI on SQLite. The database is created and seeded from `data/` on first use (never from `data/evals/` or `data/security/`). Read operations for the queue, claims, policies, claim history, plans, policy wording, the agent's instructions and the handlers.
- `agent/`: the hello-world skeleton, still to be replaced.
- `dashboard/`: one page that shows whether the backend is up.
- `e2e/`: one test of that page.

## Run it

- `uv sync` and `npm install` install everything.
- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
- `npm run check` runs every check.

The database is `backend/undercover.db`, or the file named in `UNDERCOVER_DB`. Delete it to start again from `data/`.
