# Plan: the agent's harness

This plan was built as written; the code was then restructured after review (see `docs/STATUS.md`). `agent/main.py` and `agent/queue_agent.py` are now `agent/api.py`, `agent/tools.py` and `agent/harness.py`, and `backend/main.py` is split into `backend/routers/`.

The brief in `docs/HARNESS.md`: one run of the UnderCover Agent works the whole queue, plans it as a to-do list the team can watch, hands each claim to a fresh subagent, looks up the claims manual and the wording section by section, and puts its own problems right. Built on the pilot as `docs/STATUS.md` describes it, with the stack in `docs/TECH_STACK.md`.

## Approach

- **Two agents, both `create_agent`.** A *queue agent* plans and runs the queue; a *claim agent* decides one claim. The queue agent's only way to work a claim is the `work_claim` tool, which builds a new claim agent on a new thread, runs it, and returns one line. The queue agent never sees a claim's documents or tool results, so its context grows by one line per claim and each claim starts clean. No new framework: LangChain's own middleware and our own tools.
- **The rules that must hold are in code, not in the instructions.** The model chooses the order, writes the to-do list and the summary. Code enforces the cap, the retries, the "never twice" rule and the missed-claim check, so a model that misbehaves cannot break them:
  - The backend already refuses a second decision (`record_decision` needs `in_progress`) and a second payment. It also gets a `release` operation that puts a failed claim back, counts the attempt, and after the second failure leaves it for a handler. It refuses to release a claim that has a decision, so a decided claim can never go back in the queue.
  - `work_claim` wraps each claim in a `try/finally`: whatever goes wrong (provider error after retries, timeout, too many steps, a crash in a tool), if the claim is still `in_progress` it is released with the reason. One bad claim returns a line like `CLM-1007 failed (timeout), back in the queue (attempt 1 of 2)` and the run goes on.
  - `work_claim` refuses a new claim once the run has started as many claims as its cap. Retrying a claim this run already started does not count again.
  - `finish_run` refuses while a waiting claim is within the cap (the run has started fewer claims than its cap and some are waiting, or one of its own claims is back in the queue), and names them. If the queue agent stops without a successful `finish_run`, the harness tells it what it missed and lets it carry on, twice at most, then closes the run with a note.
  - At the start of a run, any claim left `in_progress` by an earlier run that was killed is released, so nothing stays stuck.
- **Errors from the model provider** are retried by LangChain's `ModelRetryMiddleware` (with backoff) on both agents, and the model has a request timeout. `ModelCallLimitMiddleware` stops a claim agent that loops; that counts as a failure of that claim.
- **Rate limits, such as the 20 requests a minute on `openrouter/free`.** Three layers, from cheapest to last resort:
  1. *Stay under the limit.* One LangChain `InMemoryRateLimiter` (a token bucket) is shared by the queue agent and every claim agent in the process, passed to `ChatOpenAI` as `rate_limiter`. It is set from `MODEL_REQUESTS_PER_MINUTE` in `.env` (for example `18` for `openrouter/free`, leaving headroom); when that is unset there is no limiter, so the default model runs at full speed. Each model call waits for a token, so a run on the free model is slower but does not hit the limit.
  2. *Wait and retry a 429.* `ModelRetryMiddleware` retries rate-limit errors with a longer backoff (starting at 10 seconds, up to 60) than other provider errors, so a burst or a limit we did not know about is absorbed inside the claim.
  3. *Stop, don't burn the queue.* If a rate-limit error outlasts the retries (a daily allowance used up, say), it is not the claim's fault: `work_claim` puts the claim back in the queue without counting an attempt, and the run stops cleanly with a summary that says why. Otherwise one exhausted allowance would fail every remaining claim twice and leave them all for a handler.
- **Our own to-do tool, stored in the backend.** LangChain's `TodoListMiddleware` keeps its list in the agent's memory with three states; the brief wants four (to do, in progress, done, left for a handler) and a list the dashboard can read. So `update_todos` replaces the run's whole list in the backend, the same way `write_todos` works, and the queue page polls it. Statuses: `todo`, `in_progress`, `done`, `handler`.
- **The manual and the wording as sections.** Both documents are seeded into the database and split on their `##` headings. The claim agent gets three lookup tools instead of `get_policy_wording`: the contents of a document, one section, and a keyword search across both that returns section numbers and titles. Every section read is recorded on the claim as a `read` step ("Claims manual 9. Repeat claims"), which the claim page lists.
- **Runs in the backend.** A `runs` table holds each run's cap, to-do list, status (`running`, `finished`) and summary, so the dashboard can show the current run.
- **Model:** `deepseek/deepseek-v4.1-flash` with low reasoning effort by default; `MODEL_NAME` overrides it as before.
- **Instructions:** `backend/instructions/queue.md` and `backend/instructions/claim.md`, written from the wording and the manual only. The pilot's test that nothing in `agent/` or `backend/` mentions `data/evals` stays.

## Claim states

`waiting`, `in_progress`, `awaiting_signoff`, `decided`, and a new `needs_handler` ("Left for a handler"). Claims get an `attempts` count.

```
waiting --start--> in_progress --decision--> decided / awaiting_signoff
                       |
                    release: attempts 1 -> waiting, attempts 2 -> needs_handler
```

## API changes

Every operation keeps an `operation_id`, a one-line docstring and no optional inputs.

| Method and path | `operation_id` | What it does |
|---|---|---|
| `GET /api/documents/{document}` | `get_contents` | `wording` or `manual`: its title and the number and title of each section |
| `GET /api/documents/{document}/sections/{section}` | `get_section` | One section's text; 404 for an unknown one |
| `GET /api/documents/search?query=` | `search_documents` | Sections of either document containing every word of the query, with document, number, title and a short excerpt |
| `POST /api/claims/{claim_id}/release` | `release_claim` | Takes `reason` and `counts_as_attempt`. Only for `in_progress` (409 otherwise). Adds an `error` step with the reason and moves the claim to `waiting`. When the failure counts, it counts the attempt, and the second counted failure moves the claim to `needs_handler` instead |
| `POST /api/runs` | `start_run` | Takes `claim_limit`. Creates a run with an empty to-do list |
| `GET /api/runs/latest` | `get_latest_run` | The most recent run with its to-dos, status and summary; 404 before the first run |
| `PUT /api/runs/{run_id}/todos` | `update_todos` | Replaces the run's to-do list: each item has `text`, `status` and, when it is about a claim, `claim_id` |
| `POST /api/runs/{run_id}/finish` | `finish_run` | Takes `summary`. Marks the run finished |
| `GET /api/instructions/{name}` | `get_instructions` | `queue` or `claim` as markdown (replaces `GET /api/instructions`) |

`GET /api/policy-wording` is removed, since nothing reads the whole wording any more. `list_claims` and `get_claim` add `attempts`. Steps gain the kinds `read` and `error`.

---

## Phase 1: The backend for the harness

Everything the two agents and the dashboard will need, built and tested before any agent changes.

- `backend/db.py`: seed `data/claims_manual.md` beside the wording; split each document into sections; add `attempts` to claims and a `runs` table.
- `backend/main.py`: the routes in the table above, the `needs_handler` state and the new step kinds.
- `backend/instructions/`: move the pilot's instructions to `claim.md` for now and add a placeholder `queue.md` (both rewritten in phases 2 and 3).

Success criteria:

- [x] Tests: `get_contents` lists 14 manual sections and 12 wording sections; `get_section("manual", "9")` returns "Repeat claims" and its text; an unknown document or section is a 404
- [x] Tests: `search_documents("wild animal")` returns manual section 7; `search_documents("receipts meals")` includes manual section 10; a query that matches nothing returns an empty list
- [x] Tests: `release_claim` on an `in_progress` claim moves it to `waiting` with `attempts` 1 and an `error` step; started and released again it moves to `needs_handler` with `attempts` 2; on a `waiting`, `awaiting_signoff` or `decided` claim it returns 409 and changes nothing
- [x] Test: `release_claim` with `counts_as_attempt` false moves the claim to `waiting` with an `error` step and leaves `attempts` unchanged
- [x] Test: a claim that is `decided` cannot be started, decided or paid again (409 each time), and a released claim that is started again can be decided once
- [x] Tests: `start_run`, `update_todos` and `get_latest_run` store and return the to-do list in order with its statuses; an unknown status is a 422; `finish_run` stores the summary; `get_latest_run` is 404 before any run
- [x] Tests: `get_instructions("queue")` and `get_instructions("claim")` return text; any other name is a 404
- [x] The pilot's tests still pass, updated for the removed `/api/policy-wording`; the test that nothing from `data/evals/` or `data/security/` is seeded still passes
- [x] With `npm run dev:backend` on a fresh database, `curl "localhost:8000/api/documents/search?query=third%20claim"` returns manual section 9
- [x] `npm run check:python` passes with coverage at or above 80%

## Phase 2: The claim agent

The agent that decides one claim, now reading the manual and the wording a section at a time, and a harness function around it that never leaves a claim stuck.

- `agent/main.py`: tools `get_contents`, `get_section` and `search_documents` replace `get_policy_wording`. `run(claim_id, thread_id, llm)` records a `read` step for each section read. `ModelRetryMiddleware` and `ModelCallLimitMiddleware` on the claim agent; a timeout on the model. `DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"` with low reasoning effort. `model()` attaches the shared rate limiter when `MODEL_REQUESTS_PER_MINUTE` is set, and the retry middleware backs off longer on a 429.
- `agent/main.py`: `work_claim(claim_id, llm)` runs a fresh claim agent on a new thread id and returns one line from the claim as the backend has it (`CLM-1001 approve $420.00 decided`), or, when it fails, releases the claim with the reason and returns what went wrong and where the claim is now. A claim agent that ends without recording a decision is a failure too.
- `backend/instructions/claim.md`: rewritten from the wording and the manual: the order of work in manual section 4; look up the benefit's section of the wording, its required documents (manual 5), the payout steps (manual 6 and wording 10), the interpretation notes that apply (manual 7), story and documents disagreeing (manual 8), repeat claims (manual 9) and meals without receipts (manual 10); search when the claim has something unusual; record the sections relied on; pay within the sign-off rule as before. Nothing from `data/evals/`.

Success criteria:

- [x] Tests with a stub model: a claim agent that calls `search_documents`, `get_section("manual", "9")` and `get_section("wording", "5")` and then declines records two `read` steps naming those sections, in order, and the claim ends `decided`
- [x] Test: a stub model that raises on its first call leaves the claim `waiting` with `attempts` 1 and an `error` step, and `work_claim` returns a line saying it failed and is back in the queue
- [x] Test: the same claim failing a second time ends `needs_handler`, and the line says it is left for a handler
- [x] Test: a stub that finishes without recording a decision counts as a failure and releases the claim
- [x] Test: a stub that keeps calling tools is stopped by the call limit and the claim is released, not left `in_progress`
- [x] Test: an approve over the limit still ends `awaiting_signoff` with no payment, and `work_claim` reports it as such
- [x] Test: `ModelRetryMiddleware` retries a stub model that fails once with a provider error and then succeeds, and the claim is decided with no `error` step
- [x] Tests: with `MODEL_REQUESTS_PER_MINUTE=18`, `model()` has a rate limiter at 0.3 requests a second, and the queue and claim models share the same one; without it, there is no limiter
- [x] Test: a stub model that raises a 429 once and then succeeds decides the claim, with no `error` step and no attempt counted
- [x] Test: a stub model that keeps raising 429s puts the claim back `waiting` with `attempts` 0 and an `error` step about the rate limit, and `work_claim` reports that the provider's rate limit stopped it
- [x] `test_model_name`: the default is `deepseek/deepseek-v4.1-flash` with reasoning effort low; `MODEL_NAME=openrouter/free` overrides it
- [x] The test that nothing in `agent/` or `backend/` mentions `evals` still passes, now covering `backend/instructions/`
- [x] `npm run check:python` passes

## Phase 3: The queue agent and the command line

The agent that runs the queue: plans, delegates, recovers and finishes with a summary.

- `agent/queue_agent.py`: `run_queue(claim_limit, llm, claim_llm)` releases claims left `in_progress` by an earlier run, starts a run, and runs the queue agent with these tools:
  - `list_waiting_claims()`: id, type, summary, submitted date and amount claimed of each waiting claim, plus how many more claims this run may start
  - `update_todos(todos)`: replaces the run's to-do list in the backend
  - `work_claim(claim_id)`: the Phase 2 function, behind the cap
  - `finish_run(summary)`: the missed-claim check, then the summary to the backend
  - `ModelRetryMiddleware` on the queue agent. After the agent stops, the harness checks for missed claims and nudges it at most twice, as in the approach.
- `backend/instructions/queue.md`: list the waiting claims; plan a to-do list of the claims to work within the cap, in an order you choose and can explain (oldest submitted first unless there is a reason not to); mark each in progress before working it, done or left for a handler after; a failed claim goes back on the list to try again; check the queue again before finishing; finish with a summary for the handlers of three to six lines: decided, waiting for sign-off, left for a handler, and anything a handler should look at.
- `agent/__main__.py`: `uv run -m agent` works the whole queue; `uv run -m agent --limit 5` caps the run; `uv run -m agent CLM-1001` works one claim through `work_claim`, trying it a second time if it fails once. It prints each claim's line and, for a run, the summary.

Success criteria:

- [x] Test (stub queue model, stub claim models): a run with `--limit 2` on the seeded queue works exactly two claims, stores a to-do list that goes from `todo` to `in_progress` to `done`, finishes with the summary, and leaves the other 23 claims `waiting`
- [x] Test: `work_claim` called for a third new claim in a run capped at 2 is refused, and that claim stays `waiting`
- [x] Test: a run capped at 3 whose second claim's model raises carries on to the third claim, puts the second back in the queue, works it again and decides it, and the claim has one `error` step
- [x] Test: a claim whose model fails twice ends `needs_handler`, its to-do ends `handler`, and the run still finishes
- [x] Test: a queue model that calls `finish_run` after one claim of a cap of two is refused with the missed claim named; after it works the second the run finishes
- [x] Test: a queue model that stops without calling `finish_run` while claims within the cap are waiting is nudged and works them; a model that ignores two nudges leaves the run closed with a note, and no claim `in_progress`
- [x] Test: a run capped at 3 whose second claim hits a rate limit that outlasts the retries stops without starting the third claim, leaves the second `waiting` with no attempt counted, and finishes with a summary that names the rate limit
- [x] Test: a claim left `in_progress` before a run starts is released at the start of the run
- [x] Test: a claim that is already `decided` is refused by `work_claim` and never decided or paid twice
- [x] Tests: the command line parses no argument, `--limit 5` and a claim id, and the one-claim form works only that claim
- [x] `npm run check:python` passes

## Phase 4: The dashboard

What the team sees: the run's to-do list, the sections each claim read, the new state and both sets of instructions.

- `dashboard/src/api.ts`: `Run`, `Todo`, the `needs_handler` status, the `read` and `error` step kinds, `attempts`, and the new instructions route.
- Queue page: a "Current run" panel above the table from `get_latest_run`, refreshed every two seconds with the queue: the cap, each to-do with a status chip (To do, In progress, Done, Left for a handler) and a link to its claim, and the summary once finished. No panel before the first run.
- Status chip and queue counts: "Left for a handler".
- Claim page: a "What the agent read" panel listing the claim's `read` steps; `error` steps stand out in the activity timeline; the attempt count when it is above zero.
- Instructions page: "Running the queue" and "Working a claim", both read only.
- `e2e/`: tests that drive the run and claims through the API, as the pilot's do.

Success criteria:

- [x] Vitest: the run panel renders to-dos in order with the right labels and links, shows the summary when finished, refreshes with the queue so the to-dos tick off without a reload, and does not render before a run
- [x] Vitest: the claim page lists the sections read; an `error` step renders as an error; a `needs_handler` claim shows "Left for a handler"
- [x] Vitest: the instructions page shows both sets of instructions with no way to edit them
- [x] Playwright: after `start_run` and `update_todos` through the API, the queue page shows the to-do list; after another `update_todos` the ticked item shows Done without a reload
- [x] Playwright: a claim with `read` steps shows them under "What the agent read"; a claim released twice shows "Left for a handler" in the queue and on its page
- [x] `npm run check:ts` and `npm run e2e` pass, with no `any`
- [x] With `npm run dev`, in the browser with the Playwright MCP server, the run panel, the new chip and both instruction pages look right in light and dark mode

## Phase 5: The live run and handover

The run the brief asks for, on the real model, and the documents brought up to date.

- Reseed: stop the backend, delete `backend/undercover.db`, start `npm run dev`.
- `uv run -m agent --limit 5` with the default model, watched in the browser.
- `docs/SPEC.md`: decisions follow the wording and the claims manual; the manual leaves "Not for now"; the queue page shows the run's to-do list; the claim page shows what the agent read; a claim that fails twice is left for a handler.
- `docs/TECH_STACK.md`: the default model, the two agents, the middleware and the documents API.
- `docs/STATUS.md`: what is built and every command (`uv run -m agent`, `--limit 5`, `CLM-1001`, reseeding), and `MODEL_REQUESTS_PER_MINUTE` for rate-limited models such as `openrouter/free`.

Success criteria:

- [ ] After reseeding, `uv run -m agent --limit 5` on `deepseek/deepseek-v4.1-flash` works five claims without help, prints a line for each and a summary, and exits (not run on DeepSeek: this machine's `.env` sets `MODEL_NAME=openrouter/free`, which overrides the default. The same run on `openrouter/free` did all of this; see the free-model criterion below and `docs/STATUS.md`)
- [x] In the browser during that run (on `openrouter/free`): the to-do list appears, fills in and is ticked off; afterwards it shows the summary; 20 claims are still `waiting`
- [x] In the browser: each of the five claims shows its steps, the sections it read (at least one manual section each) and a decision or "Left for a handler"; none is `in_progress`
- [x] Trial on the free model, if its daily allowance allows: after reseeding, `MODEL_NAME=openrouter/free MODEL_REQUESTS_PER_MINUTE=18 uv run -m agent --limit 2` runs without a rate-limit failure, or, if the allowance runs out, stops cleanly with the claim back `waiting` and the reason in the summary (run with `--limit 5`, both settings from `.env`: five claims in about 12 minutes, no rate-limit failure)
- [x] `curl localhost:8000/api/runs/latest` shows the run `finished` with five claim to-dos, none `todo` or `in_progress` (the agent marked the two claims waiting for sign-off `handler` rather than `done`; `work_claim` now says which status to use)
- [x] `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as built, and every command in `docs/STATUS.md` works as written
- [x] `npm run check` passes in full

## Not in this build

From the brief and the spec: no change to the rules, including sign-off over $1,000; no sign-in, real payments or messages to customers. Also left for later days: running claims in parallel, durable state across restarts beyond releasing stuck claims, and scoring the agent against `data/evals/`.
