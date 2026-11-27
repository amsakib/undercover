"""Guards on how the agent is put together, from docs/CODE_STANDARDS.md."""

import ast
from pathlib import Path

AGENT = Path(__file__).parent.parent
MODULES = [p for p in AGENT.glob("*.py") if p.name != "__init__.py"]


def imports(path):
    tree = ast.parse(path.read_text())
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "agent"
        for alias in node.names
    } | {
        node.module.removeprefix("agent.")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("agent.")
    }


def test_only_api_talks_to_the_backend():
    for path in MODULES:
        if path.name != "api.py":
            text = path.read_text()
            assert "httpx" not in text, path
            assert '"/' not in text, path


def test_modules_depend_in_one_direction():
    allowed = {
        "api.py": set(),
        "tools.py": {"api"},
        "harness.py": {"api", "tools"},
        "__main__.py": {"api", "harness"},
    }
    assert {p.name for p in MODULES} == set(allowed)
    for path in MODULES:
        assert imports(path) <= allowed[path.name], path
