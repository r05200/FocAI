# Prompts

One file per prompt, loaded by name from the backend. Keep prompts here, not inline in code,
so they can be tuned without touching logic. Planned (added as each step is built):

- `objectives.md` (done): specs -> 3 to 5 point-form objectives; `objectives_amend.md` (done): a new instruction -> new objectives to append
- `propose.md`: propose up to 3 next steps from a node
- `pre_score.md`, `post_score.md`, `rescore.md` (all done): scoring against the objectives and the person's vault; both take the user's instructions
- `ingest.md`: title, summary and tags for a vault item
- `profile.md`: known topics, open questions, ruled-out topics
- `synthesize.md`: final answer from kept branches
- `grader.md`: rubric coverage grader (separate from the pruner's judge)
