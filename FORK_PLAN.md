# Fork plan: make the amend agent's `fork` real

Status: backend and prompts built (work items 1-9 and the tests); frontend items 10-14 are
still open (see the fork section of TODO.txt for the contract). Backend and `prompts/` edits are allowed for
this feature only (the repo's default is frontend-only).

## Goal

After the objectives are amended, the amend agent finds the node F that the new objectives still
fit, and offers a **manual** fork there. On confirm, every node not on the root-to-F path is parked
(plus F's descendants, which are overwritten), and the run restarts from F with new hypotheses under
the amended objectives. Nothing changes until a person confirms. Undo restores the exact pre-fork
tree.

## What already exists (build on it, do not add a second agent)

- `agent/amend.py` `AmendObjectivesAgent`: walks the tree layer by layer, re-rates live children
  with `rate_layer`, and calls `fork()`, which only appends a `ForkRequest` to `forks.jsonl`.
  Today it forks only where ALL children score low (`backtrack_below`, `zone == "park"`).
- `orchestrator/steering.py`: `apply_rerate` writes `directive_score` and also parks or restores
  nodes; `suggest()` turns fork requests into `Suggestion(source="fork", action="expand")`;
  `job_for()` maps a confirmed fork suggestion to `Job(node, "new_hypothesis")`.
- `orchestrator/loop.py` `steer()`: batched re-rate, auto-parks (`DeadEnd` records), then
  `host._offer(...)`. The main loop checks `host._checkpoint`, `state.amends_idle`, `state.jobs`.
- `orchestrator/human.py`: keep / park / restore; `decided_by == "human"` is normally never
  overridden by the judge.
- `api/suggestions.py` + `RunManager.resolve_suggestion`: confirm and dismiss.
- Scores are 0-1 internally, shown as 0-10 via `pruner.pruning.scale.to_ten`.

## Decisions (all settled with the user)

1. **Manual only.** The fork is a suggestion a person confirms. Never applied automatically.
2. **Choosing F.** Walk down from the root. F is the **deepest node on the path whose relevance to
   the new objectives is >= 8/10** (add a config value, e.g. `FORK_RELEVANT_AT=8.0`, default 8). If
   several branches qualify, F is their **lowest common ancestor**. If nothing qualifies, **F is the
   root** (baseline). A person can slide F up or down the path on the card before confirming.
3. **What gets parked on confirm.** Everything not on the root-to-F path, plus F's descendants. That
   includes waiting nodes, finished nodes, and nodes a person kept (the keep is cleared; the card
   shows how many keeps are overridden). Hand-parked nodes stay parked. The baseline is never parked.
   Root as F parks every other branch.
4. **Exceptions.** Off-path nodes with a high relevance score are flagged on the card and pre-ticked
   "park anyway"; a person can untick any to keep that node live. No hidden threshold decides it.
5. **Not failures.** Fork-parked nodes are NOT written to `state.dead_ends` (they are off-direction,
   not failed). Their results are kept and they stay restorable.
6. **The block.** From the amend until the person confirms or dismisses: the run holds all new
   experiments and proposals (a running experiment finishes first; if it is on a node about to be
   parked, park it after it finishes). No timeout. A visible "waiting for fork decision" state
   (`Run.awaiting`, like `"choice"`). Hand keep, park and restore are rejected (409) while blocked.
7. **Score-only re-rate while blocked.** The amend's re-rate writes `directive_score`,
   `directive_reason`, `needs_remeasure`, `missing_metrics`, and nothing else. It must not park,
   restore, or touch `DeadEnd`s. Parking happens only through a confirmed fork or by hand.
8. **Dismiss.** Unblocks the run with no parking. The amended objectives and the scores stay.
9. **After confirm.** Snapshot first, then park, queue a `Job` at F (`new_hypothesis`, brief built
   from the amended objectives), log one "forked at F" event, and leave the run **paused**. Resume
   is the normal resume; it runs the Job. Web search is on in the proposer phases where it is
   already used (it needs a configured search provider; if there is none, say so on the card).
   Exploration continues from F until `max_depth` runs out.
10. **Undo (restore exactly).** "Undo fork" restores the pre-fork snapshot: node statuses, keep
    flags, `decision`, and which nodes exist, plus the dead-end list. It always works. If nodes were
    created after the fork, the button states what it will delete, for example "Undo fork: this
    deletes 6 new nodes and their results", and needs an explicit second confirm. The amended
    objectives stay (the amend happened before the fork). Undo also clears the queued Job.
11. **Superseding.** A new amend while a fork suggestion is open replaces it
    (`status="replaced"`, as steering suggestions already do).

## Work items

### Backend

1. **Models** (`core/models.py`): extend `ForkRequest` with the path scores, the proposed parked
   node ids, the count of overridden keeps and the flagged high-scoring off-path ids, and a
   status of `requested | confirmed | dismissed | replaced | undone`. Add a `ForkSnapshot` (node
   states, dead ends, objectives untouched) stored with the fork. Add `Run.awaiting = "fork"`.
   Add the config value from decision 2.
2. **Amend agent** (`agent/amend.py`): replace the "all children low" backtrack rule with decision 2.
   Keep the code-driven walk (the LLM wrapper has no function calling). `fork()` records a request
   with the data in item 1. Update `tools_for` descriptions and the module docstring.
3. **Score-only re-rate** (`orchestrator/steering.py` + `loop.py steer()`): split `apply_rerate`
   so the status changes (park and restore) are separate from the score writes. `steer()` uses only
   the score writes while a fork is pending. Keep the old behaviour only if there is a case with no
   fork pending that still needs it; the user's intent is that parking comes only from a confirmed
   fork or by hand.
4. **Block**: add the fork pause to `LiveRun` / the main loop. The loop waits on it like `amends_idle`
   and `choice_changed`, after the current experiment finishes. Set and clear `Run.awaiting`. Emit
   `RunUpdated`. The block must survive a reload (`RunSnapshot`) and the recovery path
   (`RunManager.recover`, which reloads a run paused).
5. **Human actions** (`orchestrator/human.py`): reject keep, park and restore with `IllegalAction`
   while a fork is pending.
6. **Confirm** (`RunManager.resolve_suggestion`, a new fork function, probably in a new
   `orchestrator/fork.py`): validate F is still on a valid path; snapshot; park the set; clear
   keeps; no `DeadEnd`s; queue the `Job`; log the event (`Activity` + a node log entry); unblock;
   set the run to paused. Idempotent against a double confirm (409, like `SuggestionClosed`).
7. **Undo**: `POST /runs/{id}/forks/{fork_id}/undo` with a `confirm_delete` flag required when new
   nodes exist. Restores the snapshot, deletes post-fork nodes and their events and vault entries
   that only they created (check `store.py` for what a node owns), clears the Job, emits the node
   updates and removals. Check how the rewind code handles removed nodes (the comment in `steer()`
   mentions "removed by a rewind meanwhile") and reuse it.
8. **API** (`api/runs.py`, `api/suggestions.py`): the fork card needs a preview endpoint or fields:
   F, reason, path with scores, nodes to be parked with counts, overridden keeps, the flagged
   high-scoring off-path nodes, and F's alternatives. Confirm takes the person's choices (moved F,
   unticked rescues). Fork suggestions must keep working through `resolve_suggestion`.
9. **Prompts** (`prompts/`): a proposer brief for the post-fork `new_hypothesis` Job that states the
   amended objectives and what is parked. Check `proposer.py` `MODE_BRIEFS`.

### Frontend (`frontend/src`)

10. `types.ts`, `api/client.ts`: the new fields and endpoints.
11. The fork card (reuse the suggestion UI; see `RunTab.tsx`): F, reason, path with scores, a slider
    for F, "parks N nodes, including M you kept", the untickable "park anyway" list, a root-fork
    warning, Confirm and Dismiss.
12. A "waiting for fork decision" banner; hand node actions disabled while blocked.
13. "Undo fork" on the fork's log event or activity row, with the delete warning and second confirm
    when new nodes exist.
14. Fixtures (`fixtures/`) so the UI can be seen without a backend.

### Tests

- Walk picks the deepest node >= 8/10; lowest common ancestor for several branches; root when none.
- A re-rate during a pending fork changes no node status and adds no `DeadEnd`.
- Confirm: the exact parked set; keeps cleared; the baseline kept; hand-parked nodes unchanged; no
  dead ends; the Job queued; the run left paused.
- Undo: exact restore before any resume; after resume, refused without `confirm_delete`, and
  with it, the new nodes are gone.
- Block: no experiment or proposal starts while pending; an in-flight experiment finishes and is
  parked; hand actions return 409; dismiss unblocks with no parking.
- Recovery and snapshot reload keep a pending fork pending.

## Open points to check while building (not asked of the user)

- The amend agent scores with `pre_score` (`rate_for_amendment`) while `steer()` scores with
  `directive_score` (`rate_for_directive`). Decide which one feeds the 8/10 threshold and show that
  one on the card. Prefer a single scoring pass so the numbers do not disagree.
- The weak-model scores are noisy, so show them on the card and keep the slider.
- Check the `ForkRequest` rows already written to `forks.jsonl`; old requests lacking the new fields
  must still load (give the new fields defaults).
