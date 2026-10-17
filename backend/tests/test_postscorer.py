import pytest

from pruner.core.models import DeadEnd, IngestRequest, Instruction, Node, Objective
from pruner.pruning.postscorer import PostScorer, apply

OBJECTIVES = [Objective(id="o1", text="Lower val_bpb"), Objective(id="o2", text="Stay in budget")]
KW = {"question": "Q?", "objectives": OBJECTIVES, "people": ["alice"]}
NOTE = "Use AdamW at 1e-3: val_bpb 1.90 vs baseline 1.95 on short training budgets"


def node(result="val_bpb 1.90 vs baseline 1.95"):
    return Node(run_id="r_1", type="experiment", description="Use AdamW at 1e-3", result=result)


def scorer(store, fake_llm, cfg):
    return PostScorer(store, fake_llm, cfg)  # type: ignore[arg-type]


async def test_good_result_is_kept_and_cites_only_shown_vault_items(store, fake_llm, cfg):
    item = (await store.ingest(IngestRequest(person="alice", text=NOTE))).item
    res = await scorer(store, fake_llm, cfg).score(node(), **KW)
    assert res.decision.verdict == "keep" and res.decision.stage == "post"
    assert res.decision.reason == "Fake reason."
    assert res.retrieved == [item.id] and res.decision.vault_items_used == [item.id]
    assert res.post_score == 0.8


async def test_weak_result_with_no_progress_is_parked(store, fake_llm, cfg):
    fake_llm.post_score = (cfg.post_score_min - 3) / 10  # 1.0: below the cutoff
    res = await scorer(store, fake_llm, cfg).score(node(), **KW)
    assert res.decision.verdict == "park"


async def test_advancing_an_objective_keeps_a_low_score_and_drops_unknown_ids(
        store, fake_llm, cfg):
    fake_llm.post_score, fake_llm.progress = (cfg.post_score_min - 3) / 10, ("o2",)
    res = await scorer(store, fake_llm, cfg).score(node(), **KW)
    assert res.criteria_progress == ["o2"]  # "c_bogus" is dropped
    assert res.decision.verdict == "keep"


async def test_prompt_includes_result_baseline_instructions_and_dead_ends(store, fake_llm, cfg):
    dead = DeadEnd(run_id="r_1", node_id="n_x", description="Wider model", reason="too slow")
    spec = Instruction(kind="spec", text="Stay under 10 seconds")
    steer = Instruction(kind="steer", text="Focus on optimizers")
    await scorer(store, fake_llm, cfg).score(
        node(), baseline="baseline val_bpb 1.95", dead_ends=[dead],
        instructions=[spec, steer], **KW)
    prompt = fake_llm.prompts[-1]
    assert "val_bpb 1.90 vs baseline 1.95" in prompt and "baseline val_bpb 1.95" in prompt
    assert "Stay under 10 seconds" in prompt and "1. Focus on optimizers" in prompt
    assert "Wider model (too slow)" in prompt


async def test_node_without_a_result_cannot_be_scored(store, fake_llm, cfg):
    with pytest.raises(ValueError):
        await scorer(store, fake_llm, cfg).score(node(result=None), **KW)


async def test_apply_sets_node_fields(store, fake_llm, cfg):
    n = node()
    fake_llm.progress = ("o1",)
    apply(n, await scorer(store, fake_llm, cfg).score(n, **KW))
    assert n.status == "done" and n.decided_by == "agent" and n.post_score == 0.8
    assert n.criteria_progress == ["o1"] and n.tokens.scorer == 15
    fake_llm.post_score, fake_llm.progress = (cfg.post_score_min - 4) / 10, ()
    apply(n, await scorer(store, fake_llm, cfg).score(n, **KW))
    assert n.status == "parked"
