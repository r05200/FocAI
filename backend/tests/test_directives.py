import pytest
from fastapi.testclient import TestClient

from pruner.api.app import app
from pruner.api.deps import get_directive_store
from pruner.core.models import Directive, DirectiveRequest, IngestRequest, Node
from pruner.core.prompts import render_instructions
from pruner.pruning.prescorer import PreScorer
from pruner.vault.directives import DirectiveStore
from pruner.vault.store import VaultStore


def add(store, text="Prefer optimizer changes", person="alice"):
    return store.add(DirectiveRequest(person=person, text=text))


def test_add_list_delete_roundtrip(tmp_path):
    store = DirectiveStore(tmp_path)
    a, b = add(store), add(store, "Stay under 10 seconds", person="bob")
    assert [d.id for d in store.list()] == [a.id, b.id]
    assert [d.id for d in store.list("bob")] == [b.id]
    assert store.delete(a.id) and not store.delete(a.id)
    assert [d.id for d in store.list()] == [b.id]


def test_directives_persist_and_do_not_pollute_the_vault(tmp_path, cfg, fake_llm):
    add(DirectiveStore(tmp_path))
    assert [d.text for d in DirectiveStore(tmp_path).list()] == ["Prefer optimizer changes"]
    vault = VaultStore(tmp_path, fake_llm, cfg)  # type: ignore[arg-type]
    assert vault.graph().nodes == [] and vault.people() == []


async def test_directives_are_not_vault_items_or_neighbors(store, cfg, fake_llm):
    add(DirectiveStore(cfg.vault_dir), "KV cache quantization reduces memory")
    res = await store.ingest(IngestRequest(person="alice", text="KV cache quantization"))
    assert res.edges == [] and len(store.graph().nodes) == 1
    assert fake_llm.prompts and all("directive" not in p.lower() for p in fake_llm.prompts)


def test_directive_kind_exists_but_cannot_be_ingested_as_an_item():
    from typing import get_args

    from pruner.core.models import VaultKind

    assert "directive" in get_args(VaultKind)  # same kinds as the frontend
    with pytest.raises(ValueError, match="POST /api/vault/directives"):
        IngestRequest(person="alice", kind="directive", text="x")


def test_render_instructions_appends_directives():
    d = Directive(person="alice", text="Prefer optimizer changes")
    assert render_instructions([], [d]) == (
        "Standing directives from the user:\n- Prefer optimizer changes")
    assert render_instructions([], []) == "(none)"


async def test_scorer_prompt_includes_directives(store, fake_llm, cfg, tmp_path):
    d = add(DirectiveStore(tmp_path), "Ignore architecture changes")
    await PreScorer(store, fake_llm, cfg).score(  # type: ignore[arg-type]
        Node(run_id="r", type="hypothesis", description="x"),
        question="Q?", objectives=[], people=["alice"], directives=[d])
    assert "- Ignore architecture changes" in fake_llm.prompts[-1]


def test_routes(tmp_path):
    app.dependency_overrides[get_directive_store] = lambda: DirectiveStore(tmp_path)
    try:
        client = TestClient(app)
        made = client.post("/api/vault/directives",
                           json={"person": "alice", "text": " Prefer optimizer changes "})
        assert made.status_code == 201 and made.json()["text"] == "Prefer optimizer changes"
        assert [d["id"] for d in client.get("/api/vault/directives?person=alice").json()] \
            == [made.json()["id"]]
        assert client.get("/api/vault/directives?person=bob").json() == []
        assert client.delete(f"/api/vault/directives/{made.json()['id']}").status_code == 204
        assert client.delete("/api/vault/directives/dir_nope").status_code == 404
        assert client.post("/api/vault/directives",
                           json={"person": "alice", "text": ""}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_directive_store, None)


def test_frontend_sent_directives_render_as_plain_texts_or_stored_ones():
    stored = Directive(person="alice", text="Prefer optimizer changes")
    block = render_instructions([], ["  Stay under 10 seconds ", "", stored])
    assert block == ("Standing directives from the user:\n"
                     "- Stay under 10 seconds\n- Prefer optimizer changes")


async def test_directive_texts_reach_scorer_and_objective_prompts(store, fake_llm, cfg):
    from pruner.core.models import Instruction, Objective
    from pruner.runs.objectives import ObjectiveMaker

    await PreScorer(store, fake_llm, cfg).score(  # type: ignore[arg-type]
        Node(run_id="r", type="hypothesis", description="x"),
        question="Q?", objectives=[], people=["alice"], directives=["Ignore architecture"])
    assert "- Ignore architecture" in fake_llm.prompts[-1]

    maker = ObjectiveMaker(fake_llm, cfg)  # type: ignore[arg-type]
    await maker.create(question="Q?", spec="Tiny model", directives=["Prefer optimizers"])
    prompt = fake_llm.prompts[-1]
    assert prompt.index("Tiny model") < prompt.index("- Prefer optimizers")
    await maker.amend([Objective(id="o1", text="A")],
                      Instruction(kind="steer", text="Go faster"), directives=["No new deps"])
    assert "Go faster" in fake_llm.prompts[-1] and "- No new deps" in fake_llm.prompts[-1]


def test_requests_carry_directives_from_the_frontend():
    from pruner.core.models import InstructionRequest, StartRunRequest

    start = StartRunRequest(question="Q", primary_person="alice", directives=["a", "b"])
    assert start.directives == ["a", "b"]
    assert StartRunRequest(question="Q", primary_person="alice").directives == []
    assert InstructionRequest(text="x").directives is None  # omitted: keep the run's list
    assert InstructionRequest(text="x", directives=[]).directives == []  # empty: clear them
