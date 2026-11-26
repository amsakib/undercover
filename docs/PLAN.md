# Plan: the claims pilot

The pilot from `docs/SPEC.md`: a backend that holds the claims queue, the UnderCover Agent that works it, and a dashboard where the handlers watch the agent and sign off large payouts. Built on the skeleton in `docs/STATUS.md`, with the stack in `docs/TECH_STACK.md`.

## Approach

- **The backend is the system of record and enforces the rules.** The agent and the dashboard both go through its API. The $1,000 sign-off rule lives in the backend's payment operation, not in the agent's instructions, so a misbehaving agent cannot pay early.
- **SQLite with the standard library's `sqlite3`.** Each record is kept as a JSON column next to the few fields we query or update (id, status, queue position). No ORM: the data is small and its shape already comes from `data/`.
- **Seeded from `data/` on startup when the database is empty.** The seed reads the queue, policies, customers, plans, handlers and policy wording. It never reads `data/evals/`, `data/security/` or the claims manual. The database path comes from `UNDERCOVER_DB` (default `backend/undercover.db`, git-ignored) so tests and Playwright each get a fresh one.
- **Claim states:** `waiting`, `in_progress`, `awaiting_signoff`, `decided`. The seed's `open` becomes `waiting`.
- **The agent's instructions live in the backend** (`backend/instructions.md`) and are served by the API. The agent fetches them at the start of each run, and the dashboard shows the same text read only, so the page always shows what the agent actually used.
- **Step-by-step activity:** the agent's entry point streams the graph's updates and posts each tool call, tool result and model message to the backend as a step. The dashboard polls the claim's steps while it is in progress. Polling every two seconds is simpler than websockets and good enough for three handlers.
- **Minimum personal data to the agent:** it gets the customer's claim history, not their address, phone or date of birth.

## The API

Every operation has an `operation_id`, a one-line docstring and no optional inputs.

| Method and path | `operation_id` | What it does |
|---|---|---|
| `GET /api/health` | `health` | Existing |
| `GET /api/claims` | `list_claims` | The queue in order, with each claim's id, type, summary, amount claimed and status |
| `GET /api/claims/{claim_id}` | `get_claim` | The claim in full, with its decision and payment if any |
| `GET /api/policies/{policy_id}` | `get_policy` | One policy |
| `GET /api/customers/{customer_id}/claim-history` | `get_claim_history` | The customer's earlier claims only |
| `GET /api/plans/{plan}` | `get_plan` | One plan's limits, plus the add-on definitions |
| `GET /api/policy-wording` | `get_policy_wording` | The policy wording as markdown |
| `GET /api/instructions` | `get_instructions` | The agent's instructions as markdown |
| `GET /api/handlers` | `list_handlers` | The three handlers |
| `POST /api/claims/{claim_id}/start` | `start_claim` | `waiting` to `in_progress`; 409 otherwise |
| `POST /api/claims/{claim_id}/steps` | `record_step` | Adds a step: `kind` (`tool_call`, `tool_result`, `message`) and `text` |
| `GET /api/claims/{claim_id}/steps` | `list_steps` | The claim's steps in order, with timestamps |
| `POST /api/claims/{claim_id}/decision` | `record_decision` | `decision` (`approve`, `decline`, `refer`), `payout`, `reasons`, `policy_section`. Approve over $1,000 goes to `awaiting_signoff`; everything else goes to `decided` |
| `POST /api/claims/{claim_id}/payments` | `pay_claim` | Takes `amount`. Pays only an approved claim, only the approved payout, and only when the payout is $1,000 or less or a handler has signed off; otherwise 409 with the reason |
| `POST /api/claims/{claim_id}/sign-off` | `sign_off` | Takes `handler_id`. Only for `awaiting_signoff`; records the sign-off, pays the approved payout and moves the claim to `decided` |

Decline and refer carry a payout of $0.00. All amounts are rounded to cents.

---

## Phase 1: The data and the read API

Builds the database, the seed and every read operation the agent and dashboard need. Everything later stands on this.

- `backend/db.py`: connect, create tables (`claims`, `policies`, `customers`, `plans`, `handlers`, `settings`, `decisions`, `payments`, `steps`), seed from `data/` when empty.
- `backend/main.py`: the `GET` routes in the table above, with 404s for unknown ids.
- `backend/instructions.md`: a first version of the agent's instructions (see Phase 3; written here so the route has something to serve).
- `.gitignore`: the database files.

Success criteria:

- [x] `uv run pytest backend` passes, with tests for every route and every 404
- [x] A test asserts the seed loads 25 claims, all `waiting`, in the order of `data/claims.json`
- [x] A test asserts nothing from `data/evals/` or `data/security/` is in the database (no `CLM-1901`, no held-out claim ids)
- [x] `get_claim_history` returns previous claims and no email, phone, address or date of birth
- [x] With `npm run dev:backend` running, `curl localhost:8000/api/claims` returns 25 claims starting with `CLM-1001`, and `curl localhost:8000/api/claims/CLM-1001` returns its story, items and documents
- [x] `npm run check:python` passes

## Phase 2: Decisions, payments and the sign-off rule

Builds the write operations and the claim lifecycle. The sign-off rule is enforced here, so it holds whatever the agent does.

- The `POST` routes in the table above, with the state transitions and the payment checks.
- The $1,000 limit read from `data/company.json` (`payout_approval_limit`), not hard-coded.

Success criteria:

- [x] Tests cover each transition: `waiting` to `in_progress`; `in_progress` to `decided` on decline and refer; approve at $1,000.00 or less to `decided`, then paid by `pay_claim`; approve over $1,000 to `awaiting_signoff`, then `decided` after `sign_off`
- [x] A test: `pay_claim` on an approved $1,250.00 claim before sign-off returns 409 and records no payment
- [x] Tests: `pay_claim` returns 409 for a declined or referred claim, for an amount different from the approved payout, and for a second payment
- [x] Tests: `start_claim` on a claim that is not `waiting`, `record_decision` on a claim that is not `in_progress`, and `sign_off` on a claim that is not `awaiting_signoff` each return 409; `sign_off` with an unknown handler returns 404
- [x] A test: steps come back in the order they were recorded
- [x] Every route in `/openapi.json` has an `operation_id` and a summary, checked by a test
- [x] `npm run check:python` passes with coverage at or above 80%

## Phase 3: The UnderCover Agent

Replaces the hello-world agent with one that works a claim end to end through the API.

- `agent/main.py`: tools that wrap the API (`get_claim`, `get_policy`, `get_claim_history`, `get_plan`, `get_policy_wording`, `record_decision`, `pay_claim`). `run(claim_id, thread_id)` fetches the instructions, calls `start_claim`, streams the agent with `stream_mode="updates"`, posts each step with `record_step`, and returns the final reply. Tool errors from the API (such as a 409 on payment) go back to the model as the tool's result, so it can see the payment is waiting for sign-off.
- `backend/instructions.md`: the instructions. Read the claim, policy, plan, history and wording; decide from the wording alone; work out the payout using the plan's limits, the per-item limits and the deductible where the wording applies it; record the decision with two or three sentences of reasons and the section of the wording; then pay an approved claim. Over $1,000 the payment will be refused until a handler signs off, and that is expected.
- `agent/__main__.py`: `uv run -m agent` works every `waiting` claim in queue order; `uv run -m agent CLM-1001` works one. Each run gets a new thread id. It prints one line per claim: id, decision, payout, final status.

Success criteria:

- [x] Tests with a stub model and the backend's `TestClient` (no model calls): an approve under the limit ends `decided` with a payment; an approve over the limit ends `awaiting_signoff` with no payment even though the stub calls `pay_claim`; a decline ends `decided` with no payment
- [x] A test: each tool call and result from a run shows up in `list_steps`
- [x] A test: the CLI with no argument works only the `waiting` claims, in queue order; with an id it works only that claim
- [x] A test asserts no file in `agent/` or `backend/` references `data/evals`
- [x] `test_model_name` still passes for the default model and `MODEL_NAME`
- [x] `npm run check:python` passes

## Phase 4: The dashboard queue and claim pages

Builds the handlers' two main screens and the brand.

- `dashboard/src/`: an `api.ts` with typed fetches, a queue page and a claim page, switched by the URL hash (`#/`, `#/claims/CLM-1001`) so no router library is needed.
- Queue: a table of claims in order with id, type, summary, amount claimed and a status chip (waiting, in progress, waiting for sign-off, decided), using the brand colors in that order.
- Claim: the story, items, documents, policy and plan, and the agent's decision with payout, reasons and policy section, and the payment if made.
- `docs/BRAND.md` applied: the three fonts from Google Fonts, the palette, light and dark mode from `prefers-color-scheme`, rounded panels with no outline, amounts as `$1,250.00`.

Success criteria:

- [x] Vitest tests with a mocked `fetch` render the queue with 25 rows and the right status labels, and render a claim with and without a decision
- [x] `npm run check:ts` passes with coverage at or above 80% and no `any`
- [x] With `npm run dev`, checked in the browser with the Playwright MCP server: the queue lists `CLM-1001` first; clicking it opens the claim with its documents; the browser back button returns to the queue; dark mode follows the system setting

## Phase 5: Live activity, sign-off and the instructions

Builds the rest of what the team needs to see, and the handler's half of the sign-off rule.

- Claim page: an activity timeline from `list_steps`, polled every two seconds while the claim is `in_progress` and stopped once it leaves that state.
- Claim page: for `awaiting_signoff`, a sign-off panel with the handler picker from `list_handlers` and a button that calls `sign_off` and refreshes the claim.
- An instructions page (`#/instructions`) that shows `get_instructions` read only.
- A small header with links to the queue and the instructions.

Success criteria:

- [ ] Vitest tests: the timeline renders steps in order; polling starts for `in_progress` and stops when the status changes; the sign-off button calls `sign_off` with the chosen handler and shows the claim as decided; the instructions page renders the text with no way to edit it
- [ ] `npm run check:ts` passes
- [ ] In the browser with the Playwright MCP server, after `uv run -m agent CLM-1001` with a real model: the queue shows `CLM-1001` as decided, and its page shows the decision, the reasons, the section and the agent's steps
- [ ] In the browser: a claim the agent approved over $1,000 shows "Waiting for sign-off", and signing off as a handler moves it to decided with the payment shown

## Phase 6: End-to-end tests and handover

Locks in the whole flow and documents how to run it.

- `playwright.config.ts`: the backend web server started with `UNDERCOVER_DB` pointing at a fresh file under `e2e/`, so the tests never touch the dev database.
- `e2e/`: tests that drive state through the API (start, decision, payment) rather than a model, then check the screens: the queue and its statuses, a decided claim's page, the 409 on an early payment, and a handler signing off an over-limit claim. The existing health test is replaced or kept as it still applies.
- `docs/STATUS.md`: what is built, how to run it (`npm run dev`, `uv run -m agent`, `uv run -m agent CLM-1001`), and how to reset the database (delete the file).

Success criteria:

- [ ] `npm run e2e` passes
- [ ] `uv run -m agent` with the default model works the remaining waiting claims and prints a line for each; the queue in the browser shows none left waiting
- [ ] `docs/STATUS.md` lists every command above and they each work as written
- [ ] `npm run check` passes in full

## Not in the pilot

From the spec: the claims manual, sign-in, real payments and messages to customers. Also left for later days: scoring the agent against `data/evals/`, the harness's middleware, durable state and running claims in parallel.
