"""Runs of the queue: each run's cap, to-do list, status and summary."""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import DB, now
from backend.schemas import RunFinish, RunStart, Todo

router = APIRouter(prefix="/api/runs")


def run_record(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    """Return one run with its to-do list, or raise a 404."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"No run {run_id}")
    return {**dict(row), "todos": json.loads(row["todos"])}


@router.post("", operation_id="start_run")
def start_run(start: RunStart, conn: DB) -> dict[str, Any]:
    """Start a run of the queue, capped at a number of claims."""
    cursor = conn.execute(
        "INSERT INTO runs (claim_limit, status, todos, summary, started_at) "
        "VALUES (?, 'running', '[]', '', ?)",
        (start.claim_limit, now()),
    )
    conn.commit()
    return run_record(conn, cursor.lastrowid or 0)


@router.get("/latest", operation_id="get_latest_run")
def get_latest_run(conn: DB) -> dict[str, Any] | None:
    """Get the most recent run with its to-do list, or null before the first."""
    row = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()
    return None if row[0] is None else run_record(conn, row[0])


@router.get("/{run_id}", operation_id="get_run")
def get_run(run_id: int, conn: DB) -> dict[str, Any]:
    """Get one run with its to-do list."""
    return run_record(conn, run_id)


@router.put("/{run_id}/todos", operation_id="update_todos")
def update_todos(run_id: int, todos: list[Todo], conn: DB) -> dict[str, Any]:
    """Replace a run's to-do list."""
    run_record(conn, run_id)
    conn.execute(
        "UPDATE runs SET todos = ? WHERE run_id = ?",
        (json.dumps([t.model_dump() for t in todos]), run_id),
    )
    conn.commit()
    return run_record(conn, run_id)


@router.post("/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, finish: RunFinish, conn: DB) -> dict[str, Any]:
    """Finish a run with a summary for the handlers."""
    run_record(conn, run_id)
    conn.execute(
        "UPDATE runs SET status = 'finished', summary = ?, finished_at = ? "
        "WHERE run_id = ?",
        (finish.summary, now(), run_id),
    )
    conn.commit()
    return run_record(conn, run_id)
