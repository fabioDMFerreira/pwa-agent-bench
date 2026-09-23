import json

import pytest

from feature_flags import Flag, FlagStore

@pytest.fixture
def flags_path(tmp_path):
    p = tmp_path / "flags.json"
    p.write_text(json.dumps([
        {"name": "new-checkout", "enabled": True, "rollout_percent": 25, "allowlist": ["u1", "u2"]},
        {"name": "dark-mode", "enabled": False, "rollout_percent": 100, "allowlist": []},
        {"name": "always-on", "enabled": True, "rollout_percent": 100, "allowlist": []},
        {"name": "always-off", "enabled": True, "rollout_percent": 0, "allowlist": []},
    ]))
    return p

def test_load_reads_all_flags(flags_path):
    store = FlagStore(flags_path)
    store.load()
    assert store.get("new-checkout") is not None
    assert store.get("dark-mode") is not None

def test_load_missing_file_is_empty(tmp_path):
    store = FlagStore(tmp_path / "does-not-exist.json")
    store.load()
    assert store.get("anything") is None

def test_get_unknown_returns_none(flags_path):
    store = FlagStore(flags_path)
    store.load()
    assert store.get("nope") is None

def test_upsert_adds_new(flags_path):
    store = FlagStore(flags_path)
    store.load()
    store.upsert(Flag(name="brand-new", enabled=True, rollout_percent=50, allowlist=[]))
    assert store.get("brand-new").rollout_percent == 50

def test_upsert_replaces_existing(flags_path):
    store = FlagStore(flags_path)
    store.load()
    store.upsert(Flag(name="dark-mode", enabled=True, rollout_percent=10, allowlist=["u9"]))
    assert store.get("dark-mode").enabled is True
    assert store.get("dark-mode").rollout_percent == 10
    assert store.get("dark-mode").allowlist == ["u9"]

def test_remove_returns_true_on_hit(flags_path):
    store = FlagStore(flags_path)
    store.load()
    assert store.remove("dark-mode") is True
    assert store.get("dark-mode") is None

def test_remove_returns_false_on_miss(flags_path):
    store = FlagStore(flags_path)
    store.load()
    assert store.remove("nope") is False

def test_save_round_trip(flags_path):
    store = FlagStore(flags_path)
    store.load()
    store.upsert(Flag(name="brand-new", enabled=True, rollout_percent=50, allowlist=["u5"]))
    store.save()

    reloaded = FlagStore(flags_path)
    reloaded.load()
    assert reloaded.get("brand-new").allowlist == ["u5"]

def test_unknown_flag_is_disabled(flags_path):
    store = FlagStore(flags_path)
    store.load()
    assert store.is_enabled("nope", "u1") is False

def test_disabled_flag_returns_false_for_all(flags_path):
    store = FlagStore(flags_path)
    store.load()
    for uid in ("u1", "u2", "u9999"):
        assert store.is_enabled("dark-mode", uid) is False

def test_allowlist_bypasses_rollout(flags_path):
    store = FlagStore(flags_path)
    store.load()
    # rollout_percent is 25 but u1/u2 are on the allowlist
    assert store.is_enabled("new-checkout", "u1") is True
    assert store.is_enabled("new-checkout", "u2") is True

def test_always_on_returns_true(flags_path):
    store = FlagStore(flags_path)
    store.load()
    for uid in ("u1", "u2", "u12345"):
        assert store.is_enabled("always-on", uid) is True

def test_always_off_returns_false(flags_path):
    store = FlagStore(flags_path)
    store.load()
    for uid in ("u1", "u2", "u12345"):
        assert store.is_enabled("always-off", uid) is False

def test_rollout_is_deterministic(flags_path):
    store = FlagStore(flags_path)
    store.load()
    first = [store.is_enabled("new-checkout", f"user{n}") for n in range(50)]
    second = [store.is_enabled("new-checkout", f"user{n}") for n in range(50)]
    assert first == second

def test_rollout_approximates_percentage(flags_path):
    store = FlagStore(flags_path)
    store.load()
    # ~25% of 1000 users should get "new-checkout" — accept 15%..35% to keep it non-flaky
    on = sum(store.is_enabled("new-checkout", f"user{n}") for n in range(1000))
    assert 150 <= on <= 350, f"got {on}/1000 — rollout skew suspicious"


def test_segment_rule_gates_rollout(tmp_path):
    store = FlagStore(tmp_path / "flags.json")
    store.upsert(Flag(name="eu-only", enabled=True, rollout_percent=100,
                      rules=[{"attribute": "country", "in": ["PT", "ES"]}]))
    assert store.is_enabled("eu-only", "u1", {"country": "PT"}) is True
    assert store.is_enabled("eu-only", "u1", {"country": "US"}) is False


def test_cli_check(flags_path, capsys):
    from feature_flags import main

    assert main(["--file", str(flags_path), "check", "always-on", "u1"]) == 0
    assert capsys.readouterr().out.strip() == "on"
