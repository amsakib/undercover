import itertools

from fastapi.testclient import TestClient
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import main, queue_agent
from agent.tests.stubs import StubModel, call, claim, declines, steps, stub
from backend.main import app


def todos(*items):
    return call(
        "update_todos",
        {
            "todos": [
                {"text": f"Work {c}", "status": s, "claim_id": c} for c, s in items
            ]
        },
        "t",
    )


def work(claim_id):
    return call("work_claim", {"claim_id": claim_id}, claim_id)


def finish(summary="All done."):
    return call("finish_run", {"summary": summary}, "f")


def failing():
    return StubModel(replies=(RuntimeError("boom") for _ in itertools.count()))


def rate_limited():
    return StubModel(
        replies=(ModelRateLimitError("429 Too Many Requests") for _ in range(20))
    )


def models(plan=None):
    """Claim models by claim id: scripted ones in order, then a decline."""
    plan = {k: list(v) for k, v in (plan or {}).items()}

    def pick(claim_id):
        if plan.get(claim_id):
            return plan[claim_id].pop(0)
        return declines(claim_id)

    return pick


def statuses():
    return {c["claim_id"]: c["status"] for c in queue_agent.claims()}


def latest():
    return TestClient(app).get("/api/runs/latest").json()


def test_a_capped_run_works_only_its_claims(monkeypatch):
    saved = []
    save = queue_agent.save_todos
    monkeypatch.setattr(
        queue_agent,
        "save_todos",
        lambda run_id, items: saved.append(items) or save(run_id, items),
    )
    run = queue_agent.run_queue(
        2,
        stub(
            call("list_waiting_claims", {}),
            todos(("CLM-1001", "todo"), ("CLM-1002", "todo")),
            todos(("CLM-1001", "in_progress"), ("CLM-1002", "todo")),
            work("CLM-1001"),
            todos(("CLM-1001", "done"), ("CLM-1002", "in_progress")),
            work("CLM-1002"),
            todos(("CLM-1001", "done"), ("CLM-1002", "done")),
            finish("Two claims declined."),
            AIMessage(content="Finished."),
        ),
        models(),
    )
    assert run["status"] == "finished"
    assert run["summary"] == "Two claims declined."
    assert [t["status"] for t in saved[0]] == ["todo", "todo"]
    assert [t["status"] for t in saved[1]] == ["in_progress", "todo"]
    assert [t["status"] for t in run["todos"]] == ["done", "done"]
    now = statuses()
    assert now["CLM-1001"] == now["CLM-1002"] == "decided"
    assert list(now.values()).count("waiting") == 23


def test_list_waiting_claims_shows_the_room_left():
    run = queue_agent.Run({"run_id": 1, "claim_limit": 3})
    listing = queue_agent.queue_tools(run, models())[0].invoke({})
    assert '"may_start": 3' in listing
    assert "CLM-1001" in listing


def test_the_cap_refuses_a_new_claim():
    queue_agent.run_queue(
        2,
        stub(
            work("CLM-1001"),
            work("CLM-1002"),
            work("CLM-1003"),
            finish(),
            AIMessage(content="Finished."),
        ),
        models(),
    )
    assert statuses()["CLM-1003"] == "waiting"
    assert steps("CLM-1003") == []


def test_a_failed_claim_does_not_stop_the_run_and_is_tried_again():
    run = queue_agent.run_queue(
        3,
        stub(
            work("CLM-1001"),
            work("CLM-1002"),
            work("CLM-1003"),
            work("CLM-1002"),
            finish(),
            AIMessage(content="Finished."),
        ),
        models({"CLM-1002": [failing()]}),
    )
    assert run["status"] == "finished"
    now = statuses()
    assert now["CLM-1001"] == now["CLM-1002"] == now["CLM-1003"] == "decided"
    assert claim("CLM-1002")["attempts"] == 1
    assert len([s for s in steps("CLM-1002") if s["kind"] == "error"]) == 1


def test_a_claim_that_fails_twice_is_left_for_a_handler():
    run = queue_agent.run_queue(
        1,
        stub(
            work("CLM-1001"),
            work("CLM-1001"),
            todos(("CLM-1001", "handler")),
            finish("CLM-1001 is left for a handler."),
            AIMessage(content="Finished."),
        ),
        models({"CLM-1001": [failing(), failing()]}),
    )
    assert claim("CLM-1001")["status"] == "needs_handler"
    assert run["status"] == "finished"
    assert run["todos"][0]["status"] == "handler"


def test_finishing_early_is_refused():
    run = queue_agent.run_queue(
        2,
        stub(
            work("CLM-1001"),
            finish("Too soon."),
            work("CLM-1002"),
            finish("Two claims declined."),
            AIMessage(content="Finished."),
        ),
        models(),
    )
    assert run["summary"] == "Two claims declined."
    assert statuses()["CLM-1002"] == "decided"


def test_finish_run_names_the_missed_claims():
    run = queue_agent.Run({"run_id": 1, "claim_limit": 2})
    finish_run = queue_agent.queue_tools(run, models())[3]
    assert "CLM-1001, CLM-1002" in finish_run.invoke({"summary": "Done."})


def test_stopping_early_is_nudged():
    run = queue_agent.run_queue(
        2,
        stub(
            work("CLM-1001"),
            AIMessage(content="I think I am done."),
            work("CLM-1002"),
            AIMessage(content="Now I am done."),
            finish("Two claims declined."),
            AIMessage(content="Finished."),
        ),
        models(),
    )
    assert run["status"] == "finished"
    assert run["summary"] == "Two claims declined."


def test_ignoring_the_nudges_closes_the_run():
    run = queue_agent.run_queue(
        2,
        stub(
            AIMessage(content="Nothing to do."),
            AIMessage(content="Still nothing."),
            AIMessage(content="No."),
        ),
        models(),
    )
    assert run["status"] == "finished"
    assert run["summary"].startswith("The queue agent stopped without finishing.")
    assert "CLM-1001" in run["summary"]
    assert "in_progress" not in statuses().values()


def test_a_lasting_rate_limit_stops_the_run():
    run = queue_agent.run_queue(
        3,
        stub(work("CLM-1001"), work("CLM-1002"), work("CLM-1003")),
        models({"CLM-1002": [rate_limited()]}),
    )
    assert run["status"] == "finished"
    assert "rate limit" in run["summary"]
    assert "CLM-1001 decline $0.00 decided" in run["summary"]
    now = statuses()
    assert now["CLM-1002"] == "waiting"
    assert claim("CLM-1002")["attempts"] == 0
    assert now["CLM-1003"] == "waiting"
    assert steps("CLM-1003") == []


def test_an_error_in_the_queue_agent_closes_the_run():
    run = queue_agent.run_queue(2, failing(), models())
    assert run["summary"].startswith("Stopped by an error: RuntimeError: boom")


def test_a_claim_left_in_progress_is_released_at_the_start():
    TestClient(app).post("/api/claims/CLM-1005/start")
    queue_agent.run_queue(
        1, stub(work("CLM-1001"), finish(), AIMessage("Done.")), models()
    )
    assert statuses()["CLM-1005"] == "waiting"
    assert claim("CLM-1005")["attempts"] == 0


def test_a_decided_claim_is_never_worked_again():
    queue_agent.run_queue(
        1,
        stub(work("CLM-1001"), work("CLM-1001"), finish(), AIMessage("Done.")),
        models(),
    )
    assert len([s for s in steps("CLM-1001") if s["kind"] == "tool_call"]) == 1
    assert claim("CLM-1001")["status"] == "decided"


def test_cli_parses_its_arguments():
    assert cli.parse([]).claim_id is None
    assert cli.parse([]).limit is None
    assert cli.parse(["--limit", "5"]).limit == 5
    assert cli.parse(["CLM-1001"]).claim_id == "CLM-1001"


def test_cli_runs_the_queue(monkeypatch, capsys):
    limits = []

    def fake(limit):
        limits.append(limit)
        return {"summary": "Summary for the handlers."}

    monkeypatch.setattr(cli, "run_queue", fake)
    cli.cli(["--limit", "5"])
    cli.cli([])
    assert limits == [5, 25]
    assert "Summary for the handlers." in capsys.readouterr().out


def test_cli_works_one_claim(monkeypatch, capsys):
    tried = iter([failing(), declines("CLM-1004")])
    work_claim = main.work_claim
    monkeypatch.setattr(main, "work_claim", lambda c: work_claim(c, next(tried)))
    cli.cli(["CLM-1004"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("CLM-1004 failed")
    assert out[1] == "CLM-1004 decline $0.00 decided"
    assert statuses()["CLM-1001"] == "waiting"


def test_cli_reports_a_rate_limit(monkeypatch, capsys):
    def stop(claim_id):
        raise main.RateLimitStop(f"{claim_id} stopped by the rate limit")

    monkeypatch.setattr(main, "work_claim", stop)
    cli.cli(["CLM-1004"])
    assert "stopped by the rate limit" in capsys.readouterr().out
