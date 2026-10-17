import json

from fastapi.testclient import TestClient

from pruner.api.app import app
from pruner.api.deps import get_run_store
from pruner.core.events import Event, parse_event
from pruner.core.models import RunSnapshot
from pruner.fixtures import build_fixtures
from pruner.runs.store import RunStore, rebuild_snapshot

FIX = build_fixtures()
EVENTS: list[Event] = [parse_event(e) for e in FIX["run_events.json"]]
SNAPSHOT = RunSnapshot.model_validate(FIX["run_snapshot.json"])
RUN_ID = SNAPSHOT.run.id


def test_events_are_saved_and_read_back_in_order(tmp_path):
    store = RunStore(tmp_path)
    for e in EVENTS:
        store.append_event(e)
    assert [e.seq for e in RunStore(tmp_path).events(RUN_ID)] == [e.seq for e in EVENTS]
    assert all(e.seq > 5 for e in store.events(RUN_ID, after=5))


def test_snapshot_roundtrip_and_listing_newest_first(tmp_path):
    store = RunStore(tmp_path)
    store.save_snapshot(SNAPSHOT)
    newer = SNAPSHOT.model_copy(update={"run": SNAPSHOT.run.model_copy(
        update={"id": "r_newer", "created_at": SNAPSHOT.run.created_at + 100})})
    store.save_snapshot(newer)
    assert RunStore(tmp_path).snapshot(RUN_ID) == SNAPSHOT
    assert [r.id for r in store.list()] == ["r_newer", RUN_ID]


def test_unfinished_run_is_rebuilt_from_events(tmp_path):
    store = RunStore(tmp_path)
    for e in EVENTS:
        store.append_event(e)  # no snapshot saved: as if the process died
    rebuilt = store.snapshot(RUN_ID)
    assert rebuilt is not None
    assert {n.id for n in rebuilt.nodes} == {n.id for n in SNAPSHOT.nodes}
    assert rebuilt.run.objectives == SNAPSHOT.run.objectives
    assert [r.id for r in store.list()] == [RUN_ID]


def test_rebuild_needs_a_run_started_event():
    assert rebuild_snapshot([]) is None
    assert rebuild_snapshot([e for e in EVENTS if e.type == "activity"]) is None


def test_unknown_and_unsafe_ids_return_nothing(tmp_path):
    store = RunStore(tmp_path)
    assert store.snapshot("r_nope") is None and store.events("r_nope") == []
    assert store.snapshot("../etc") is None and store.events("../etc") == []
    assert store.list() == []


def test_routes_serve_saved_runs(tmp_path):
    store = RunStore(tmp_path)
    store.save_snapshot(SNAPSHOT)
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        client = TestClient(app)
        assert [r["id"] for r in client.get("/api/runs").json()] == [RUN_ID]
        body = client.get(f"/api/runs/{RUN_ID}").json()
        assert json.dumps(body, sort_keys=True) == json.dumps(
            SNAPSHOT.model_dump(mode="json"), sort_keys=True)
        assert client.get("/api/runs/r_nope").status_code == 404
    finally:
        app.dependency_overrides.pop(get_run_store, None)
