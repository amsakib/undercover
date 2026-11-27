import pytest
from fastapi.testclient import TestClient

from agent import api, harness
from backend.main import app


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setattr(
        api, "client", TestClient(app, base_url="http://testserver/api")
    )


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(harness, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(harness, "RATE_LIMIT_DELAY", 0.0)
