import pytest


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
