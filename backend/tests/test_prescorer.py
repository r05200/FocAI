from pruner.core.models import DeadEnd, IngestRequest, Instruction, Node, Objective
from pruner.pruning.prescorer import PreScorer, apply

KV = "KV cache quantization reduces memory for long context inference"
OBJECTIVES = [Objective(id="o1", text="Find methods that shrink the KV cache")]
KW = {"question": "Q?", "objectives": OBJECTIVES, "people": ["alice"]}


def node(description, type="hypothesis"):
    return Node(run_id="r_1", type=type, description=description)


def scorer(store, fake_llm, cfg):
    return PreScorer(store, fake_llm, cfg)  # type: ignore[arg-type]


async def test_high_score_runs_and_cites_only_shown_vault_items(store, fake_llm, cfg):
    item = (await store.ingest(IngestRequest(person="alice", text=KV))).item
    res = await scorer(store, fake_llm, cfg).score(
        node("KV cache quantization for long context"), **KW)
    assert res.zone == "run"
    assert res.decision.verdict == "keep" and res.decision.stage == "pre"
    assert res.decision.reason == "Fake reason."
    assert res.retrieved == [item.id]
    assert res.decision.vault_items_used == [item.id]  # the invented id is dropped
    assert res.pre_score.overall == 0.8


async def test_zones_follow_the_score_on_the_ten_scale(store, fake_llm, cfg):
    # The fake judge answers pre_score * 10, so pass scores on the 1 to 10 scale divided by 10.
    cases = [
        (cfg.pre_score_min - 0.5, "park", "park"),
        (cfg.pre_score_min, "borderline", "keep"),  # the park cutoff itself is not parked
        (cfg.run_score_min - 0.1, "borderline", "keep"),
        (cfg.run_score_min, "run", "keep"),  # the run cutoff itself runs
    ]
    for score, zone, verdict in cases:
        fake_llm.pre_score = score / 10
        res = await scorer(store, fake_llm, cfg).score(node("anything"), **KW)
        assert (res.zone, res.decision.verdict) == (zone, verdict), score


async def test_siblings_are_judged_together_in_one_call(store, fake_llm, cfg):
    nodes = [node("Lower the learning rate"), node("Use AdamW"), node("Double the width")]
    calls_before = len(fake_llm.prompts)
    results = await scorer(store, fake_llm, cfg).score_siblings(nodes, **KW)
    assert len(fake_llm.prompts) - calls_before == 1
    assert [r.node_id for r in results] == [n.id for n in nodes]


async def test_only_the_primary_persons_vault_is_searched(store, fake_llm, cfg):
    await store.ingest(IngestRequest(person="bob", text=KV))
    res = await scorer(store, fake_llm, cfg).score(
        node("KV cache quantization for long context"), **KW)
    assert res.retrieved == []
    assert "(nothing close)" in fake_llm.prompts[-1]


async def test_prompt_includes_objectives_parent_and_dead_ends(store, fake_llm, cfg):
    dead = DeadEnd(run_id="r_1", node_id="n_x", description="Read about GPUs", reason="off topic")
    await scorer(store, fake_llm, cfg).score(
        node("x"), parent=node("Survey compression"), dead_ends=[dead], **KW)
    prompt = fake_llm.prompts[-1]
    assert "o1: Find methods" in prompt and "Survey compression" in prompt
    assert "Read about GPUs (off topic)" in prompt


async def test_near_repeat_of_earlier_work_is_flagged_for_the_judge(store, fake_llm, cfg):
    earlier = "Lower the learning rate from 3e-4 to 1e-4"
    a, b = node("Lower the learning rate from 3e-4 to 1e-4"), node("Add dropout to attention")
    results = await scorer(store, fake_llm, cfg).score_siblings(
        [a, b], earlier=[earlier], **KW)
    assert results[0].duplicate_of == earlier and results[1].duplicate_of is None
    assert f"Possible repeat of earlier work: {earlier}" in fake_llm.prompts[-1]


async def test_a_sibling_repeating_an_earlier_sibling_is_flagged(store, fake_llm, cfg):
    first, second = node("Use a cosine learning rate schedule"), \
        node("Use a cosine learning rate schedule")
    r1, r2 = await scorer(store, fake_llm, cfg).score_siblings([first, second], **KW)
    assert r1.duplicate_of is None and r2.duplicate_of == first.description


async def test_unjudged_candidate_defaults_to_borderline(store, fake_llm, cfg, monkeypatch):
    original = fake_llm.generate

    async def drop(schema, prompt, **kw):
        out = await original(schema, prompt, **kw)
        out.value.ratings = []
        return out

    monkeypatch.setattr(fake_llm, "generate", drop)
    res = await scorer(store, fake_llm, cfg).score(node("x"), **KW)
    assert res.zone == "borderline" and res.decision.verdict == "keep"


async def test_apply_sets_node_fields_and_parks(store, fake_llm, cfg):
    fake_llm.pre_score = (cfg.pre_score_min - 0.5) / 10
    n = node("irrelevant")
    [res] = await scorer(store, fake_llm, cfg).score_siblings([n], **KW)
    apply(n, res)
    assert n.status == "parked" and n.decided_by == "agent"
    assert n.pre_score is not None and n.tokens.scorer == 15


async def test_instructions_reach_the_prompt_spec_first_then_steering(store, fake_llm, cfg):
    spec = Instruction(kind="spec", text="Tiny model, 10 second budget")
    steer = Instruction(kind="steer", text="Ignore architecture changes")
    await scorer(store, fake_llm, cfg).score(node("x"), instructions=[spec, steer], **KW)
    prompt = fake_llm.prompts[-1]
    assert prompt.index("Tiny model, 10 second budget") < prompt.index("1. Ignore architecture")


async def test_no_instructions_renders_none(store, fake_llm, cfg):
    await scorer(store, fake_llm, cfg).score(node("x"), **KW)
    assert "User instructions" in fake_llm.prompts[-1]


async def test_people_choose_whose_vaults_are_searched(store, fake_llm, cfg):
    a = (await store.ingest(IngestRequest(person="alice", text=KV))).item
    b = (await store.ingest(IngestRequest(person="bob", text=KV + " too"))).item
    desc = node("KV cache quantization for long context")
    kw = {"question": "Q?", "objectives": OBJECTIVES}
    scorer_ = scorer(store, fake_llm, cfg)
    both = await scorer_.score(desc, people=["alice", "bob"], **kw)
    assert set(both.retrieved) == {a.id, b.id}
    assert "(note, bob)" in fake_llm.prompts[-1]
    assert (await scorer_.score(desc, people=["bob"], **kw)).retrieved == [b.id]
    assert (await scorer_.score(desc, people=[], **kw)).retrieved == []


# ---- rescore after the user amends the question or instructions


def parked(description, reason="Takes more steps", **kw):
    from pruner.core.models import Decision

    return Node(run_id="r_1", type="hypothesis", description=description, status="parked",
                decision=Decision(verdict="park", stage="pre", reason=reason), **kw)


async def test_rescore_unparks_leniently_and_parks_clearly_worse_pending(store, fake_llm, cfg):
    from pruner.pruning.prescorer import apply_rescore

    old = parked("Use a faster optimizer with more steps")
    ran = parked("Wider model", result="val_bpb 1.9")
    pend = node("Add more layers")
    done = Node(run_id="r_1", type="hypothesis", description="d", status="done")
    human = parked("Human parked this", decided_by="human")
    fake_llm.pre_score = (cfg.rescore_park_below + 0.5) / 10  # just above: not clearly off-topic
    res = await scorer(store, fake_llm, cfg).rescore(
        [old, ran, pend, done, human], instructions=[
            Instruction(kind="steer", text="Faster regardless of steps")], **KW)
    assert [r.node_id for r in res] == [old.id, ran.id, pend.id]  # done and human are skipped
    assert [r.change for r in res] == ["unparked", "unparked", "unchanged"]
    for n, r in zip([old, ran, pend], res, strict=True):
        apply_rescore(n, r)
    assert (old.status, ran.status, pend.status) == ("pending", "done", "pending")

    fake_llm.pre_score = (cfg.pre_score_min - 0.5) / 10  # below the rescore cutoff: off-topic
    res = await scorer(store, fake_llm, cfg).rescore([old, pend], **KW)
    assert {r.node_id: r.change for r in res} == {old.id: "parked", pend.id: "parked"}


async def test_rescore_shows_earlier_reason_and_new_instructions(store, fake_llm, cfg):
    await scorer(store, fake_llm, cfg).rescore(
        [parked("Faster optimizer")], instructions=[
            Instruction(kind="steer", text="Faster regardless of steps")], **KW)
    prompt = fake_llm.prompts[-1]
    assert "currently parked" in prompt
    assert "Earlier decision (park): Takes more steps" in prompt
    assert "1. Faster regardless of steps" in prompt


async def test_rescore_with_nothing_eligible_makes_no_call(store, fake_llm, cfg):
    done = Node(run_id="r_1", type="hypothesis", description="d", status="done")
    before = len(fake_llm.prompts)
    assert await scorer(store, fake_llm, cfg).rescore([done], **KW) == []
    assert len(fake_llm.prompts) == before
