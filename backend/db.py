"""The UnderCover database: SQLite, seeded from data/ when empty."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent.parent / "data"
DEFAULT_PATH = Path(__file__).parent / "undercover.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY, position INTEGER, status TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS policies (policy_id TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS customers (customer_id TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS plans (plan TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS handlers (handler_id TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    claim_id TEXT PRIMARY KEY, decision TEXT, payout REAL, reasons TEXT,
    policy_section TEXT, decided_at TEXT, signed_off_by TEXT, signed_off_at TEXT);
CREATE TABLE IF NOT EXISTS payments (
    claim_id TEXT PRIMARY KEY, amount REAL, paid_by TEXT, paid_at TEXT);
CREATE TABLE IF NOT EXISTS steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT, kind TEXT,
    text TEXT, at TEXT);
"""


def load(name: str) -> Any:
    """Read one JSON file from data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def seed(conn: sqlite3.Connection) -> None:
    """Fill an empty database from the queue and records in data/."""
    claims = load("claims.json")
    conn.executemany(
        "INSERT INTO claims VALUES (?, ?, 'waiting', ?)",
        [(c["claim_id"], i, json.dumps(c)) for i, c in enumerate(claims)],
    )
    for table, key, file in [
        ("policies", "policy_id", "policies.json"),
        ("customers", "customer_id", "customers.json"),
        ("handlers", "handler_id", "handlers.json"),
    ]:
        rows = load(file)
        conn.executemany(
            f"INSERT INTO {table} VALUES (?, ?)",  # noqa: S608
            [(r[key], json.dumps(r)) for r in rows],
        )
    plans = load("plans.json")
    conn.executemany(
        "INSERT INTO plans VALUES (?, ?)",
        [(p["plan"], json.dumps(p)) for p in plans["plans"]],
    )
    wording = (DATA / "policy_wording.md").read_text(encoding="utf-8")
    conn.executemany(
        "INSERT INTO settings VALUES (?, ?)",
        [
            ("company", json.dumps(load("company.json"))),
            ("add_ons", json.dumps(plans["add_ons"])),
            ("deductible_applies_to", json.dumps(plans["deductible_applies_to"])),
            ("policy_wording", json.dumps(wording)),
        ],
    )


def connect() -> sqlite3.Connection:
    """Open the database named in UNDERCOVER_DB, creating and seeding it if new."""
    path = os.getenv("UNDERCOVER_DB") or str(DEFAULT_PATH)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0:
        seed(conn)
        conn.commit()
    return conn


def setting(conn: sqlite3.Connection, key: str) -> Any:
    """Read one stored setting."""
    return json.loads(
        conn.execute("SELECT data FROM settings WHERE key = ?", (key,)).fetchone()[0]
    )
