import hashlib
import hmac
import json

import pytest

from notify import (
    NotificationService,
    Settings,
    TemplateStore,
    User,
    UserDirectory,
    WebhookSender,
    render,
)


class FakeTransport:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, headers, timeout))
        status = self.statuses.pop(0) if self.statuses else 200
        if isinstance(status, Exception):
            raise status
        return status


def settings(**kw):
    return Settings(api_token="tok-123", **kw)


def make_sender(statuses, **kw):
    sleeps = []
    t = FakeTransport(statuses)
    return WebhookSender(t, settings(**kw), sleep=sleeps.append), t, sleeps


# -- config -----------------------------------------------------------------

def test_settings_defaults():
    s = Settings.from_env({"NOTIFY_API_TOKEN": "x"})
    assert s.max_attempts == 3
    assert s.base_delay == 0.5


def test_settings_requires_token():
    with pytest.raises(ValueError):
        Settings.from_env({})


# -- templates --------------------------------------------------------------

def test_render_escapes_html():
    assert render("Hi $name", {"name": "<b>Bo</b>"}) == "Hi &lt;b&gt;Bo&lt;/b&gt;"


def test_render_leaves_unknown_placeholders():
    assert render("Hi $name, $missing", {"name": "Al"}) == "Hi Al, $missing"


def test_template_store_unknown():
    with pytest.raises(KeyError):
        TemplateStore({}).get("nope")


# -- webhook ----------------------------------------------------------------

def test_send_success_first_try():
    sender, t, sleeps = make_sender([200])
    res = sender.send("https://h/1", {"a": 1})
    assert res.ok and res.attempts == 1
    assert sleeps == []


def test_send_signs_exact_body():
    sender, t, _ = make_sender([200])
    sender.send("https://h/1", {"a": 1, "b": [1, 2]})
    _url, body, headers, _timeout = t.calls[0]
    expected = hmac.new(b"tok-123", body, hashlib.sha256).hexdigest()
    assert headers["X-Signature"] == f"sha256={expected}"
    assert json.loads(body) == {"a": 1, "b": [1, 2]}
    assert headers["Authorization"] == "Bearer tok-123"


def test_send_retries_503_then_succeeds():
    sender, t, sleeps = make_sender([503, 200])
    res = sender.send("https://h/1", {})
    assert res.ok and res.attempts == 2
    assert len(sleeps) == 1


def test_send_does_not_retry_404():
    sender, t, _ = make_sender([404])
    res = sender.send("https://h/1", {})
    assert not res.ok and res.status == 404 and len(t.calls) == 1


def test_send_retries_transport_error():
    sender, t, _ = make_sender([OSError("reset"), 200])
    assert sender.send("https://h/1", {}).ok


def test_send_gives_up_eventually():
    sender, t, _ = make_sender([503] * 10)
    res = sender.send("https://h/1", {})
    assert not res.ok
    assert res.status == 503


# -- service ----------------------------------------------------------------

def make_service(users, statuses=()):
    directory = UserDirectory(users)
    sender, t, _ = make_sender(statuses)
    svc = NotificationService(directory, TemplateStore({"welcome": "Hello $name, $msg"}), sender)
    return svc, directory, t


def test_notify_sends_to_each_user_once():
    users = [User(1, "Ann", "https://a"), User(2, "Bob", "https://b")]
    svc, _, t = make_service(users)
    summary = svc.notify([1, 2, 1], "welcome", {"msg": "hi"})
    assert summary.sent == 2 and summary.failed == 0
    assert [c[0] for c in t.calls] == ["https://a", "https://b"]


def test_notify_renders_per_user():
    users = [User(1, "Ann", "https://a")]
    svc, _, t = make_service(users)
    svc.notify([1], "welcome", {"msg": "hi"})
    assert json.loads(t.calls[0][1]) == {"user": 1, "text": "Hello Ann, hi"}


def test_notify_skips_inactive_and_unknown():
    users = [User(1, "Ann", "https://a", active=False), User(2, "Bob", "https://b")]
    svc, _, _ = make_service(users)
    summary = svc.notify([1, 2, 99], "welcome", {"msg": "x"})
    assert summary.sent == 1
    assert sorted(summary.skipped) == [1, 99]


def test_notify_counts_failures():
    users = [User(1, "Ann", "https://a")]
    svc, _, _ = make_service(users, statuses=[400])
    summary = svc.notify([1], "welcome", {"msg": "x"})
    assert summary.failed == 1 and summary.sent == 0
