# Tech stack

- `backend/`: FastAPI and SQLite. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount. The policy wording and the claims manual are stored by section and served a section at a time, with a keyword search across both.
- `agent/`: two agents, both LangChain's `create_agent` on OpenRouter, with no other agent framework. The queue agent (`agent/queue_agent.py`) plans a run, keeps its to-do list in the backend and hands each claim to `work_claim`, which runs a fresh claim agent (`agent/main.py`) on a new thread and reports back in one line. Both reach claims, documents and their instructions only through the backend's API. The rules that must hold (the cap, retries, leaving a claim for a handler, the check for missed claims) are in code, not in the instructions. LangChain middleware: `ModelRetryMiddleware` for provider errors and, with a longer backoff, rate limits; `ModelCallLimitMiddleware` to stop a claim agent that loops. The model is `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`. `MODEL_REQUESTS_PER_MINUTE`, if set, gives every agent in the process one shared `InMemoryRateLimiter`.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
