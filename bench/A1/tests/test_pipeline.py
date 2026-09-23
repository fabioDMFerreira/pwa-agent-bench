import json

from ingest import IngestPipeline


def ev(i, ts="2026-01-01T00:00:00Z", source="web", type_="click", user=1):
    return json.dumps({"source": source, "id": i, "type": type_, "ts": ts, "user_id": user})


def make(**kw):
    batches = []
    p = IngestPipeline(batches.append, lambda uid: {"id": uid}, **kw)
    return p, batches


def test_accepts_and_flushes_on_close():
    p, batches = make()
    assert p.submit(ev(1)) == "accepted"
    p.close()
    assert len(batches) == 1 and batches[0][0]["id"] == 1


def test_duplicate_dropped():
    p, _ = make()
    p.submit(ev(1))
    assert p.submit(ev(1)) == "duplicate"


def test_invalid_json():
    p, _ = make()
    assert p.submit("{not json") == "invalid"


def test_batch_size_triggers_flush():
    p, batches = make(batch_size=2)
    p.submit(ev(1))
    p.submit(ev(2))
    assert len(batches) == 1 and p.pending() == 0


def test_enriches_user():
    p, batches = make()
    p.submit(ev(1, user=7))
    p.flush()
    assert batches[0][0]["user"] == {"id": 7}
