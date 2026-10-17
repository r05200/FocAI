# Prompts

One file per prompt, loaded by name from the backend. Keep prompts here, not inline in code,
so they can be tuned without touching logic. Planned (added as each step is built):

- `checklist.md`: question -> 3 to 5 criteria
- `propose.md`: propose up to 3 next steps from a node
- `pre_score.md`, `post_score.md`: checklist-based scoring against the person's vault
- `ingest.md`: title, summary and tags for a vault item
- `profile.md`: known topics, open questions, ruled-out topics
- `synthesize.md`: final answer from kept branches
- `grader.md`: rubric coverage grader (separate from the pruner's judge)
