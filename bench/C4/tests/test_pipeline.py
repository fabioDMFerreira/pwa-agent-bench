import asyncio
import inspect

import cli
import fetchers
import pipeline


def test_fetch_user_is_coroutine_fn():
    assert inspect.iscoroutinefunction(fetchers.fetch_user)


def test_fetch_orders_is_coroutine_fn():
    assert inspect.iscoroutinefunction(fetchers.fetch_orders)


def test_fetch_summary_is_coroutine_fn():
    assert inspect.iscoroutinefunction(fetchers.fetch_summary)


def test_run_pipeline_is_coroutine_fn():
    assert inspect.iscoroutinefunction(pipeline.run_pipeline)


def test_run_pipeline_returns_expected_shape():
    result = asyncio.run(pipeline.run_pipeline(7))
    assert result["user"] == {"id": 7, "name": "user7"}
    assert len(result["orders"]) == 2
    assert result["summary"]["user_id"] == 7


def test_pipeline_uses_gather():
    source = inspect.getsource(pipeline)
    assert "gather" in source, "pipeline.py should use asyncio.gather for concurrent fetches"


def test_cli_runs_end_to_end(capsys):
    assert cli.main(["42"]) == 0
    out = capsys.readouterr().out
    assert '"id": 42' in out
    assert '"user_id": 42' in out
