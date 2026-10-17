import pytest

from pruner.core.models import CreateVaultRequest, IngestRequest
from pruner.vault.store import VaultExistsError, VaultStore

KV = "KV cache quantization reduces memory for long context inference"
KV2 = "Quantization of the KV cache harms long context recall at four bits"
COOKING = "Sourdough bread needs a mature starter and a long cold proof"


def req(text, person="alice", kind="note", title=None):
    return IngestRequest(person=person, kind=kind, text=text, title=title)


async def test_first_item_has_no_edges_and_gets_llm_fields(store):
    res = await store.ingest(req(KV))
    assert res.edges == []
    assert res.item.title == "KV cache quantization reduces memory"
    assert res.item.tags == ["long-context", "kv-cache"]  # normalized and deduplicated
    assert "embedding" not in res.item.model_dump()


async def test_similar_items_are_linked_with_relation_and_one_line_reason(store):
    first = await store.ingest(req(KV))
    second = await store.ingest(req(KV2, person="bob"))
    [edge] = second.edges
    assert (edge.source, edge.target) == (second.item.id, first.item.id)
    assert edge.relation == "supports"
    assert edge.reason == "Fake reason spanning lines."
    assert 0.3 <= edge.weight <= 1


async def test_dissimilar_items_are_not_linked(store):
    await store.ingest(req(KV))
    res = await store.ingest(req(COOKING))
    assert res.edges == []


async def test_neighbor_count_is_capped(store, cfg):
    for i in range(5):
        await store.ingest(req(f"{KV} variant {i}"))
    res = await store.ingest(req(KV2))
    assert len(res.edges) == cfg.neighbors_per_item
    weights = [e.weight for e in res.edges]
    assert weights == sorted(weights, reverse=True)


async def test_existing_tags_are_offered_for_reuse(store, fake_llm):
    await store.ingest(req(KV))
    await store.ingest(req(COOKING))
    ingest_prompts = [p for p in fake_llm.prompts if "Existing tags" in p]
    assert "(none yet)" in ingest_prompts[0]
    assert "kv-cache, long-context" in ingest_prompts[1]


async def test_title_override_wins(store):
    res = await store.ingest(req(KV, title="My own title"))
    assert res.item.title == "My own title"


async def test_unrelated_judgement_creates_no_edge(store, fake_llm):
    await store.ingest(req(KV))
    fake_llm.relation = "unrelated"
    res = await store.ingest(req(KV2))
    assert res.edges == [] and store.graph().edges == []


async def test_missing_judgement_creates_no_edge(store, fake_llm, monkeypatch):
    await store.ingest(req(KV))
    original = fake_llm.generate

    async def drop_relations(schema, prompt, **kw):
        out = await original(schema, prompt, **kw)
        if schema.__name__ == "RelationOutput":
            out.value.relations = []
        return out

    monkeypatch.setattr(fake_llm, "generate", drop_relations)
    assert (await store.ingest(req(KV2))).edges == []


async def test_store_persists_and_reloads(store, cfg, fake_llm):
    a = await store.ingest(req(KV))
    b = await store.ingest(req(KV2, person="bob"))
    assert sorted(p.name for p in cfg.vault_dir.iterdir()) == ["_edges.json", "alice.json",
                                                                "bob.json"]
    reloaded = VaultStore(cfg.vault_dir, fake_llm, cfg)
    assert reloaded.people() == ["alice", "bob"]
    assert reloaded.get(a.item.id).embedding == store.get(a.item.id).embedding
    assert reloaded.graph().edges == b.edges


async def test_graph_filters_by_person(store):
    await store.ingest(req(KV))
    await store.ingest(req(KV2, person="bob"))
    await store.ingest(req(KV + " again"))
    alice = store.graph("alice")
    assert {n.person for n in alice.nodes} == {"alice"} and len(alice.nodes) == 2
    ids = {n.id for n in alice.nodes}
    assert all(e.source in ids and e.target in ids for e in alice.edges)
    assert len(store.graph().nodes) == 3


async def test_question_can_link_to_material_with_investigate(store):
    first = await store.ingest(req(KV))
    res = await store.ingest(req("Does KV cache quantization hurt long context recall?",
                                 kind="question"))
    [edge] = res.edges  # fake LLM says "supports"; the question forces "investigate"
    assert (edge.source, edge.target, edge.relation) == (res.item.id, first.item.id, "investigate")


async def test_new_item_linking_to_existing_question_is_investigate(store):
    q = await store.ingest(req("Does KV cache quantization hurt long context recall?",
                               kind="question"))
    res = await store.ingest(req(KV2))
    [edge] = res.edges
    assert (edge.target, edge.relation) == (q.item.id, "investigate")


async def test_lead_text_is_flagged_and_links_to_it_are_investigate(store):
    first = await store.ingest(req(KV))
    lead = await store.ingest(req(f"Maybe worth a look: investigate {KV2}"))
    assert lead.item.investigate and not first.item.investigate
    [edge] = lead.edges
    assert (edge.target, edge.relation) == (first.item.id, "investigate")


async def test_new_item_linking_to_a_flagged_lead_is_investigate(store):
    lead = await store.ingest(req(f"Look into this: {KV}"))
    res = await store.ingest(req(KV2))
    [edge] = res.edges
    assert (edge.target, edge.relation) == (lead.item.id, "investigate")


def test_create_vault_makes_an_empty_vault_that_persists(store, cfg, fake_llm):
    summary = store.create_vault("carol")
    assert (summary.person, summary.item_count) == ("carol", 0)
    assert store.people() == ["carol"] and store.graph("carol").nodes == []
    assert (cfg.vault_dir / "carol.json").read_text().strip() == "[]"
    assert VaultStore(cfg.vault_dir, fake_llm, cfg).people() == ["carol"]  # type: ignore[arg-type]


async def test_create_vault_rejects_an_existing_vault_and_ingest_fills_it(store):
    store.create_vault("alice")
    with pytest.raises(VaultExistsError):
        store.create_vault("alice")
    await store.ingest(req(KV))
    assert store.summary("alice").item_count == 1
    with pytest.raises(VaultExistsError):  # a vault created implicitly by ingest counts too
        store.create_vault("alice")


def test_person_names_cannot_collide_with_reserved_files():
    for bad in ["_edges", "_directives", "../x", "Alice", ""]:
        with pytest.raises(ValueError):
            CreateVaultRequest(person=bad)
    CreateVaultRequest(person="alice-2_b")
