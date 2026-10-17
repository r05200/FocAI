"""The route table is part of the contract the frontend builds against."""

import pytest
from fastapi.testclient import TestClient

from pruner.api.app import app

client = TestClient(app)

EXPECTED_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/runs"),
    ("GET", "/api/runs"),
    ("GET", "/api/runs/{run_id}"),
    ("GET", "/api/runs/{run_id}/events"),
    ("POST", "/api/runs/{run_id}/nodes/{node_id}/keep"),
    ("POST", "/api/runs/{run_id}/nodes/{node_id}/prune"),
    ("POST", "/api/runs/{run_id}/nodes/{node_id}/restore"),
    ("GET", "/api/runs/{run_id}/questions"),
    ("POST", "/api/runs/{run_id}/questions/{question_id}/answer"),
    ("GET", "/api/vault/people"),
    ("GET", "/api/vault/graph"),
    ("GET", "/api/vault/items/{item_id}"),
    ("POST", "/api/vault/items"),
    ("GET", "/api/replays"),
    ("GET", "/api/replays/{name}/events"),
}


def test_route_table_matches_expected():
    openapi_paths = client.get("/openapi.json").json()["paths"]
    actual = {(m.upper(), p) for p, ops in openapi_paths.items() for m in ops}
    assert actual == EXPECTED_ROUTES


def test_health_is_live():
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/runs", None),
        ("GET", "/api/runs/r1", None),
        ("GET", "/api/runs/r1/events", None),
        ("POST", "/api/runs/r1/nodes/n1/restore", None),
        ("GET", "/api/vault/graph", None),
        ("POST", "/api/vault/items", {"person": "alice", "text": "hello"}),
        ("POST", "/api/runs", {"question": "q", "primary_person": "alice"}),
        ("POST", "/api/runs/r1/questions/q1/answer", {"answer": "yes"}),
        ("GET", "/api/replays", None),
        ("GET", "/api/replays/demo/events", None),
    ],
)
def test_unbuilt_routes_return_501(method, path, body):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 501, resp.text


def test_request_bodies_are_validated_before_the_stub_runs():
    assert client.post("/api/runs", json={"question": "q"}).status_code == 422
    assert client.post("/api/vault/items", json={"person": "alice"}).status_code == 422
    assert client.post("/api/runs/r1/questions/q1/answer", json={}).status_code == 422
    assert client.get("/api/replays/demo/events?speed=0").status_code == 422


def test_cors_allows_the_vite_dev_server():
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
