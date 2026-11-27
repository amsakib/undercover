# Code standards

1. Keep it simple, do not overcomplicate. Simple means easy to read and change, not the fewest files.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.

## Structure

7. One module has one job, and modules depend in one direction. Nothing reaches into another module's helpers or into an entry point.
   - `agent/`: `api.py` (every call to the backend) ← `tools.py` (every tool, and the state the tools share) ← `harness.py` (runs the agents, retries, records the steps, recovers) ← `__main__.py` (the command line).
   - `backend/`: `main.py` only puts the app together. Routes live in a router per resource in `backend/routers/`, request bodies in `schemas.py`, the database and its request dependency in `db.py`.
   - `dashboard/src/`: `api.ts` holds every call to the backend and its types; components only render.
8. One way to reach each outside system, with its address in one place. The agent calls the backend only through `agent/api.py`, the dashboard only through `dashboard/src/api.ts`. No URL or path strings anywhere else. Tests in `agent/tests/test_structure.py` and `dashboard/src/structure.test.ts` enforce this.
9. Each value has one home. A business number, such as the payout limit or the number of attempts, lives in `data/` or the backend, never copied into the agent or the dashboard.
10. Use the framework's own way before writing your own: FastAPI routers, dependencies and validation (a `Literal` path parameter, not a hand-written 404); LangChain middleware for retries, limits and tool errors; `create_agent(..., context_schema=...)` with tools taking `runtime: ToolRuntime[...]` to share run state, not closures, globals or extra arguments the model must fill in.
11. Split a function that does more than one thing or runs past about 40 lines.

## Agents

12. Keep the harness apart from the business. The harness knows how to run an agent, not what a claim is; UnderCover's rules belong in the tools, the backend, the wording and the manual.
13. An agent's instructions give it a goal, what it has to work with, what done looks like and its boundaries. They are not a numbered script: if the steps are fixed, write code. A rule that must always hold, such as a cap or "never pay twice", is enforced in code, not asked for in the instructions.
