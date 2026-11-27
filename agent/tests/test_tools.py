import pytest
from langchain.tools import ToolRuntime

from agent import api, tools
from agent.tests.stubs import claim, steps


def runtime(context):
    return ToolRuntime(
        state={},
        context=context,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="1",
        store=None,
    )


def invoke(tool, context=None, **args):
    if context is not None:
        args["runtime"] = runtime(context)
    return tool.func(**args)


def test_read_tools():
    assert invoke(tools.get_policy, policy_id="POL-2001")["policy_id"] == "POL-2001"
    history = invoke(tools.get_claim_history, customer_id="CUS-3001")
    assert history[0]["claim_id"] == "CLM-0412"
    assert "per_item_limit" in invoke(tools.get_plan, plan="first")


def test_lookup_tools():
    contents = invoke(tools.get_contents, document="manual")
    assert "Repeat claims" in [s["title"] for s in contents["sections"]]
    found = invoke(tools.search_documents, query="wild animal")
    assert ("manual", "7") in [(s["document"], s["section"]) for s in found]


def test_get_section_records_the_read():
    context = tools.ClaimContext("CLM-1001")
    section = invoke(tools.get_section, context, document="manual", section="10")
    assert section["title"] == "Meals without receipts"
    assert [s["text"] for s in steps("CLM-1001")] == [
        "Claims manual 10. Meals without receipts"
    ]


def test_a_refusal_is_raised():
    with pytest.raises(api.Refused, match=r"Refused \(404\)"):
        invoke(tools.get_policy, policy_id="POL-0000")


def run_context(limit, work=lambda claim_id: f"{claim_id} worked"):
    return tools.RunContext(
        run_id=api.start_run(limit)["run_id"], claim_limit=limit, work=work
    )


def test_list_waiting_claims_shows_the_room_left():
    listing = invoke(tools.list_waiting_claims, run_context(3))
    assert listing["may_start"] == 3
    assert listing["waiting"][0]["claim_id"] == "CLM-1001"
    assert "customer_name" not in listing["waiting"][0]


def test_finish_run_names_the_missed_claims():
    context = run_context(2)
    result = invoke(tools.finish_run, context, summary="Done.")
    assert "CLM-1001, CLM-1002" in result
    assert not context.finished


def test_update_todos_saves_the_list():
    context = run_context(1)
    item = tools.TodoItem(text="Work CLM-1001", status="todo", claim_id="CLM-1001")
    assert invoke(tools.update_todos, context, todos=[item]) == "Saved 1 to-dos."
    assert api.run(context.run_id)["todos"] == [item.model_dump()]


def test_work_claim_enforces_the_cap_and_says_how_to_mark_the_to_do():
    context = run_context(1)
    assert invoke(tools.work_claim, context, claim_id="CLM-1001") == (
        "CLM-1001 worked. Mark its to-do todo, to try again."
    )
    assert "Refused: this run may start 1 claims" in invoke(
        tools.work_claim, context, claim_id="CLM-1002"
    )
    assert context.started == ["CLM-1001"]
    assert claim("CLM-1002")["status"] == "waiting"
