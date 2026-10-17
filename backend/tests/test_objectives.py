import pytest

from pruner.core.events import ObjectivesUpdated, parse_event
from pruner.core.models import Instruction, Objective
from pruner.fixtures import build_fixtures
from pruner.runs.objectives import ObjectiveMaker
from pruner.runs.store import rebuild_snapshot


@pytest.fixture
def maker(fake_llm, cfg):
    return ObjectiveMaker(fake_llm, cfg)  # type: ignore[arg-type]


async def test_create_writes_numbered_objectives_from_the_spec(maker, fake_llm):
    fake_llm.objectives = ["- Find cheaper methods", "2) Show the accuracy cost", "  "]
    made = await maker.create(question="How to cut cost?", spec="Tiny model, 10 second budget")
    assert [(o.id, o.text, o.source) for o in made] == [
        ("o1", "Find cheaper methods", "spec"), ("o2", "Show the accuracy cost", "spec")]
    prompt = fake_llm.prompts[-1]
    assert "Tiny model, 10 second budget" in prompt and "How to cut cost?" in prompt


async def test_create_falls_back_to_the_question_and_notes_a_missing_spec(maker, fake_llm):
    fake_llm.objectives = []
    [only] = await maker.create(question="How to cut cost?")
    assert (only.id, only.text, only.source) == ("o1", "How to cut cost?", "spec")
    assert "(none; use the question)" in fake_llm.prompts[-1]


async def test_create_caps_the_count_and_drops_repeats(maker, fake_llm):
    fake_llm.objectives = [f"Objective {i}" for i in range(10)] + ["objective 0"]
    assert len(await maker.create(question="Q")) == 6
    fake_llm.objectives = ["Same thing", "same THING"]
    assert len(await maker.create(question="Q")) == 1


async def test_amend_appends_new_objectives_attributed_to_the_instruction(maker, fake_llm):
    existing = [Objective(id="o1", text="Find cheaper methods"),
                Objective(id="o2", text="Show the accuracy cost")]
    steer = Instruction(id="i_9", kind="steer", text="Faster regardless of steps")
    fake_llm.objectives = ["Minimise wall-clock time", "show the accuracy cost"]  # one repeat
    new = await maker.amend(existing, steer, question="Q")
    assert [(o.id, o.text, o.source) for o in new] == [("o3", "Minimise wall-clock time", "i_9")]
    prompt = fake_llm.prompts[-1]
    assert "o1: Find cheaper methods" in prompt and "Faster regardless of steps" in prompt


async def test_amend_may_add_nothing_and_ids_continue_after_gaps(maker, fake_llm):
    steer = Instruction(kind="steer", text="Same as before")
    existing = [Objective(id="o4", text="A")]
    fake_llm.objectives = []
    assert await maker.amend(existing, steer) == []
    fake_llm.objectives = ["B", "C", "D", "E"]
    new = await maker.amend(existing, steer)
    assert [o.id for o in new] == ["o5", "o6", "o7"]  # capped at 3


def test_objectives_event_rebuilds_the_run():
    events = [parse_event(e) for e in build_fixtures()["run_events.json"]]
    updates = [e for e in events if isinstance(e, ObjectivesUpdated)]
    assert updates and all(o.id.startswith("o") for o in updates[0].objectives)
    run = rebuild_snapshot(events).run  # type: ignore[union-attr]
    assert run.objectives == updates[-1].objectives
