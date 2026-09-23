import json
from pathlib import Path

import pytest

import todo_cli


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Rebind the module-level STATE_FILE to the new cwd
    monkeypatch.setattr(todo_cli, "STATE_FILE", Path("state.json"))


def test_list_empty(capsys):
    todo_cli.main(["list"])
    assert "(no todos)" in capsys.readouterr().out


def test_add_then_list(capsys):
    todo_cli.main(["add", "buy milk"])
    todo_cli.main(["list"])
    out = capsys.readouterr().out
    assert "added: buy milk" in out
    assert "1. [ ] buy milk" in out


def test_add_persists_to_state():
    todo_cli.main(["add", "persistent"])
    state = json.loads(Path("state.json").read_text())
    assert state == [{"text": "persistent", "done": False}]
