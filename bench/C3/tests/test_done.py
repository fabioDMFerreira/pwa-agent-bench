import json
from pathlib import Path

import pytest

import todo_cli


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Rebind the module-level STATE_FILE to the new cwd
    monkeypatch.setattr(todo_cli, "STATE_FILE", Path("state.json"))


def _add_two():
    todo_cli.main(["add", "buy milk"])
    todo_cli.main(["add", "write report"])


def test_done_happy_path(capsys):
    _add_two()
    todo_cli.main(["done", "1"])
    out = capsys.readouterr().out
    assert "done: buy milk" in out


def test_done_updates_list_display(capsys):
    _add_two()
    todo_cli.main(["done", "1"])
    todo_cli.main(["list"])
    out = capsys.readouterr().out
    assert "1. [x] buy milk" in out
    assert "2. [ ] write report" in out


def test_done_persists_to_state():
    _add_two()
    todo_cli.main(["done", "2"])
    state = json.loads(Path("state.json").read_text())
    assert state == [
        {"text": "buy milk", "done": False},
        {"text": "write report", "done": True},
    ]


def test_done_idempotent(capsys):
    _add_two()
    todo_cli.main(["done", "1"])
    todo_cli.main(["done", "1"])
    out = capsys.readouterr().out
    assert "done: buy milk" in out
    state = json.loads(Path("state.json").read_text())
    assert state[0]["done"] is True


@pytest.mark.parametrize("index", ["abc", "1.5", ""])
def test_done_non_integer_index_exits(index):
    _add_two()
    before = Path("state.json").read_text()
    with pytest.raises(SystemExit) as exc_info:
        todo_cli.main(["done", index])
    assert exc_info.value.code != 0
    assert Path("state.json").read_text() == before


@pytest.mark.parametrize("index", ["0", "-1", "3", "99"])
def test_done_out_of_range_exits(index):
    _add_two()
    before = Path("state.json").read_text()
    with pytest.raises(SystemExit) as exc_info:
        todo_cli.main(["done", index])
    assert exc_info.value.code != 0
    assert Path("state.json").read_text() == before


def test_done_out_of_range_with_empty_state():
    with pytest.raises(SystemExit) as exc_info:
        todo_cli.main(["done", "1"])
    assert exc_info.value.code != 0
    assert not Path("state.json").exists()